import os
import json
import importlib

from .lint import Linting
from .python import PythonLinting
from .schema import SchemaLinting

PARTCAD_SCHEMA = None
_global_lint_checks = []

def get_partcad_schema():
    global PARTCAD_SCHEMA
    if PARTCAD_SCHEMA is None:
        with importlib.resources.files("partcad.schema").joinpath("partcad.json").open("r") as file:
            PARTCAD_SCHEMA = json.load(file)
    return PARTCAD_SCHEMA

def get_linting_checks(concurrency_cap: int) -> list[Linting]:
    global _global_lint_checks
    if concurrency_cap is None:
        concurrency_cap = max(os.cpu_count(), 8)
    Linting.MAX_CONCURRENT_CHECKS = concurrency_cap
    if len(_global_lint_checks) == 0:
        _global_lint_checks.extend([
            SchemaLinting("PartcadSchema", get_partcad_schema()),
            PythonLinting("Python")
        ])
    return _global_lint_checks
