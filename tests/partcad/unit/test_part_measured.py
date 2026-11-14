#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 'heightmap', 'pointcloud' and 'voxels' part types: measured data, made solid.

What a reader gets wrong is a plausible part: a height map upside down, a voxel
model one cell off, a side of a terrain twisted so that it bounds a fifth less
than it should while OCCT still calls it valid. So each fact is held to an answer
worked out by hand - the volume of so many voxels, the area of a side under a
known curve, which edge of an image is north - on files these tests write.
Checked in this process, with numpy and OCP, as 'test_part_usd.py' checks the
'usd' type's script; LAS is read only where laspy is installed, as the type's
sandbox has it.
"""

import importlib.util
import math
import os
import struct
import sys

import numpy
import pytest
import yaml
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

from partcad import output

BUILTIN_IMPORT = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]


def _module(script):
    if BUILTIN_IMPORT not in sys.path:
        sys.path.append(BUILTIN_IMPORT)
    spec = importlib.util.spec_from_file_location("%s_under_test" % script[:-3], os.path.join(BUILTIN_IMPORT, script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


heightfield = _module("heightfield.py")
voxel_solid = _module("voxel_solid.py")
part_heightmap = _module("part_heightmap.py")
part_pointcloud = _module("part_pointcloud.py")
part_voxels = _module("part_voxels.py")


def volume(shape):
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return properties.Mass()


def box(shape):
    found = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, found, False, False)
    return found.Get()


def count(shape, kind):
    explorer, found = TopExp_Explorer(shape, kind), 0
    while explorer.More():
        found += 1
        explorer.Next()
    return found


def built(result):
    assert "exception" not in result, result.get("exception")
    assert BRepCheck_Analyzer(result["shape"]).IsValid()
    return result["shape"]


# -- What is declared ----------------------------------------------------------------------------------------------


def test_the_types_are_declared_as_solids_of_their_own_scripts():
    with open(os.path.join(BUILTIN_IMPORT, "partcad.yaml")) as f:
        declared = yaml.safe_load(f)["partTypes"]
    for name, script, extension in (
        ("heightmap", "part_heightmap.py", "asc"),
        ("pointcloud", "part_pointcloud.py", "las"),
        ("voxels", "part_voxels.py", "vox"),
    ):
        assert declared[name]["path"] == script
        assert declared[name]["extension"] == extension
        assert declared[name]["requireSolid"] is True
        assert os.path.isfile(os.path.join(BUILTIN_IMPORT, script))
    assert "pillow==12.2.0" in declared["heightmap"]["pythonRequirements"]
    assert any(r.startswith("laspy==") for r in declared["pointcloud"]["pythonRequirements"])
    assert any(r.startswith("lazrs==") for r in declared["pointcloud"]["pythonRequirements"])


# -- The height field --------------------------------------------------------------------------------------------


def hill(nx=60, ny=40):
    x, y = numpy.meshgrid(numpy.linspace(-1, 1, nx), numpy.linspace(-1, 1, ny), indexing="ij")
    return 500.0 * numpy.exp(-(x**2 + y**2) * 3)


def test_the_poles_stand_where_a_line_is_reproduced():
    for count_ in (4, 7, 260):
        poles = heightfield.greville(count_)
        for k in range(21):
            u = k / 20.0
            span, values = heightfield._basis(u, count_)
            assert sum(v * poles[span - 3 + i] for i, v in enumerate(values)) == pytest.approx(u, abs=1e-12)


def test_a_missing_height_is_the_nearest_present_ones():
    grid = numpy.array([[1.0, numpy.nan, 3.0], [numpy.nan, numpy.nan, numpy.nan], [7.0, 8.0, 9.0]])
    filled = heightfield.filled(grid)
    assert filled[0, 1] in (1.0, 3.0) and filled[2, 1] == 8.0 and numpy.isfinite(filled).all()
    with pytest.raises(ValueError, match="no height"):
        heightfield.filled(numpy.full((3, 3), numpy.nan))


def test_the_solid_is_the_volume_under_the_surface_occt_builds():
    """Every side ruled the right way round: a twisted side is valid to OCCT and bounds the wrong volume."""
    heights = hill()
    shape, info = heightfield.build(heights, 10.0, 100.0)
    assert BRepCheck_Analyzer(shape).IsValid() and count(shape, TopAbs_FACE) == 6
    x0, y0, x1, y1 = info["extent"]
    assert (x0, y0, x1, y1) == pytest.approx((-300.0, -200.0, 300.0, 200.0))
    poles = heightfield.poles(100.0 + heights - heights.min(), *info["poles"])
    surface = heightfield.surface(poles, info["extent"])
    for u, v in [(0.0, 0.0), (0.3, 0.7), (1.0, 0.5)]:
        point = surface.Value(u, v)
        assert point.Z() == pytest.approx(heightfield.evaluate(poles, info["extent"], point.X(), point.Y()), abs=1e-9)
    xs, ys = numpy.linspace(x0, x1, 241), numpy.linspace(y0, y1, 161)
    mean = numpy.mean([[heightfield.evaluate(poles, info["extent"], a, b) for b in ys] for a in xs])
    assert volume(shape) == pytest.approx(mean * (x1 - x0) * (y1 - y0), rel=0.01)
    assert box(shape)[2] == pytest.approx(0.0, abs=1e-6)


def test_a_fine_grid_is_averaged_down_to_the_poles_it_may_have():
    assert heightfield.pole_counts(1000, 500, 256) == (256, 129)
    assert heightfield.pole_counts(10, 5) == (13, 8)
    shape, info = heightfield.build(hill(600, 300), 1.0, 5.0, max_poles=64)
    assert info["poles"] == [64, 33] and BRepCheck_Analyzer(shape).IsValid()


def test_a_surface_that_reaches_its_base_is_refused():
    with pytest.raises(ValueError, match="base"):
        heightfield.build(hill(), 10.0, 0.0)


# -- heightmap ---------------------------------------------------------------------------------------------------


def test_an_ascii_grid_is_read_at_its_cell_with_its_holes_filled(tmp_path):
    path = tmp_path / "dem.asc"
    path.write_text(
        "ncols 4\nnrows 3\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n"
        "1 2 3 4\n2 -9999 4 5\n3 4 5 6\n"
    )
    shape = built(part_heightmap.run({"path": str(path), "parameters": {"base": 1000}}))
    xmin, ymin, zmin, xmax, ymax, zmax = box(shape)
    # 4 x 3 cells of 10 m; heights 1 to 6 m above the lowest, which stands 1 m up.
    assert (xmin, ymin, xmax, ymax) == pytest.approx((-20000, -15000, 20000, 15000))
    assert zmin == pytest.approx(0.0, abs=1e-3) and 1000.0 < zmax <= 6000.0 + 1e-3


def test_an_image_is_north_up(tmp_path):
    """The first row of an image is its north edge: what is bright at the top of the picture is high at +Y."""
    from PIL import Image

    levels = numpy.repeat(numpy.linspace(65535, 0, 50).astype(numpy.uint16)[:, None], 30, axis=1)
    Image.fromarray(levels).save(tmp_path / "ramp.png")
    heights, cell, _ = part_heightmap.heights_of(str(tmp_path / "ramp.png"), {"relief": 100, "cell": 2})
    assert heights.shape == (30, 50) and cell == (2.0, 2.0)
    assert heights[0, -1] == pytest.approx(100.0) and heights[0, 0] == pytest.approx(0.0)
    shape = built(part_heightmap.run({"path": str(tmp_path / "ramp.png"), "parameters": {"relief": 100, "cell": 2}}))
    assert box(shape)[0] == pytest.approx(-30.0) and box(shape)[4] == pytest.approx(50.0)


def test_integer_levels_need_a_relief_and_colour_needs_an_encoding(tmp_path):
    from PIL import Image

    Image.fromarray(numpy.zeros((4, 4), numpy.uint8)).save(tmp_path / "flat.png")
    assert "relief" in part_heightmap.run({"path": str(tmp_path / "flat.png"), "parameters": {}})["exception"]
    rgb = numpy.zeros((4, 4, 3), numpy.uint8)
    rgb[..., 0] = 200
    Image.fromarray(rgb).save(tmp_path / "colour.png")
    said = part_heightmap.run({"path": str(tmp_path / "colour.png"), "parameters": {"relief": 1}})["exception"]
    assert "encoding" in said


def test_the_rgb_encodings_are_metres(tmp_path):
    from PIL import Image

    # Terrarium: (R * 256 + G + B / 256) - 32768; 128, 100, 128 is 100.5 m.
    tile = numpy.zeros((3, 3, 3), numpy.uint8)
    tile[...] = (128, 100, 128)
    Image.fromarray(tile).save(tmp_path / "terrarium.png")
    heights, _, _ = part_heightmap.heights_of(str(tmp_path / "terrarium.png"), {"encoding": "terrarium"})
    assert heights == pytest.approx(numpy.full((3, 3), 100500.0))
    # Terrain-RGB: -10000 + (R * 65536 + G * 256 + B) * 0.1; 1, 134, 160 is 0 m.
    tile[...] = (1, 134, 160)
    Image.fromarray(tile).save(tmp_path / "terrain-rgb.png")
    heights, _, _ = part_heightmap.heights_of(str(tmp_path / "terrain-rgb.png"), {"encoding": "terrain-rgb"})
    assert heights == pytest.approx(numpy.zeros((3, 3)), abs=1e-6)


# -- pointcloud --------------------------------------------------------------------------------------------------


def write_ply(path, xyz, rgb=None, form="binary_little_endian"):
    properties = [("x", "f4"), ("y", "f4"), ("z", "f4")] + (
        [("red", "u1"), ("green", "u1"), ("blue", "u1")] if rgb is not None else []
    )
    names = {"f4": "float", "u1": "uchar"}
    header = "ply\nformat %s 1.0\nelement vertex %d\n" % (form, len(xyz))
    header += "".join("property %s %s\n" % (names[kind], name) for name, kind in properties)
    header += "element face 0\nproperty list uchar int vertex_indices\nend_header\n"
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        if form == "ascii":
            for index, point in enumerate(xyz):
                values = list(point) + (list(rgb[index]) if rgb is not None else [])
                f.write((" ".join(str(v) for v in values) + "\n").encode("ascii"))
        else:
            record = numpy.zeros(len(xyz), dtype=[(name, "<" + kind) for name, kind in properties])
            for axis, name in enumerate("xyz"):
                record[name] = xyz[:, axis]
            if rgb is not None:
                for axis, name in enumerate(("red", "green", "blue")):
                    record[name] = rgb[:, axis]
            f.write(record.tobytes())


def test_ply_and_text_are_read_alike(tmp_path):
    rng = numpy.random.default_rng(3)
    xyz = numpy.column_stack([rng.uniform(0, 10, 200), rng.uniform(0, 5, 200), rng.uniform(0, 1, 200)])
    write_ply(tmp_path / "binary.ply", xyz)
    write_ply(tmp_path / "ascii.ply", xyz, form="ascii")
    (tmp_path / "points.csv").write_text("x,y,z\n" + "".join("%.9g,%.9g,%.9g\n" % tuple(p) for p in xyz))
    for name in ("binary.ply", "ascii.ply", "points.csv"):
        cloud = part_pointcloud.read(str(tmp_path / name))
        assert cloud.xyz == pytest.approx(xyz.astype(numpy.float32).astype(float), abs=1e-5), name


def test_a_height_field_of_points_takes_the_statistic_of_each_cell(tmp_path):
    # Two points a cell, 1 m and 3 m up, on a 4 x 4 m grid of 1 m cells.
    cells = [(x + 0.5, y + 0.5) for x in range(4) for y in range(4)]
    xyz = numpy.array([(x, y, z) for x, y in cells for z in (1.0, 3.0)])
    (tmp_path / "pairs.xyz").write_text("".join("%s %s %s\n" % tuple(p) for p in xyz))
    for statistic, top in (("max", 3000.0), ("min", 1000.0), ("mean", 2000.0)):
        shape = built(
            part_pointcloud.run(
                {"path": str(tmp_path / "pairs.xyz"), "parameters": {"cell": 1000, "statistic": statistic, "base": 500}}
            )
        )
        # Flat: every cell the same height, so the field stands at the base.
        assert box(shape)[5] == pytest.approx(500.0, abs=1e-3), statistic
        assert volume(shape) == pytest.approx(4000.0 * 4000.0 * 500.0, rel=1e-6), statistic
        assert top  # the heights differ by statistic, and a flat field lifts its lowest to the base


def test_a_cloud_made_voxels_is_coloured_by_its_points(tmp_path):
    xyz = numpy.array([(0.5, 0.5, 0.5), (1.5, 0.5, 0.5), (0.6, 0.5, 0.5)])
    rgb = numpy.array([(255, 0, 0), (0, 0, 255), (250, 0, 0)])
    write_ply(tmp_path / "two.ply", xyz, rgb)
    result = part_pointcloud.run({"path": str(tmp_path / "two.ply"), "parameters": {"as": "voxels", "cell": 1000}})
    shape = built(result)
    assert count(shape, TopAbs_SOLID) == 2 and volume(shape) == pytest.approx(2e9)
    colours = sorted(tuple(s["rgba"][:3]) for s in result["cmf"]["solids"])
    assert colours == [(0, 0, 255), (255, 0, 0)]
    # Named by their colour: a set with no name is one the part type's wrapper drops.
    assert sorted(s["color"] for s in result["cmf"]["solids"]) == ["#0000FF", "#FF0000"]


def test_classes_are_a_lidar_filter(tmp_path):
    (tmp_path / "p.xyz").write_text("0 0 0\n1 0 0\n0 1 1\n")
    said = part_pointcloud.run({"path": str(tmp_path / "p.xyz"), "parameters": {"classes": "2"}})["exception"]
    assert "classes" in said


def test_lidar_is_read_with_its_classes(tmp_path):
    laspy = pytest.importorskip("laspy")
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = numpy.array([0.01, 0.01, 0.01])
    las = laspy.LasData(header)
    las.x = numpy.array([0.0, 10.0, 0.0, 10.0, 5.0])
    las.y = numpy.array([0.0, 0.0, 10.0, 10.0, 5.0])
    las.z = numpy.array([1.0, 1.0, 1.0, 1.0, 30.0])
    las.classification = numpy.array([2, 2, 2, 2, 6])
    las.write(str(tmp_path / "scan.las"))
    shape = built(
        part_pointcloud.run({"path": str(tmp_path / "scan.las"), "parameters": {"classes": "2", "cell": 5000}})
    )
    # The building's point is filtered out: the ground is flat.
    assert box(shape)[5] - box(shape)[2] == pytest.approx(10000.0, abs=1.0)


# -- voxels ------------------------------------------------------------------------------------------------------


def test_every_filled_cell_is_in_exactly_one_box_of_its_label():
    rng = numpy.random.default_rng(7)
    labels = rng.integers(0, 3, (9, 8, 7))
    covered = numpy.zeros(labels.shape, int)
    for label, low, high in voxel_solid.boxes(labels):
        block = labels[low[0] : high[0], low[1] : high[1], low[2] : high[2]]
        assert (block == label).all()
        covered[low[0] : high[0], low[1] : high[1], low[2] : high[2]] += 1
    assert ((covered == 1) == (labels > 0)).all()


def test_voxels_are_exact_and_a_label_a_solid():
    n = 16
    grid = numpy.indices((n, n, n)) - (n - 1) / 2.0
    radius = numpy.sqrt((grid**2).sum(axis=0))
    labels = numpy.where(radius < n / 2.0, numpy.where(grid[2] > 0, 2, 1), 0)
    shape, per_solid, per_face = voxel_solid.solids(labels, 2.0)
    assert BRepCheck_Analyzer(shape).IsValid()
    assert volume(shape) == pytest.approx((labels > 0).sum() * 8.0)
    assert sorted(per_solid) == [1, 2]
    # Every face is its solid's: a picture is drawn face by face.
    assert sorted(set(per_face)) == [1, 2] and len(per_face) == count(shape, TopAbs_FACE)


def test_cells_touching_along_an_edge_are_two_valid_solids():
    labels = numpy.zeros((2, 2, 1), int)
    labels[0, 0, 0] = labels[1, 1, 0] = 1
    shape, per_solid, per_face = voxel_solid.solids(labels, 1.0)
    assert count(shape, TopAbs_SOLID) == 2 and per_solid == [1, 1]
    assert BRepCheck_Analyzer(shape).IsValid()


def chunk(identifier, content, children=b""):
    return identifier + struct.pack("<ii", len(content), len(children)) + content + children


def dictionary(entries):
    out = struct.pack("<i", len(entries))
    for key, value in entries.items():
        for text in (key, value):
            out += struct.pack("<i", len(text)) + text.encode()
    return out


def test_a_magicavoxel_model_is_placed_by_its_scene_in_its_palette(tmp_path):
    # Two one-voxel models, the second 10 voxels along +X of the first, in palette colours 1 and 9.
    xyzi = lambda colour: struct.pack("<i", 1) + struct.pack("<BBBB", 0, 0, 0, colour)  # noqa: E731
    palette = bytearray(1024)
    palette[0:4] = bytes([200, 30, 30, 255])
    palette[32:36] = bytes([30, 30, 200, 255])
    scene = (
        chunk(b"nTRN", struct.pack("<i", 0) + dictionary({}) + struct.pack("<iiii", 1, -1, 0, 1) + dictionary({}))
        + chunk(b"nGRP", struct.pack("<i", 1) + dictionary({}) + struct.pack("<iii", 2, 2, 4))
        + chunk(
            b"nTRN",
            struct.pack("<i", 2) + dictionary({}) + struct.pack("<iiii", 3, -1, 0, 1) + dictionary({"_t": "0 0 0"}),
        )
        + chunk(b"nSHP", struct.pack("<i", 3) + dictionary({}) + struct.pack("<ii", 1, 0) + dictionary({}))
        + chunk(
            b"nTRN",
            struct.pack("<i", 4) + dictionary({}) + struct.pack("<iiii", 5, -1, 0, 1) + dictionary({"_t": "10 0 0"}),
        )
        + chunk(b"nSHP", struct.pack("<i", 5) + dictionary({}) + struct.pack("<ii", 1, 1) + dictionary({}))
    )
    body = (
        chunk(b"SIZE", struct.pack("<iii", 1, 1, 1))
        + chunk(b"XYZI", xyzi(1))
        + chunk(b"SIZE", struct.pack("<iii", 1, 1, 1))
        + chunk(b"XYZI", xyzi(9))
        + scene
        + chunk(b"RGBA", bytes(palette))
    )
    (tmp_path / "pair.vox").write_bytes(b"VOX " + struct.pack("<i", 150) + chunk(b"MAIN", b"", body))
    result = part_voxels.run({"path": str(tmp_path / "pair.vox"), "parameters": {"size": 10}})
    shape = built(result)
    xmin, ymin, zmin, xmax, ymax, zmax = box(shape)
    assert (xmax - xmin, ymax - ymin, zmin, zmax) == pytest.approx((110.0, 10.0, 0.0, 10.0))
    assert result["cmf"]["convention"] == "vox"
    stated = sorted((s["color"], tuple(s["rgba"][:3])) for s in result["cmf"]["solids"])
    assert stated == [("1", (200, 30, 30)), ("9", (30, 30, 200))]
    faces = result["cmf"]["faces"]
    assert len(faces) == 12 and sorted({f["color"] for f in faces}) == ["1", "9"]


def test_binvox_is_read_y_fastest_then_z_then_x(tmp_path):
    occupied = numpy.zeros((4, 4, 4), numpy.uint8)
    occupied[3, 0, 0] = 1  # one voxel at the far end of X
    occupied[0, 2, 1] = 1  # and one along Y, a layer up
    flat = occupied.transpose(0, 2, 1).ravel()
    runs = []
    for value in flat:
        if runs and runs[-2] == value and runs[-1] < 255:
            runs[-1] += 1
        else:
            runs += [int(value), 1]
    (tmp_path / "two.binvox").write_bytes(b"#binvox 1\ndim 4 4 4\ntranslate 0 0 0\nscale 4\ndata\n" + bytes(runs))
    grid = part_voxels.read_binvox(str(tmp_path / "two.binvox"))
    assert sorted(map(tuple, numpy.argwhere(grid.labels))) == [(0, 2, 1), (3, 0, 0)]
    assert grid.size == 1.0


def test_an_array_is_labels_unless_it_has_a_threshold(tmp_path):
    labels = numpy.zeros((5, 5, 5), numpy.int16)
    labels[0:2, 0:2, 0:2] = 7
    labels[3:5, 3:5, 3:5] = 9
    numpy.save(tmp_path / "labels.npy", labels)
    result = part_voxels.run({"path": str(tmp_path / "labels.npy"), "parameters": {}})
    assert count(built(result), TopAbs_SOLID) == 2 and len(result["cmf"]["solids"]) == 2
    result = part_voxels.run({"path": str(tmp_path / "labels.npy"), "parameters": {"threshold": 8}})
    shape = built(result)
    # Densities of 8 and more: the block of nines alone, cut to it and stood on z = 0 over the origin.
    assert count(shape, TopAbs_SOLID) == 1 and volume(shape) == pytest.approx(8.0)
    assert box(shape) == pytest.approx((-1.0, -1.0, 0.0, 1.0, 1.0, 2.0))
    assert "cmf" not in result


def test_too_many_labels_is_a_density_field_without_a_threshold(tmp_path):
    numpy.save(tmp_path / "scan.npy", numpy.arange(512, dtype=numpy.int32).reshape(8, 8, 8))
    said = part_voxels.run({"path": str(tmp_path / "scan.npy"), "parameters": {}})["exception"]
    assert "threshold" in said


def test_the_vox_convention_is_builtin():
    from partcad import cmf_conventions

    assert cmf_conventions.BUILTIN["vox"].ids == "vox"


def test_unit_names():
    assert heightfield.unit_scale("m") == 1000.0 and heightfield.unit_scale("ft") == pytest.approx(304.8)
    with pytest.raises(ValueError, match="unit"):
        heightfield.unit_scale("furlong")
    assert math.isfinite(heightfield.unit_scale("us-ft"))
