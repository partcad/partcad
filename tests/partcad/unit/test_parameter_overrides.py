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
import yaml

import partcad as pc
import partcad.logging as pc_logging
from partcad.config import apply_user_parameter_overrides, parameter_overrides
from partcad_utils.user_config import UserConfig, user_config

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


# ---- whose overrides: the process's, and the context's on top ---------------
#
# '--extra-param' is part of the caller's configuration, and a daemon builds the
# context it serves a command from from that configuration -- not from its own
# process-wide one, which was resolved when the daemon started. So the context's
# overrides have to count; the process-wide ones still do as well, for a program
# that sets them against a context it already has.


def caller_config(overrides):
    config = UserConfig()
    for name, values in overrides.items():
        config.parameter_config[name] = values
    return config


def test_the_context_s_overrides_are_layered_over_the_process_s_one_parameter_at_a_time(overrides):
    overrides({"width": "1", "height": "2"})
    caller = caller_config({OBJECT: {"height": "3"}, "//test:other": {"depth": "4"}})

    merged = parameter_overrides(caller)

    assert merged[OBJECT] == {"width": "1", "height": "3"}
    assert merged["//test:other"] == {"depth": "4"}
    assert user_config.parameter_config[OBJECT] == {"width": "1", "height": "2"}


def test_an_override_only_the_context_holds_is_applied():
    caller = caller_config({OBJECT: {"value": "60"}})
    config = apply_user_parameter_overrides(declared(value=("int", 1)), OBJECT, user_config=caller)
    assert config["parameters"]["value"]["default"] == 60


def test_a_part_of_a_context_built_from_a_caller_s_configuration_takes_its_overrides(tmp_path):
    """What the daemon does with 'pc --extra-param //test:cube.size=20 ...'."""
    (tmp_path / "cube.py").write_text("size = 10.0\n")
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                "parts": {"cube": {"type": "build123d", "parameters": {"size": {"type": "float", "default": 10.0}}}},
            }
        )
    )
    # As the daemon receives it: the client's configuration, sent and rebuilt.
    caller = UserConfig.from_dict(caller_config({"//test:cube": {"size": "20"}}).to_dict())

    ctx = pc.Context(str(tmp_path), search_root=False, user_config=caller)

    assert ctx.get_project("//test").get_part_config("cube")["parameters"]["size"]["default"] == 20.0
    assert "//test:cube" not in (user_config.parameter_config.to_dict() or {})
