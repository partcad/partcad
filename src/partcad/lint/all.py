import os

from partcad_utils.assy_lint import PARTCAD_SCHEMA, get_schema

from .lint import Linting
from .python import PythonLinting
from .schema import AssySchemaLinting, SchemaLinting
from .software import SoftwareLinting

_global_lint_checks = []


def get_partcad_schema():
    """The schema every `partcad.yaml` is checked against.

    Packaged with `partcad_utils` rather than here, beside the ASSY schema and
    the checker that reads both: a client checks the `partcad.yaml` it is
    editing without a daemon and without a CAD kernel, and reaching a schema
    under `partcad` would import one to read a JSON file.
    """
    return get_schema(PARTCAD_SCHEMA)


def get_linting_checks(concurrency_cap: int) -> list[Linting]:
    global _global_lint_checks
    if concurrency_cap is None:
        concurrency_cap = max(os.cpu_count(), 8)
    Linting.MAX_CONCURRENT_CHECKS = concurrency_cap
    if len(_global_lint_checks) == 0:
        _global_lint_checks.extend(
            [
                SchemaLinting("PartcadSchema"),
                AssySchemaLinting("AssySchema"),
                PythonLinting("Python"),
                SoftwareLinting("Software"),
            ]
        )
    return _global_lint_checks
