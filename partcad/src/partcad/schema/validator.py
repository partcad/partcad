import json
import yaml
import fastjsonschema
from enum import Enum
import importlib.resources

from .. import logging as pc_logging

__all__ = ["lint", "LintLevel", "LintResult", "LintMessage"]

class LintLevel(Enum):
    ERROR = 1
    WARNING = 2
    INFO = 3

class LintResult:
    def __init__(self, messages: list["LintMessage"]):
        self.messages = messages

    @property
    def is_valid(self):
        return not any(
            message.level == LintLevel.ERROR or message.level == LintLevel.WARNING for message in self.messages
        )

class LintMessage:
    def __init__(self, level: LintLevel, message: str):
        self.level = level
        self.message = message

    def __repr__(self):
        return self.message


PARTCAD_SCHEMA = None

def get_partcad_schema():
    global PARTCAD_SCHEMA
    if PARTCAD_SCHEMA is None:
        with importlib.resources.files('partcad.schema').joinpath('partcad.json').open('r') as file:
            PARTCAD_SCHEMA = json.load(file)

    return PARTCAD_SCHEMA

def lint(config_path: str) -> LintResult:
    messages = []
    validator = fastjsonschema.compile(get_partcad_schema())
    with open(config_path) as file:
        try:
            config = yaml.safe_load(file)
            validator(config)
            messages.append(LintMessage(LintLevel.INFO, "configuration is valid"))
        except fastjsonschema.JsonSchemaValueException as exc:
            if "must not contain" in exc.message:
                level = LintLevel.WARNING
                message = f"Validation Warning: {exc.message.replace('must not contain', 'contains unexpected')}"
            else:
                level = LintLevel.ERROR
                message = f"Validation Error: {exc.message}"
            messages.append(LintMessage(level, message))
        except fastjsonschema.JsonSchemaDefinitionException as exc:
            pc_logging.debug(f"Schema Error: {str(exc)}")
            messages.append(LintMessage(LintLevel.ERROR, f"Internal Error: Invalid schema"))
        except yaml.YAMLError as exc:
            messages.append(LintMessage(LintLevel.ERROR, f"YAML Error: {str(exc)}"))

    return LintResult(messages)
