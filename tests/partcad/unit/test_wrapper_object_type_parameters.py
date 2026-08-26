#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""An object-type parameter the script has no use for must not break the build.

CQGI is strict about build parameters: a name the script does not assign at top
level is a name nobody will ever read, which is almost always a typo, so it
raises. That is right for a parameter the author of the part invented, and wrong
for one the part's *type* contributed - a part can be obliged to declare a
tolerance ('pc test' requires one of anything manufactured) while the script
that builds its geometry has no interest in it.

So the factory tells the wrapper which names came from the type, and the wrapper
drops those - and only those - when the script does not declare them. A name the
script does declare is still passed through, and everything else stays strict.

What runs here: the factory's side of the request, and the filtering at the CQGI
boundary, including that the strict setter accepts what the filter produced.
Actually executing a script needs CadQuery and a CAD kernel, which this
environment does not have; that half is covered by the existing script-building
tests in CI.
"""

import asyncio
import importlib.util
import os

import pytest
import yaml

import partcad as pc
import partcad.wrapper
from partcad import shape_envelope
from partcad.part_factory_build123d import PartFactoryBuild123d
from partcad.part_factory_cadquery import PartFactoryCadquery
from partcad.part_factory_python import PartFactoryPython
from partcad.part_factory_step import PartFactoryStep

OBJECT_TYPE_PARAMETERS = ["color", "material", "tolerance"]


def _load_wrapper_module(name):
    """Import a wrapper-side module the way the sandbox does: by path.

    'wrappers/' is not a package - the sandbox puts the directory on sys.path
    and imports the scripts by name - so there is nothing to import normally.
    'custom_cqgi' is pure AST work and pulls in no CAD library, which is what
    makes the filtering testable outside a sandbox at all.
    """
    directory = os.path.dirname(partcad.wrapper.get("cadquery.py"))
    spec = importlib.util.spec_from_file_location(name, os.path.join(directory, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


custom_cqgi = _load_wrapper_module("custom_cqgi")


# ---------------------------------------------------------------- factory side


class _Stop(Exception):
    """Raised from the serializer to stop 'instantiate()' once the request exists."""


def _captured_request(monkeypatch, tmp_path, part_type):
    """The request the factory would send, without provisioning a sandbox.

    'prepare_python()' is stubbed because it installs into a sandbox, and the
    serializer is stubbed to capture the request and stop right there - which is
    as far as this test needs the real code path to run, and no further.
    """
    (tmp_path / "body.py").write_text("width = 1.0\nshow_object(None)\n")
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                "parts": {
                    "body": {
                        "type": part_type,
                        "path": "body.py",
                        "parameters": {
                            "width": {"type": "float", "default": 2.0},
                            "tolerance": {"type": "float", "default": 0.1},
                        },
                    }
                },
            }
        )
    )

    captured = {}

    async def no_sandbox(self):
        return None

    def capture(obj, *args, **kwargs):
        captured["request"] = obj
        raise _Stop()

    monkeypatch.setattr(PartFactoryPython, "prepare_python", no_sandbox)
    monkeypatch.setattr(shape_envelope, "serialize", capture)

    part = pc.Context(str(tmp_path)).get_part("//:body")
    with pytest.raises(_Stop):
        asyncio.run(part.instantiate(part))
    return captured["request"]


@pytest.mark.parametrize("part_type", ["cadquery", "build123d"])
def test_the_request_names_what_the_type_contributed(monkeypatch, tmp_path, part_type):
    """Which is what lets the wrapper tell those names from the part's own."""
    request = _captured_request(monkeypatch, tmp_path, part_type)

    # Every declared parameter is still passed to the script, as before.
    assert request["build_parameters"] == {"width": 2.0, "tolerance": 0.1}
    # ...and the type's own names travel beside them.
    assert request["object_type_parameters"] == OBJECT_TYPE_PARAMETERS


@pytest.mark.parametrize(
    "factory, expected",
    [
        (PartFactoryCadquery, OBJECT_TYPE_PARAMETERS),
        (PartFactoryBuild123d, OBJECT_TYPE_PARAMETERS),
        # A type that contributes nothing offers nothing, which leaves a wrapper
        # exactly as strict as it was.
        (PartFactoryStep, []),
    ],
)
def test_the_names_come_from_the_part_type(factory, expected):
    """Read off the class, so there is no second list to drift from it."""
    assert factory.object_type_parameter_names(factory) == expected


# ------------------------------------------------------------ wrapper/CQGI side


def _filter(script, params, optional=OBJECT_TYPE_PARAMETERS):
    model = custom_cqgi.parse(script)
    return model, custom_cqgi.filter_optional_params(model, params, optional)


def test_an_object_type_parameter_the_script_ignores_is_dropped():
    """The failure this whole change is about: the script never wanted it."""
    model, filtered = _filter("width = 1.0\n", {"width": 2.0, "tolerance": 0.1})

    assert filtered == {"width": 2.0}
    # And the strict setter, which used to raise here, is now content.
    model.set_param_values(filtered)


def test_an_object_type_parameter_the_script_declares_is_still_passed():
    """The pass-through is the point; the fix must not have removed it."""
    model, filtered = _filter(
        "width = 1.0\nmaterial = 'steel'\n",
        {"width": 2.0, "material": "brass", "tolerance": 0.1},
    )

    assert filtered == {"width": 2.0, "material": "brass"}
    model.set_param_values(filtered)


def test_a_typo_in_an_ordinary_parameter_still_raises():
    """The guard that the fix did not simply disable the check."""
    model, filtered = _filter("width = 1.0\n", {"widht": 2.0})

    assert filtered == {"widht": 2.0}
    with pytest.raises(custom_cqgi.InvalidParameterError):
        model.set_param_values(filtered)


def test_a_typo_in_an_object_type_parameter_name_is_not_privileged():
    """Only the exact names the type contributed are forgiven."""
    model, filtered = _filter("width = 1.0\n", {"matrial": "brass"})

    assert filtered == {"matrial": "brass"}
    with pytest.raises(custom_cqgi.InvalidParameterError):
        model.set_param_values(filtered)


def test_a_request_that_names_nothing_leaves_everything_strict():
    """What a sketch gets: its types contribute no object-type parameters.

    The key is absent from the request altogether, so the wrapper passes None.
    """
    model, filtered = _filter("width = 1.0\n", {"tolerance": 0.1}, optional=None)

    assert filtered == {"tolerance": 0.1}
    with pytest.raises(custom_cqgi.InvalidParameterError):
        model.set_param_values(filtered)
