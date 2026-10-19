#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A Python script runs in its package's session, and says why when it fails.

A package's 'pythonRequirements', and a shape's own, are only *recorded* by
'prepare_python()': each one the sandbox does not already have marks the
package's session dirty, and nothing is installed yet. It is
'run_async(..., session=...)' that then builds the session's v-env, installs
what was recorded and runs the script there. A factory that leaves 'session='
out runs the script in the sandbox's base interpreter instead, where none of it
was ever installed - so a declared requirement fails on its first import, every
time, on every sandbox that does not happen to have it already (#774). The
build123d part factory and both sketch factories did exactly that.

The build123d part factory also logged a failed script as "Failed to produce the
part" and never recorded the script's exception on the part, so the reason never
reached 'part.errors' - where every other factory here puts it.

What runs here is each factory's side, up to the runtime: the runtime is stubbed,
so no sandbox is provisioned and no script is executed. That a session's
requirements are installed once a run is given the session is the runtime's
business, and 'test_runtime_python_deps' covers it.
"""

import asyncio

import pytest
import yaml

import partcad as pc
from partcad import shape_envelope
from partcad.part_factory_python import PartFactoryPython
from partcad.sketch_factory_python import SketchFactoryPython

MISSING = "No module named 'shapely'"

SCRIPTS = {
    "cadquery": "import shapely\nimport cadquery as cq\nshow_object(cq.Workplane('XY').box(1, 1, 1))\n",
    "build123d": "import shapely\nfrom build123d import Box\nshow_object(Box(1, 1, 1))\n",
    "sdf": "import shapely\nfrom sdf import sphere\nf = sphere(1)\n",
}


def _instantiate(monkeypatch, tmp_path, kind, shape_type):
    """Instantiate one scripted shape whose script fails on a declared requirement.

    'prepare_python()' is where a factory first holds a runtime it is about to
    use, so that is where the runtime is stubbed: installs do nothing, and a run
    records what it was given and answers the way the wrapper does for a script
    that raised - exit code 0, and the exception inside the envelope.
    """
    (tmp_path / "shape.py").write_text(SCRIPTS[shape_type])
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                {"part": "parts", "sketch": "sketches"}[kind]: {
                    "shape": {
                        "type": shape_type,
                        "path": "shape.py",
                        "pythonRequirements": ["shapely"],
                    }
                },
            }
        )
    )

    seen = {}

    async def no_install(*args, **kwargs):
        return None

    async def run_async(cmd, stdin="", cwd=None, session=None, **kwargs):
        seen["session"] = session
        envelope = {"success": False, "exception": MISSING, "shape": None, "components": []}
        return 0, shape_envelope.serialize(envelope), ""

    async def prepare_python(self):
        seen["factory"] = self
        monkeypatch.setattr(self.runtime, "ensure_async", no_install)
        monkeypatch.setattr(self.runtime, "run_async", run_async)

    monkeypatch.setattr(PartFactoryPython, "prepare_python", prepare_python)
    monkeypatch.setattr(SketchFactoryPython, "prepare_python", prepare_python)

    ctx = pc.Context(str(tmp_path))
    shape = ctx.get_part("//:shape") if kind == "part" else ctx.get_sketch("//:shape")
    result = asyncio.run(shape.instantiate(shape))
    return shape, result, seen


CASES = [
    ("part", "cadquery"),
    ("part", "build123d"),
    ("part", "sdf"),
    ("sketch", "cadquery"),
    ("sketch", "build123d"),
]


@pytest.mark.parametrize("kind, shape_type", CASES)
def test_the_script_runs_in_the_session_its_requirements_were_recorded_in(monkeypatch, tmp_path, kind, shape_type):
    """Without it the script runs where none of them was installed."""
    _, _, seen = _instantiate(monkeypatch, tmp_path, kind, shape_type)

    assert seen["session"] is not None
    # The one 'prepare_python()' records the requirements in.
    assert seen["session"] is seen["factory"].session


@pytest.mark.parametrize("kind, shape_type", CASES)
def test_the_script_s_exception_is_recorded_on_the_shape(monkeypatch, tmp_path, kind, shape_type):
    """Not only logged: 'errors' is what the callers report a failure from."""
    shape, result, _ = _instantiate(monkeypatch, tmp_path, kind, shape_type)

    assert result is None
    assert any(MISSING in error for error in shape.errors), shape.errors
