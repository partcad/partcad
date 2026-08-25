#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Showing a shape sends compressed glTF to the IDE and never touches OCP in-process."""

import asyncio
import base64
import os
import sys
import threading
import zlib

import pytest

import partcad as pc
from partcad import shape_envelope, viewer

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


class FakeClient:
    """Stands in for the lazily imported 'partcad_ide_client'."""

    class ViewerNotAvailable(Exception):
        pass

    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def show(self, objects, **kwargs):
        if self.raises is not None:
            raise self.raises
        self.calls.append((objects, kwargs))
        return {"type": "ack", "ok": True}


@pytest.fixture(autouse=True)
def reset_camera_memory():
    viewer._previously_displayed = None
    yield
    viewer._previously_displayed = None


@pytest.fixture
def tessellated(monkeypatch):
    """Skip the sandbox: tessellation itself is exercised by the render tests."""
    objects = [{"name": "//pkg:part", "label": "part", "gltf": ocp_serialize.encode_gltf(b"glTF-bytes")}]

    async def fake_tessellate(ctx, components, name=None, **kwargs):
        return list(objects)

    monkeypatch.setattr(viewer, "tessellate", fake_tessellate)
    return objects


def test_show_sends_the_tessellated_objects(monkeypatch, tessellated):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    assert asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part", kind="part")) is True

    objects, kwargs = client.calls[0]
    assert objects == tessellated
    assert kwargs["name"] == "//pkg:part"
    assert kwargs["kind"] == "part"
    assert kwargs["markers"] == []
    # First show of this shape: the camera is expected to reset.
    assert kwargs["keep_camera"] is False


def test_reshowing_the_same_shape_keeps_the_camera(monkeypatch, tessellated):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part"))
    asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part"))
    asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:other"))

    assert [kwargs["keep_camera"] for _, kwargs in client.calls] == [False, True, False]


