#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A BREP payload is OCCT's binary format, without the mesh of a face that has a surface.

What 'ocp_serialize.shape_to_brep' writes and 'shape_from_brep' reads, and the
two things the core learns about a payload without a kernel now that it cannot
scan one: the free shells it records at encode time, and the format it sniffs.
"""

import base64
import glob
import os
import sys
from io import BytesIO

import pytest

import partcad as pc

# 'partcad' before OCP, and 'isort: split' so it stays there: importing the
# package pins the standard library's expat (see the comment on 'import
# pyexpat' in partcad/__init__.py), and whatever loads first wins for the
# process.
# isort: split

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.Poly import Poly_Array1OfTriangle, Poly_Triangle, Poly_Triangulation
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_VERTEX
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Face, TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape

from partcad import brep_inspect, cache_shape, shape_envelope

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import shape_measure  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "data", "brep")


def _box(corner=(0.0, 0.0, 0.0), size=(10.0, 20.0, 30.0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*corner), *size).Shape()


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _ascii(shape) -> bytes:
    with BytesIO() as bio:
        BRepTools.Write_s(shape, bio)
        return bio.getvalue()


def _read_ascii(data: bytes):
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, BytesIO(data), BRep_Builder())
    return shape


def _vertices(shape):
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, found)
    points = []
    for index in range(1, found.Extent() + 1):
        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(found.FindKey(index)))
        points.append((point.X(), point.Y(), point.Z()))
    return points


def _faces(shape):
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        yield TopoDS.Face_s(explorer.Current())
        explorer.Next()


def _triangles(shape) -> int:
    total = 0
    for face in _faces(shape):
        triangulation = BRep_Tool.Triangulation_s(face, TopLoc_Location())
        total += 0 if triangulation is None else triangulation.NbTriangles()
    return total


def _mesh_face(points):
    """A face that is nothing but triangles, as 'wrapper_sdf' and an STL read as a mesh build one."""
    nodes = TColgp_Array1OfPnt(1, len(points))
    for index, point in enumerate(points):
        nodes.SetValue(index + 1, gp_Pnt(*point))
    triangles = Poly_Array1OfTriangle(1, len(points) // 3)
    for index in range(len(points) // 3):
        triangles.SetValue(index + 1, Poly_Triangle(3 * index + 1, 3 * index + 2, 3 * index + 3))
    face = TopoDS_Face()
    BRep_Builder().MakeFace(face, Poly_Triangulation(nodes, triangles))
    return face


def _compound(*shapes):
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def _meshed(shape, deflection=0.05):
    BRepMesh_IncrementalMesh(shape, deflection)
    return shape


def test_a_payload_is_binary_in_the_pinned_version():
    payload = ocp_serialize.shape_to_brep(_box())

    assert payload.startswith(b"\nOpen CASCADE Topology V%d" % ocp_serialize.BINARY_FORMAT_VERSION)
    assert ocp_serialize.is_binary_brep(payload)
    assert not ocp_serialize.is_binary_brep(_ascii(_box()))


def test_the_round_trip_is_exact_where_ascii_is_not():
    """ASCII prints fifteen digits, so a coordinate that needs seventeen moves; binary keeps all of them."""
    shape = _box(corner=(1.0 / 3.0, 2.0 / 7.0, 10000.0 / 3.0), size=(10.0 / 3.0, 20.0 / 7.0, 1.0 / 9.0))
    exact = _vertices(shape)

    assert _vertices(ocp_serialize.shape_from_brep(ocp_serialize.shape_to_brep(shape))) == exact
    assert _vertices(_read_ascii(_ascii(shape))) != exact


def test_it_is_smaller_than_ascii_after_compression():
    """What the pipe and the cache carry is the compressed payload, so that is the size that counts."""
    shape = BRepPrimAPI_MakeSphere(gp_Pnt(1.0 / 3.0, 0.5, 2.0 / 7.0), 12.3456789).Shape()
    shape = _compound(shape, BRepBuilderAPI_Transform(shape, gp_Trsf(), True).Shape())

    binary = ocp_serialize.compressed_brep(shape)
    ascii_payload = ocp_serialize._compress(_ascii(shape))

    assert len(binary) < len(ascii_payload)


def test_an_ascii_payload_is_still_read():
    """An earlier release's cache entry, Chili3D's answer, a package's '.brep' file."""
    box = _box()
    plain = _ascii(box)

    assert ocp_serialize.shape_from_brep(plain).ShapeType() == box.ShapeType()
    for payload in (ocp_serialize._compress(plain), plain):
        envelope = {"name": "box", "label": "box", "brep": base64.b64encode(payload).decode("ascii")}
        assert _volume(ocp_serialize.decode_shape(envelope)) == pytest.approx(_volume(box))


