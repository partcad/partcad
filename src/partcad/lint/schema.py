import json
import os
import yaml
import aiofiles
import jsonschema
import jsonschema.exceptions

from ..project import Project
from ..context import Context
from .. import logging as pc_logging
from partcad.cache_hash import CacheHash
from .lint import Linting, Severity, LintingReport

# Shared with every client's `pc lint --file`, which is why it is not in this
# package: the daemon checks a package's ASSY files while walking the package
# graph, and a client checks the one file being edited in its own process. Two
# copies of that check would let an editor and CI disagree about a file.
from partcad_utils.assy_lint import ASSY_SCHEMA, SEVERITY_WARNING, get_schema, schema_name_for_file, validate_source


class SchemaLinting(Linting):
    def __init__(self, name: str, schema: dict) -> None:
        super().__init__(name)
        self.schema = schema

    def get_hash(self, name: str, target: str) -> CacheHash:
        # The schema is half of what produced a finding: a cached result for an
        # unchanged file is only valid while the schema it was checked against
        # is the same one.
        hash = super().get_hash(name, target)
        hash.add_string(json.dumps(self.schema, sort_keys=True))
        return hash

    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        return [os.path.join(package.config_dir, "partcad.yaml")]

    async def validate(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        lint_result = LintingReport(package.name)
        async with aiofiles.open(target, mode="r") as file:
            # Handle file access and decoding errors
            try:
                raw = await file.read()
            except (OSError, IOError, UnicodeDecodeError) as err:
                lint_result.add(
                    Severity.FAILED,
                    f"Failed to read configuration file: {err}"
                )
                return lint_result

            # Handle YAML parsing and schema validation errors
            try:
                config = yaml.safe_load(raw)
                jsonschema.validate(instance=config, schema=self.schema)
            except jsonschema.exceptions.ValidationError as exc:
                if "unexpected" in exc.message:
                    lint_result.add(
                        Severity.WARNING,
                        f"{exc.json_path}: {exc.message}",
                    )
                else:
                    details = []
                    if exc.context:
                        root_error_location = exc.context[-1].relative_path
                        for error in reversed(exc.context):
                            if error.relative_path == root_error_location:
                                details.append(error.message)
                            else:
                                break
                    lint_result.add(
                        Severity.FAILED,
                        f"{exc.json_path}: {exc.message}" + (f" ({details})" if details else ""),
                    )
            except jsonschema.exceptions.SchemaError as exc:
                pc_logging.debug(package.name, str(exc))
                lint_result.add(Severity.FAILED, f"Internal Error: Invalid schema")

        return lint_result


class AssySchemaLinting(Linting):
    """Check every ASSY file of a package against the ASSY schema.

    ASSY files are Jinja2 templates, so unlike `partcad.yaml` above they cannot
    be handed to `yaml.safe_load()` as they are on disk. `partcad_utils.assy_lint`
    masks the template first and reports each finding at the source line it came
    from; this wraps that into the package-scoped report `pc lint` prints.

    This is the *package* half of ASSY checking: it needs the package graph to
    know which packages, and which of their files, to walk, which is what makes
    it daemon work. Checking a single file needs none of that and is done by the
    client itself (`partcad_client.lint`).
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def get_hash(self, name: str, target: str) -> CacheHash:
        # As in 'SchemaLinting' above: a schema update has to invalidate the
        # findings cached against the schema it replaced.
        hash = super().get_hash(name, target)
        hash.add_string(json.dumps(get_schema(ASSY_SCHEMA), sort_keys=True))
        return hash

    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        config_dir = package.config_dir
        if not os.path.isdir(config_dir):
            return []
        # Through the shared helper, which matches the extension case
        # insensitively: 'pc lint --file' and the extension already check a
        # 'Logo.ASSY', and the package walk skipping it is exactly the
        # editor/CI disagreement this module exists to prevent.
        return sorted(
            os.path.join(config_dir, f)
            for f in os.listdir(config_dir)
            if schema_name_for_file(f) is not None and os.path.isfile(os.path.join(config_dir, f))
        )

    async def validate(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        lint_result = LintingReport(package.name)

        # 'open' is inside the try as well: it is what raises when the entry is a
        # directory named '*.assy', or was removed between the listing and here,
        # and nothing above catches that - one unreadable entry would end the
        # whole 'pc lint' run instead of being reported as a failed check.
        try:
            async with aiofiles.open(target, mode="r") as file:
                raw = await file.read()
        except (OSError, UnicodeDecodeError) as err:
            lint_result.add(Severity.FAILED, f"Failed to read assembly file: {err}")
            return lint_result

        try:
            diagnostics = validate_source(raw, get_schema(ASSY_SCHEMA))
        except Exception as exc:  # pylint: disable=broad-except
            pc_logging.debug(package.name, str(exc))
            lint_result.add(Severity.FAILED, "Internal Error: Failed to check the assembly file")
            return lint_result

        for diagnostic in diagnostics:
            severity = Severity.WARNING if diagnostic.severity == SEVERITY_WARNING else Severity.FAILED
            lint_result.add(severity, diagnostic.format(os.path.basename(target)))

        return lint_result