def test_markers_are_sent_without_tessellating(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    async def fail(*args, **kwargs):
        raise AssertionError("tessellate() must not run when there is no geometry")

    monkeypatch.setattr(viewer, "tessellate", fail)

    markers = [{"name": "port", "location": [[0, 0, 0], [0, 0, 1], 0]}]
    assert asyncio.run(viewer.show(object(), [], name="//pkg:iface", markers=markers)) is True

    objects, kwargs = client.calls[0]
    assert objects == []
    assert kwargs["markers"] == markers


def test_a_missing_client_warns_rather_than_raises(monkeypatch, tessellated):
    monkeypatch.setattr(viewer, "_client", lambda: None)
    assert asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part")) is False


def test_a_closed_viewer_warns_rather_than_raises(monkeypatch, tessellated):
    client = FakeClient()
    client.raises = client.ViewerNotAvailable("nothing is listening")
    monkeypatch.setattr(viewer, "_client", lambda: client)

    assert asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part")) is False


def test_a_failing_tessellation_warns_rather_than_raises(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    async def boom(*args, **kwargs):
        raise Exception("the sandbox died")

    monkeypatch.setattr(viewer, "tessellate", boom)

    assert asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part")) is False
    assert client.calls == []


def test_encode_gltf_matches_the_client_side_codec():
    """The two implementations of the glTF payload codec have to stay in step.

    'ocp_serialize' runs in the sandbox and cannot import 'partcad_ide_client';
    the client cannot import the sandbox's module either, so each carries its
    own two-line copy. This is the test that notices when one of them drifts.

    Imported outright rather than through 'importorskip': the client ships in
    this distribution, so it being absent is a packaging regression to fail on
    rather than a reason to skip.
    """
    import partcad_ide_client

    glb = b"glTF\x02\x00\x00\x00" + os.urandom(64) + b"\x00" * 4096

    encoded = ocp_serialize.encode_gltf(glb)
    assert zlib.decompress(base64.b64decode(encoded)) == glb

    assert partcad_ide_client.decode_gltf(encoded) == glb
    assert partcad_ide_client.encode_gltf(glb) == encoded


def _interface_with_port(location):
    """An Interface holding one port with one sketch, without touching the config machinery."""
    from partcad.interface import Interface, InterfacePort

    envelope = {"name": "sketch", "label": "sketch", shape_envelope.KEY_BREP: "unused"}

    class FakeSketch:
        async def get_components(self, ctx):
            return [envelope]

    port = InterfacePort.__new__(InterfacePort)
    port.name = "port"
    port.location = location
    port.sketch = FakeSketch()

    interface = Interface.__new__(Interface)
    interface.name = "//pkg:iface"
    interface.lock = threading.RLock()
    interface.ports = {"port": port}
    return interface, port, envelope


def test_interface_ports_place_sketches_without_ocp():
    """An interface moves its sketches onto its ports as data, not as geometry."""
    from partcad.geom import Location

    interface, port, envelope = _interface_with_port(Location([[1, 2, 3], [0, 0, 1], 90]))

    components = asyncio.run(interface.get_components(None))

    ((moved,),) = components
    # The envelope is untouched geometry carrying a placement, so nothing here
    # needed a CAD kernel.
    assert moved[shape_envelope.KEY_BREP] == "unused"
    assert moved[shape_envelope.KEY_LOCATION] == port.location.as_packed()
    assert shape_envelope.KEY_LOCATION not in envelope

    assert interface.get_markers() == [{"name": "port", "location": port.location.as_packed()}]


def test_a_port_without_a_location_sits_at_the_origin():
    """'InterfacePort.location' is None unless the port declares one.

    Most ports do not - every port inherited without a placement leaves it None -
    so both the placement and the marker paths have to read that as the identity
    rather than dereference it.
    """
    from partcad.geom import Location

    interface, _port, _envelope = _interface_with_port(None)

    ((moved,),) = asyncio.run(interface.get_components(None))
    assert moved[shape_envelope.KEY_LOCATION] == Location().as_packed()

    assert interface.get_markers() == [{"name": "port", "location": Location().as_packed()}]


def test_interface_show_sends_its_sketches_and_its_ports(monkeypatch):
    """Interface.show_async hands both halves to the viewer.

    The geometry is the port sketches; the ports themselves are frames with no
    geometry, so they travel beside it as markers for the viewer to draw axes at.
    """
    from partcad.geom import Location

    interface, port, _envelope = _interface_with_port(Location([[1, 2, 3], [0, 0, 1], 90]))

    shown = {}

    async def fake_show(ctx, components, name=None, kind=None, markers=None):
        shown.update(ctx=ctx, components=components, name=name, kind=kind, markers=markers)
        return True

    monkeypatch.setattr(viewer, "show", fake_show)

    asyncio.run(interface.show_async(None))

    assert shown["kind"] == "interface"
    assert shown["name"] == "//pkg:iface"
    assert shown["markers"] == [{"name": "port", "location": port.location.as_packed()}]
    ((moved,),) = shown["components"]
    assert moved[shape_envelope.KEY_LOCATION] == port.location.as_packed()


def test_interface_with_no_ports_shows_nothing(monkeypatch):
    from partcad.interface import Interface

    interface = Interface.__new__(Interface)
    interface.name = "//pkg:empty"
    interface.lock = threading.RLock()
    interface.ports = {}

    called = []

    async def fake_show(*args, **kwargs):
        called.append(True)
        return True

    monkeypatch.setattr(viewer, "show", fake_show)

    asyncio.run(interface.show_async(None))
    assert called == []


def test_a_shape_sends_the_ports_of_its_interface_as_markers(monkeypatch):
    """A part that implements an interface shows its ports too.

    'Shape.get_components()' appends the ports' *sketches*; the port frames have
    no geometry and would otherwise be lost, which is what showing a bare
    location used to provide.
    """
    from partcad.geom import Location
    from partcad.interface import InterfacePort
    from partcad.shape import Shape

    port = InterfacePort.__new__(InterfacePort)
    port.name = "port"
    port.location = Location([[4, 5, 6], [0, 1, 0], 45])
    port.sketch = None

    class FakeWithPorts:
        def get_markers(self):
            return [{"name": "port", "location": port.location.as_packed()}]

    shape = Shape.__new__(Shape)
    shape.name = "//pkg:part"
    shape.kind = "part"
    shape.project_name = "//pkg"
    shape.with_ports = FakeWithPorts()
    shape.components = [{"brep": "..."}]

    async def fake_get_components(ctx):
        return shape.components

    shape.get_components = fake_get_components

    shown = {}

    async def fake_show(ctx, components, name=None, kind=None, markers=None):
        shown.update(components=components, name=name, kind=kind, markers=markers)
        return True

    monkeypatch.setattr(viewer, "show", fake_show)

    asyncio.run(shape.show_async(object()))

    assert shown["kind"] == "part"
    assert shown["markers"] == [{"name": "port", "location": port.location.as_packed()}]


def test_interface_components_walk_lists_and_pass_non_geometry_through():
    """A port's sketch can hand back nested lists and non-geometry entries.

    Only shape envelopes get a placement; a nested list is walked, and anything
    that is not geometry (a null a factory produced) is passed through as it is.
    """
    from partcad.geom import Location
    from partcad.interface import Interface, InterfacePort

    envelope = {"name": "sketch", shape_envelope.KEY_BREP: "unused"}

    class FakeSketch:
        async def get_components(self, ctx):
            return [[envelope], None, "not-geometry"]

    port = InterfacePort.__new__(InterfacePort)
    port.name = "port"
    port.location = Location([[1, 0, 0], [0, 0, 1], 0])
    port.sketch = FakeSketch()

    interface = Interface.__new__(Interface)
    interface.name = "//pkg:iface"
    interface.lock = threading.RLock()
    interface.ports = {"port": port}

    ((nested, null, text),) = asyncio.run(interface.get_components(None))

    assert nested[0][shape_envelope.KEY_LOCATION] == port.location.as_packed()
    assert null is None
    assert text == "not-geometry"


def test_interface_show_survives_components_it_cannot_build(monkeypatch):
    """A sketch that will not build must not stop the ports being shown."""
    from partcad.interface import Interface, InterfacePort

    class ExplodingSketch:
        async def get_components(self, ctx):
            raise Exception("the sketch will not build")

    port = InterfacePort.__new__(InterfacePort)
    port.name = "port"
    port.location = None
    port.sketch = ExplodingSketch()

    interface = Interface.__new__(Interface)
    interface.name = "//pkg:iface"
    interface.lock = threading.RLock()
    interface.ports = {"port": port}

    shown = {}

    async def fake_show(ctx, components, name=None, kind=None, markers=None):
        shown.update(components=components, markers=markers)
        return True

    monkeypatch.setattr(viewer, "show", fake_show)

    asyncio.run(interface.show_async(None))

    assert shown["components"] == []
    assert len(shown["markers"]) == 1


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


def test_metadata_travels_beside_the_components():
    """Names and labels are carried separately.

    The sandbox's codec rebuilds live geometry from the envelopes and drops
    their metadata, so the core sends it alongside, positionally.
    """
    envelope = {"name": "//pkg:part", "label": "part", shape_envelope.KEY_BREP: "..."}

    assert viewer._metadata_of(envelope, "name") == "//pkg:part"
    assert viewer._metadata_of(envelope, "label") == "part"
    # A component can be a list of envelopes (a shape's ports); the first one
    # names the group.
    assert viewer._metadata_of([envelope], "name") == "//pkg:part"
    assert viewer._metadata_of([], "name") is None
    assert viewer._metadata_of(None, "name") is None


def test_interface_show_is_callable_synchronously(monkeypatch):
    """'show()' wraps 'show_async()' for callers outside an event loop."""
    from partcad.interface import Interface

    interface = Interface.__new__(Interface)
    interface.name = "//pkg:empty"
    interface.lock = threading.RLock()
    interface.ports = {}

    called = []

    async def fake_show(*args, **kwargs):
        called.append(True)
        return True

    monkeypatch.setattr(viewer, "show", fake_show)

    interface.show()
    assert called == []


def test_showing_a_shape_with_nothing_in_it_warns_and_stops(monkeypatch):
    """A shape that tessellates to nothing has nothing to send."""
    client = FakeClient()
    monkeypatch.setattr(viewer, "_client", lambda: client)

    async def nothing(ctx, components, name=None, **kwargs):
        return []

    monkeypatch.setattr(viewer, "tessellate", nothing)

    assert asyncio.run(viewer.show(object(), [{"brep": "..."}], name="//pkg:part")) is False
    assert client.calls == []