def test_a_draw_saved_ascii_payload_is_not_taken_for_binary():
    """DBRep prefixes its own line, and the ASCII marker is inside the binary one: neither fools the sniff."""
    assert not ocp_serialize.is_binary_brep(b"DBRep_DrawableShape\n\nCASCADE Topology V1, (c) Matra-Datavision\n")
    assert not ocp_serialize.is_binary_brep(b"\nCASCADE Topology V3, (c) Open Cascade\n")
    assert ocp_serialize.is_binary_brep(b"\nOpen CASCADE Topology V4, (c) Open Cascade\n\x00\x01")


def test_the_mesh_of_a_face_with_a_surface_is_not_carried():
    """It is what somebody meshed the faces to; every reader that needs one meshes for itself."""
    box = _meshed(_box())
    assert _triangles(box) > 0

    payload = ocp_serialize.shape_to_brep(box)
    decoded = ocp_serialize.shape_from_brep(payload)

    assert _triangles(decoded) == 0
    assert _vertices(decoded) == _vertices(box)
    assert len(payload) < len(ocp_serialize._write_binary(box, True))


def test_a_face_that_is_only_triangles_keeps_them():
    """An SDF part, an STL read as a mesh, an imported glTF: there the triangles are the geometry."""
    points = [(0.0, 0.0, 0.0), (1.0 / 3.0, 0.0, 0.0), (0.0, 2.0 / 7.0, 0.0)]
    points += [(0.0, 0.0, 0.0), (0.0, 2.0 / 7.0, 0.0), (0.0, 0.0, 5.0 / 9.0)]
    face = _mesh_face(points)

    decoded = ocp_serialize.shape_from_brep(ocp_serialize.shape_to_brep(face))
    triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(decoded), TopLoc_Location())

    assert triangulation is not None
    assert triangulation.NbTriangles() == 2
    nodes = [triangulation.Node(index + 1) for index in range(triangulation.NbNodes())]
    assert [(node.X(), node.Y(), node.Z()) for node in nodes] == points


def test_a_shape_holding_a_mesh_is_written_with_all_of_it():
    """So that the edges of a face that is only triangles keep the polygons that are their only geometry."""
    mesh = _mesh_face([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    box = _meshed(_box())
    both = _compound(box, mesh)

    decoded = ocp_serialize.shape_from_brep(ocp_serialize.shape_to_brep(both))

    assert _triangles(decoded) == _triangles(both)


@pytest.mark.parametrize(
    "header, holds",
    [
        (b"Triangulations 0\n", False),
        (b"Triangulations 3\n", True),
        # Unreadable is answered with a payload that keeps its mesh: the safe side.
        (b"Triangulations x\n", True),
        (b"no such section", True),
    ],
)
def test_whether_a_payload_holds_a_mesh_is_read_off_its_header(header, holds):
    assert ocp_serialize._holds_mesh(b"\nOpen CASCADE Topology V4, (c) Open Cascade\n\x00" + header) is holds


def test_an_occt_with_no_binary_writer_writes_ascii(monkeypatch):
    """Older than 7.6: what it writes is still a payload, because every reader reads ASCII too."""
    ocp_serialize._ensure_ocp()
    monkeypatch.setattr(ocp_serialize, "_binary_version", None)
    box = _box()

    payload = ocp_serialize.shape_to_brep(box)

    assert not ocp_serialize.is_binary_brep(payload)
    assert _volume(ocp_serialize.shape_from_brep(payload)) == pytest.approx(_volume(box))


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(FIXTURES, "*.brep"))), ids=os.path.basename)
def test_the_recorded_count_agrees_with_the_payload_scan(path):
    """The count a binary payload's envelope records, and the count an ASCII payload is read for, are one rule."""
    with open(path, "rb") as stream:
        plain = stream.read()
    shape = _read_ascii(plain)

    assert shape_measure.free_shells(shape) == brep_inspect.free_shells(plain)


