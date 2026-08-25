#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for rendering 2D projections to DXF.

What is specific to DXF is that a written file is not a function of the drawing
alone. ezdxf stamps every save with the time it happened and a fresh pair of
GUIDs, and it derives the order of the CLASSES section from a 'set' of type
names, whose iteration order follows a per-process hash seed. Both make two
saves of one drawing differ, which would cost PartCAD a checked-in DXF: the
examples are a regression canary only because rendering them twice produces the
same bytes.

These cover the 'reproducible' parameter that settles both, without the sandbox
the implementation normally runs in. That the result really is byte-identical
across processes is not something a unit test can show; 'examples/feature_render'
checks its DXF in, and the "Examples (PartCAD)" CI job re-renders it.
"""

import importlib.util
import os
import sys
import types

import pytest

import partcad as pc
from partcad import output

RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]


class _Options:
    write_fixed_meta_data_for_testing = None


class _Classes:
    def __init__(self):
        self.added = []

    def add_class(self, name):
        self.added.append(name)


class _EntityDB:
    def __init__(self, types_in_use):
        self._types = types_in_use

    def dxf_types_in_use(self):
        # A 'set', like ezdxf's own: the order this comes out in is exactly what
        # the implementation must not depend on.
        return set(self._types)


class _Document:
    def __init__(self, types_in_use):
        self.classes = _Classes()
        self.entitydb = _EntityDB(types_in_use)
        self.saved_as = None

    def modelspace(self):
        space = types.SimpleNamespace()
        space.add_line = lambda start, end: None
        return space

    def saveas(self, path):
        # Recorded after the classes, so a test can tell that registration
        # happened before the save rather than after it.
        self.saved_as = (path, list(self.classes.added))


def _dxf_implementation(types_in_use=("LINE", "LAYOUT", "ACDBPLACEHOLDER", "DICTIONARY")):
    """The DXF implementation, with ezdxf and svgpathtools replaced by recorders.

    Returns '(module, ezdxf_stub, documents)', where 'documents' collects every
    document 'ezdxf.new()' handed out.
    """
    documents = []

    ezdxf_stub = types.ModuleType("ezdxf")
    ezdxf_stub.options = _Options()

    def new(dxfversion=None):
        document = _Document(types_in_use)
        documents.append(document)
        return document

    ezdxf_stub.new = new

    math_stub = types.ModuleType("ezdxf.math")
    math_stub.Vec2 = lambda x, y: (x, y)
    ezdxf_stub.math = math_stub

    svgpathtools_stub = types.ModuleType("svgpathtools")
    svgpathtools_stub.svg2paths2 = lambda _path: ([], [], {})

    stubs = {
        "ezdxf": ezdxf_stub,
        "ezdxf.math": math_stub,
        "svgpathtools": svgpathtools_stub,
        "wrapper_common": types.ModuleType("wrapper_common"),
        "render_svg": types.ModuleType("render_svg"),
    }

    saved = {key: sys.modules.get(key) for key in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("test_render_dxf_impl", os.path.join(RENDER_DIR, "render_dxf.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for key, value in saved.items():
            if value is None:
                del sys.modules[key]
            else:
                sys.modules[key] = value

    return module, ezdxf_stub, documents


def test_the_builtin_dxf_is_reproducible_by_default():
    """A package gets diffable DXF without asking for it."""
    ctx = pc.init("examples")
    declared = output.builtin_formats(ctx, output.RENDER)["dxf"]
    assert declared["reproducible"] is True


def test_the_timestamp_and_the_guids_are_suppressed(tmp_path):
    """ezdxf writes fixed metadata behind one option; it has to be set."""
    module, ezdxf_stub, _documents = _dxf_implementation()

    module.convert_svg_to_dxf("in.svg", str(tmp_path / "out.dxf"))

    assert ezdxf_stub.options.write_fixed_meta_data_for_testing is True


def test_the_real_timestamp_can_be_asked_for(tmp_path):
    """'reproducible: false' is what a drawing that records its own age sets."""
    module, ezdxf_stub, _documents = _dxf_implementation()

    module.convert_svg_to_dxf("in.svg", str(tmp_path / "out.dxf"), reproducible=False)

    assert ezdxf_stub.options.write_fixed_meta_data_for_testing is False


def test_the_classes_section_is_registered_in_a_settled_order(tmp_path):
    """The order ezdxf would pick comes out of a set, so it is pinned here.

    'register()' keeps the first entry for a name and ignores later ones, so
    registering every type in use before the save is what decides the order.
    """
    module, _ezdxf_stub, documents = _dxf_implementation()

    module.convert_svg_to_dxf("in.svg", str(tmp_path / "out.dxf"))

    document = documents[0]
    _path, registered_before_save = document.saved_as
    assert registered_before_save == sorted(registered_before_save)
    assert set(registered_before_save) == {"LINE", "LAYOUT", "ACDBPLACEHOLDER", "DICTIONARY"}


def test_nothing_is_pinned_when_reproducibility_is_off(tmp_path):
    """Off means out of the way: ezdxf decides the CLASSES order as it always did."""
    module, _ezdxf_stub, documents = _dxf_implementation()

    module.convert_svg_to_dxf("in.svg", str(tmp_path / "out.dxf"), reproducible=False)

    assert documents[0].saved_as[1] == []


@pytest.mark.parametrize(
    "requested, expected", [({}, True), ({"reproducible": True}, True), ({"reproducible": False}, False)]
)
def test_the_request_carries_the_parameter_through(tmp_path, requested, expected, monkeypatch):
    """'process()' is what the wrapper calls, and the parameter arrives in it."""
    module, ezdxf_stub, _documents = _dxf_implementation()

    def render_svg_process(path, _request):
        with open(path, "w") as f:
            f.write("<svg/>")
        return {"success": True}

    monkeypatch.setattr(module.render_svg, "process", render_svg_process, raising=False)

    response = module.process(str(tmp_path / "out.dxf"), dict(requested))

    assert response["success"] is True
    assert ezdxf_stub.options.write_fixed_meta_data_for_testing is expected
