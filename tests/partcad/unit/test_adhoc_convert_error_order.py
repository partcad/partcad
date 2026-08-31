#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""
Which failure an ad-hoc command reports when a factory fails.

A factory that fails records the reason in `errors` and returns no shape, so
both conditions are true at once and only the order of the checks decides what
the user is told. These tests pin that order: the recorded reason wins, and
"no shape returned" is reserved for the case where nothing was recorded.

They stub the context rather than converting a real file, so they need no CAD
runtime and no sandbox -- the ordering is the whole subject.

Both verbs are covered. `pc adhoc convert` and `pc adhoc render` build the same
throwaway package (`partcad.adhoc.adhoc`), so a shape that will not load fails
identically for either, and what differs is only the verb in the message.
"""

import pytest

from partcad.adhoc import adhoc as adhoc_base
from partcad.adhoc import convert as adhoc_convert
from partcad.adhoc import render as adhoc_render


class _FakeShape:
    """Stands in for whatever the factory would have produced."""


class _FakeObject:
    def __init__(self, errors, shape):
        self.errors = errors
        self._shape = shape
        self.rendered = False

    async def get_wrapped(self, ctx):
        return self._shape

    def render(self, **kwargs):
        self.rendered = True


class _FakeProject:
    def __init__(self, obj):
        self._obj = obj

    def get_part(self, name):
        return self._obj

    def get_sketch(self, name):
        return self._obj


class _FakeContext:
    def __init__(self, obj):
        self._obj = obj

    def get_project(self, name):
        return _FakeProject(self._obj)


@pytest.fixture
def stub_context(monkeypatch):
    """Point the throwaway package's `Context` at a fake built from the object."""

    def install(obj):
        monkeypatch.setattr(adhoc_base, "Context", lambda *a, **kw: _FakeContext(obj))
        return obj

    return install


# Every ad-hoc entry point, with an output type that makes sense for it: a
# conversion writes another part or sketch, a render writes a projection.
ENTRY_POINTS = [
    pytest.param(adhoc_convert.convert_cad_file, "stl", id="convert-part"),
    pytest.param(adhoc_convert.convert_sketch_file, "dxf", id="convert-sketch"),
    pytest.param(adhoc_render.render_cad_file, "png", id="render-part"),
    pytest.param(adhoc_render.render_sketch_file, "png", id="render-sketch"),
]


@pytest.mark.parametrize("entry_point, output_type", ENTRY_POINTS)
def test_a_recorded_error_is_reported_instead_of_the_missing_shape(stub_context, tmp_path, entry_point, output_type):
    """A failed factory records why; that reason is what reaches the user."""
    obj = stub_context(_FakeObject(errors=["sandbox install failed: no cadquery wheel"], shape=None))

    with pytest.raises(RuntimeError) as excinfo:
        entry_point(str(tmp_path / "in.step"), "step", str(tmp_path / "out"), output_type)

    message = str(excinfo.value)
    assert "sandbox install failed: no cadquery wheel" in message
    assert "no shape returned" not in message
    assert not obj.rendered


@pytest.mark.parametrize("entry_point, output_type", ENTRY_POINTS)
def test_no_shape_and_no_recorded_error_still_says_no_shape(stub_context, tmp_path, entry_point, output_type):
    """With nothing recorded, the fallback message is all there is to say."""
    obj = stub_context(_FakeObject(errors=[], shape=None))

    with pytest.raises(RuntimeError) as excinfo:
        entry_point(str(tmp_path / "in.step"), "step", str(tmp_path / "out"), output_type)

    assert "no shape returned" in str(excinfo.value)
    assert not obj.rendered


@pytest.mark.parametrize("entry_point, output_type", ENTRY_POINTS)
def test_a_shape_with_no_errors_is_rendered(stub_context, tmp_path, entry_point, output_type):
    """The success path is unchanged: no errors and a shape means write the file."""
    obj = stub_context(_FakeObject(errors=[], shape=_FakeShape()))

    entry_point(str(tmp_path / "in.step"), "step", str(tmp_path / "out"), output_type)

    assert obj.rendered


@pytest.mark.parametrize(
    "entry_point, expected",
    [
        (adhoc_convert.convert_cad_file, "Failed to convert:"),
        (adhoc_convert.convert_sketch_file, "Failed to convert sketch:"),
        (adhoc_render.render_cad_file, "Failed to render:"),
        (adhoc_render.render_sketch_file, "Failed to render sketch:"),
    ],
)
def test_the_message_names_what_was_being_done(stub_context, tmp_path, entry_point, expected):
    """The CLI prints this line, so it has to say which command failed."""
    stub_context(_FakeObject(errors=["nope"], shape=None))

    with pytest.raises(RuntimeError, match=expected):
        entry_point(str(tmp_path / "in.step"), "step", str(tmp_path / "out"), "stl")