def test_a_shell_placed_twice_is_one_shell():
    """A payload records a sub-shape once however often it is placed, and so does the count."""
    box = _box()
    shell = TopExp_Explorer(box, TopAbs_SHELL).Current()
    moved = gp_Trsf()
    moved.SetTranslation(gp_Vec(100.0, 0.0, 0.0))
    twice = _compound(shell, shell.Moved(TopLoc_Location(moved)))

    assert shape_measure.free_shells(twice) == 1
    assert brep_inspect.free_shells(_ascii(twice)) == 1

    # And a solid beside its own boundary: the one shell is a solid's, wherever else it stands.
    beside = _compound(box, shell)
    assert shape_measure.free_shells(beside) == brep_inspect.free_shells(_ascii(beside)) == 0


def test_the_core_reads_the_count_a_binary_envelope_recorded():
    """It cannot scan a binary payload, and does not need to: the encoder counted while the shape was live."""
    shell = TopExp_Explorer(_box(), TopAbs_SHELL).Current()
    solid = ocp_serialize.encode_shape(_box())
    skin = ocp_serialize.encode_shape(shell)

    for encoded in (solid, skin):
        assert brep_inspect.topology(encoded["brep"]) is None
        measured = encoded["metadata"]["measurements"]
        assert measured[shape_envelope.METADATA_FREE_SHELLS] == (1 if encoded is skin else 0)

    assert brep_inspect.envelope_free_shells(solid) == (0, 0)
    assert brep_inspect.envelope_free_shells(skin) == (1, 0)
    assert brep_inspect.envelope_free_shells({"name": "a", "assembly": [solid, skin]}) == (1, 0)

    # A binary payload whose envelope recorded nothing is not read, and says so.
    bare = {key: value for key, value in skin.items() if key != "metadata"}
    assert brep_inspect.envelope_free_shells(bare) == (0, 1)


def test_a_binary_brep_file_is_read_like_an_ascii_one(tmp_path):
    """What an interference check leaves behind is a payload in a file, read back by the 'brep' part type."""
    box = _box()
    binary = tmp_path / "binary.brep"
    binary.write_bytes(ocp_serialize.shape_to_brep(box))
    ascii_file = tmp_path / "ascii.brep"
    ascii_file.write_bytes(_ascii(box))

    for path in (binary, ascii_file):
        assert _volume(ocp_serialize.shape_from_brep_file(str(path))) == pytest.approx(_volume(box))

    broken = tmp_path / "broken.brep"
    broken.write_bytes(b"\nOpen CASCADE Topology V4, (c) Open Cascade\nLocations 0\n")
    with pytest.raises(Exception):
        ocp_serialize.shape_from_brep_file(str(broken))


def test_the_cache_takes_an_uncompressed_payload_of_either_format():
    """Written by a peer without zstd: the cache tells a payload from its frames and its JSON by the first bytes."""
    for plain in (ocp_serialize.shape_to_brep(_box()), _ascii(_box())):
        assert cache_shape._deserialize(plain) == {shape_envelope.KEY_BREP: plain}
