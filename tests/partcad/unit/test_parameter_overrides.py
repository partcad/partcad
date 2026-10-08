#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A user's parameter override is read as the type the parameter declares.

'--extra-param' hands over text, and '60' used to reach a template as the string
'60' -- which a template multiplying it by three turned into '606060'.
"""

import pytest

import partcad.logging as pc_logging
from partcad.config import apply_user_parameter_overrides
from partcad_utils.user_config import user_config

OBJECT = "//test:overridden"


@pytest.fixture
def overrides():
    def set_overrides(values):
        user_config.parameter_config[OBJECT] = values

    yield set_overrides
    del user_config.parameter_config[OBJECT]
    pc_logging.reset_errors()


def declared(**parameters):
    return {"parameters": {name: {"type": kind, "default": default} for name, (kind, default) in parameters.items()}}


@pytest.mark.parametrize(
    "kind, default, text, expected",
    [
        ("int", 1, "60", 60),
        ("float", 1.0, "2.5", 2.5),
        ("bool", True, "false", False),
        ("string", "a", "60", "60"),
    ],
)
def test_an_override_takes_the_declared_type(overrides, kind, default, text, expected):
    overrides({"value": text})
    config = apply_user_parameter_overrides(declared(value=(kind, default)), OBJECT)
    assert config["parameters"]["value"]["default"] == expected
    assert type(config["parameters"]["value"]["default"]) is type(expected)


def test_an_override_that_is_not_its_type_is_an_error_and_the_default_stands(overrides):
    overrides({"count": "4.5"})
    config = apply_user_parameter_overrides(declared(count=("int", 3)), OBJECT)
    assert config["parameters"]["count"]["default"] == 3
    assert pc_logging.had_errors


def test_a_value_from_the_configuration_file_keeps_its_type(overrides):
    overrides({"count": 4, "scale": 2})
    config = apply_user_parameter_overrides(declared(count=("int", 3), scale=("float", 1.0)), OBJECT)
    assert config["parameters"]["count"]["default"] == 4
    assert config["parameters"]["scale"]["default"] == 2.0
