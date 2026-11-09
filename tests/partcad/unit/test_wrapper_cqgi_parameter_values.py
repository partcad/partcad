#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A build parameter must reach the script, on every supported Python.

CQGI overrides a script's top-level assignment by editing the literal in its
syntax tree. It used to write the '.n' and '.s' aliases of 'ast.Constant' (and
'.id' for booleans, when 'ast.NameConstant' was missing). Python 3.14 removed
those aliases, so assigning them only added an attribute that nothing reads:
the script ran with its own defaults and every parameter in 'partcad.yaml' was
silently ignored.

These tests set each kind of parameter and run the edited tree, without
CadQuery: the script assigns plain values and builds nothing.
"""

import importlib.util
import os

import pytest

import partcad.wrapper


def _load_wrapper_module(name):
    directory = os.path.dirname(partcad.wrapper.get("cadquery.py"))
    spec = importlib.util.spec_from_file_location(name, os.path.join(directory, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


custom_cqgi = _load_wrapper_module("custom_cqgi")

SCRIPT = """
width = 41.5
pins = 8
label = "default"
flat = False
size = (1, 2)
"""


def _run(params):
    model = custom_cqgi.parse(SCRIPT)
    model.set_param_values(params)
    env = {}
    exec(compile(model.ast_tree, "<test>", "exec"), env)
    return env


def test_defaults_without_parameters():
    env = _run({})
    assert (env["width"], env["pins"], env["label"], env["flat"], env["size"]) == (41.5, 8, "default", False, (1, 2))


def test_number_parameters_override_the_script():
    env = _run({"width": 13.0, "pins": 2})
    assert env["width"] == 13.0
    assert env["pins"] == 2
    assert isinstance(env["pins"], int)


def test_string_parameter_overrides_the_script():
    assert _run({"label": "custom"})["label"] == "custom"


def test_boolean_parameter_overrides_the_script():
    assert _run({"flat": True})["flat"] is True


def test_tuple_parameter_overrides_the_script():
    assert _run({"size": (3, 4)})["size"] == (3, 4)


def test_parameter_description_is_read():
    # Read through '.s' before, which Python 3.14 removed; the bare 'except'
    # around it swallowed the AttributeError and the description was lost.
    model = custom_cqgi.parse(SCRIPT + 'describe_parameter(width, "Overall width")\n')
    assert model.metadata.parameters["width"].desc == "Overall width"


@pytest.mark.parametrize("value", ["wide", None])
def test_non_numeric_value_for_a_number_is_rejected(value):
    # 'float()' raises ValueError for a string and TypeError for None; both
    # must surface as the parameter error, not as whichever one escaped.
    with pytest.raises(custom_cqgi.InvalidParameterError):
        _run({"width": value})
