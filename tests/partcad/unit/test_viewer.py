#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What showing a shape sends, and what it does when there is nothing to send to.

One object, as the tree of nodes every shape is (see 'test_shape_tree.py' for what
that tree holds), with the geometry at each node tessellated - and never a live OCP
object in this process. The delivery is the whole of what is tested here; the tree
itself is built by the code that builds it for every other purpose.
"""

import asyncio
import base64
import os
import sys
import zlib

import pytest
from viewer_fakes import fake_interface, fake_part, fake_port

import partcad as pc
from partcad import shape_envelope, viewer

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402

TESSELLATED = {"name": "//pkg:part", "label": "part", shape_envelope.KEY_GLTF: "compressed-glTF"}


class FakeClient:
    """Stands in for the lazily imported 'partcad_ide_client'."""

    class ViewerNotAvailable(Exception):
        pass

    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def show(self, obj, **kwargs):
        if self.raises is not None:
            raise self.raises
        self.calls.append((obj, kwargs))
        return {"type": "ack", "ok": True}


def _capture_show(monkeypatch):
    """Intercept 'viewer.show()' and hand back everything it was called with."""
    shown = {}

    async def fake_show(ctx, tree, **kwargs):
        shown.update(ctx=ctx, tree=tree, **kwargs)
        return True

    monkeypatch.setattr(viewer, "show", fake_show)
    return shown


def _tessellates(monkeypatch):
    """Skip the sandbox: the conversion itself is exercised by the render tests."""
    from partcad import shape_gltf

    async def fake_convert(ctx, subject, **kwargs):
        return TESSELLATED

    monkeypatch.setattr(shape_gltf, "convert_async", fake_convert)


@pytest.fixture(autouse=True)
def reset_camera_memory():
    viewer._previously_displayed = None
    yield
    viewer._previously_displayed = None


def test_show_sends_the_object_as_one_tree(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    assert asyncio.run(viewer.show(object(), TESSELLATED, name="part", kind="part", package="//pkg")) is True

    obj, kwargs = client.calls[0]
    # Passed through as it was built: this is the shape's own account of itself.
    assert obj is TESSELLATED
    assert kwargs["name"] == "part"
    assert kwargs["kind"] == "part"
    # What the viewer's tabs beside the 3D one are about: they ask the daemon
    # about '<package>:<name>', which a name on its own cannot spell.
    assert kwargs["package"] == "//pkg"
    # First show of this shape: the camera is expected to reset.
    assert kwargs["keep_camera"] is False


def test_reshowing_the_same_shape_keeps_the_camera(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    asyncio.run(viewer.show(object(), TESSELLATED, name="part"))
    asyncio.run(viewer.show(object(), TESSELLATED, name="part"))
    asyncio.run(viewer.show(object(), TESSELLATED, name="other"))

    assert [kwargs["keep_camera"] for _, kwargs in client.calls] == [False, True, False]


def test_nothing_to_show_warns_and_sends_nothing(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    assert asyncio.run(viewer.show(object(), None, name="part")) is False
    assert client.calls == []


def test_a_missing_client_warns_rather_than_raises(monkeypatch):
    monkeypatch.setattr(viewer, "_client", lambda: None)
    assert asyncio.run(viewer.show(object(), TESSELLATED, name="part")) is False


def test_a_closed_viewer_warns_rather_than_raises(monkeypatch):
    client = FakeClient()
    client.raises = client.ViewerNotAvailable("nothing is listening")
    monkeypatch.setattr(viewer, "_client", lambda: client)

    assert asyncio.run(viewer.show(object(), TESSELLATED, name="part")) is False


def test_a_shape_shows_itself_in_the_drawable_form(monkeypatch):
    """A browser has no CAD kernel, so what it is sent is the tessellated tree."""
    _tessellates(monkeypatch)
    shown = _capture_show(monkeypatch)

    shape = fake_part("bracket", ports={"grip": fake_port()})
    asyncio.run(shape.show_async(object()))

    assert shown["tree"] is TESSELLATED
    assert shown["name"] == "bracket"
    assert shown["kind"] == "part"
    assert shown["package"] == "//pkg"


def test_a_shape_that_will_not_build_warns_rather_than_raises(monkeypatch):
    """A show is a side effect of browsing a package, not the command itself."""
    shown = _capture_show(monkeypatch)

    shape = fake_part("bracket")

    async def boom(ctx):
        raise Exception("the sandbox died")

    shape.get_wrapped = boom

    asyncio.run(shape.show_async(object()))
    assert shown == {}


def test_an_interface_shows_itself_the_same_way(monkeypatch):
    """No per-kind path: an interface is a tree of nodes like anything else."""
    _tessellates(monkeypatch)
    shown = _capture_show(monkeypatch)

    interface = fake_interface("m3-thru", ports={"thru": fake_port()})
    asyncio.run(interface.show_async(object()))

    assert shown["tree"] is TESSELLATED
    assert shown["name"] == "m3-thru"
    assert shown["kind"] == "interface"
    assert shown["package"] == "//pkg"


def test_an_interface_that_will_not_build_warns_rather_than_raises(monkeypatch):
    shown = _capture_show(monkeypatch)

    interface = fake_interface("m3-thru", ports={"thru": fake_port()})

    async def boom(ctx, seen=None):
        raise Exception("the sketch will not build")

    interface._tree_async = boom

    asyncio.run(interface.show_async(object()))
    assert shown == {}


def test_show_is_callable_synchronously(monkeypatch):
    """'show()' wraps 'show_async()' for callers outside an event loop."""
    _tessellates(monkeypatch)
    shown = _capture_show(monkeypatch)

    fake_interface("m3", ports={"m3": fake_port()}).show(object())
    assert shown["kind"] == "interface"


def test_encode_gltf_matches_the_client_side_codec():
    """The glTF payload codec has three implementations and they have to agree.

    None of the three can import either of the others - the sandbox has no
    'partcad_ide_client', the client has no 'partcad', the extension is not Python
    - so each carries its own two-line copy. This is the test that notices when one
    of them drifts.

    Imported outright rather than through 'importorskip': the client ships in this
    distribution, so it being absent is a packaging regression to fail on rather
    than a reason to skip.
    """
    import partcad_ide_client

    glb = b"glTF\x02\x00\x00\x00" + os.urandom(64) + b"\x00" * 4096

    encoded = ocp_serialize.encode_gltf(glb)
    assert zlib.decompress(base64.b64decode(encoded)) == glb

    assert partcad_ide_client.decode_gltf(encoded) == glb
    assert partcad_ide_client.encode_gltf(glb) == encoded


def test_a_missing_client_package_is_not_an_import_error(monkeypatch):
    """A client that will not import degrades a preview, it does not fail a command.

    'partcad_ide_client' ships inside this distribution, so this is a damaged
    install rather than a missing optional package -- but 'show()' is a side
    effect of browsing, and neither that nor a shape that will not tessellate
    should take down the command that asked for it.
    """

    def no_client(name):
        raise ImportError("no module named %r" % name)

    monkeypatch.setattr(viewer.importlib, "import_module", no_client)

    assert viewer._client() is None


def test_a_caller_that_passes_no_context_gets_the_process_wide_one(monkeypatch):
    """Which is what a script, a notebook or the REPL has: 'part.show()'."""
    from partcad import globals as pc_globals

    standin = object()
    monkeypatch.setattr(pc_globals, "_partcad_context", standin)
    assert viewer.context(None, "cube") is standin
    # One that does pass a context keeps it, whatever the global holds.
    mine = object()
    assert viewer.context(mine, "cube") is mine


def test_showing_with_no_context_anywhere_says_so_and_stops(monkeypatch):
    """Rather than leaving it to whatever first needs one to raise.

    Which is how showing a sketch from the IDE's Explorer came to answer "A context
    is required to tessellate a shape tree": the daemon held a context and did not
    pass it, and the global it fell back to was not set in that session.
    """
    from partcad import globals as pc_globals

    monkeypatch.setattr(pc_globals, "_partcad_context", None)
    assert viewer.context(None, "cube") is None

    # And the show gives up there: nothing is built and nothing is sent.
    shown = _capture_show(monkeypatch)
    shape = fake_part("cube")

    async def never(ctx):
        raise AssertionError("nothing may be built without a context")

    shape.get_wrapped = never
    asyncio.run(shape.show_async())
    assert shown == {}


def test_a_port_without_a_location_sits_at_the_origin():
    """'InterfacePort.location' is None unless the port declares one.

    Most ports do not - every port inherited without a placement leaves it None -
    so every reader of a port's placement has to read that as the identity rather
    than dereference it.
    """
    from partcad.geom import Location
    from partcad.interface import port_location

    assert port_location(fake_port(None)).as_packed() == Location().as_packed()
