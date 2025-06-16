import os
import yaml
import aiofiles
import jsonschema
import jsonschema.exceptions

from ..project import Project
from ..context import Context
from .. import logging as pc_logging
from .lint import Linting, Severity, LintingReport


class SchemaLinting(Linting):
    def __init__(self, name: str, schema: dict) -> None:
        super().__init__(name)
        self.schema = schema

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
