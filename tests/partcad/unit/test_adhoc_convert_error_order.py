#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""
Which failure `pc adhoc convert` reports when a factory fails.

A factory that fails records the reason in `errors` and returns no shape, so
both conditions are true at once and only the order of the checks decides what
the user is told. These tests pin that order: the recorded reason wins, and
"no shape returned" is reserved for the case where nothing was recorded.

They stub the context rather than converting a real file, so they need no CAD
runtime and no sandbox -- the ordering is the whole subject.
"""

import pytest

from partcad.adhoc import convert as adhoc_convert


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
    """Point `convert.Context` at a fake built from the object under test."""

    def install(obj):
        monkeypatch.setattr(adhoc_convert, "Context", lambda *a, **kw: _FakeContext(obj))
        return obj

    return install


@pytest.mark.parametrize(
    "convert, kind",
    [
        (adhoc_convert.convert_cad_file, "part"),
        (adhoc_convert.convert_sketch_file, "sketch"),
    ],
)
def test_a_recorded_error_is_reported_instead_of_the_missing_shape(stub_context, tmp_path, convert, kind):
    """A failed factory records why; that reason is what reaches the user."""
    obj = stub_context(_FakeObject(errors=["sandbox install failed: no cadquery wheel"], shape=None))

    with pytest.raises(RuntimeError) as excinfo:
        convert(str(tmp_path / "in.step"), "step", str(tmp_path / "out.stl"), "stl")

    message = str(excinfo.value)
    assert "sandbox install failed: no cadquery wheel" in message
    assert "no shape returned" not in message
    assert not obj.rendered


@pytest.mark.parametrize(
    "convert, kind",
    [
        (adhoc_convert.convert_cad_file, "part"),
        (adhoc_convert.convert_sketch_file, "sketch"),
    ],
)
def test_no_shape_and_no_recorded_error_still_says_no_shape(stub_context, tmp_path, convert, kind):
    """With nothing recorded, the fallback message is all there is to say."""
    obj = stub_context(_FakeObject(errors=[], shape=None))

    with pytest.raises(RuntimeError) as excinfo:
        convert(str(tmp_path / "in.step"), "step", str(tmp_path / "out.stl"), "stl")

    assert "no shape returned" in str(excinfo.value)
    assert not obj.rendered


@pytest.mark.parametrize(
    "convert",
    [adhoc_convert.convert_cad_file, adhoc_convert.convert_sketch_file],
)
def test_a_shape_with_no_errors_is_rendered(stub_context, tmp_path, convert):
    """The success path is unchanged: no errors and a shape means render."""
    obj = stub_context(_FakeObject(errors=[], shape=_FakeShape()))

    convert(str(tmp_path / "in.step"), "step", str(tmp_path / "out.stl"), "stl")

    assert obj.rendered
