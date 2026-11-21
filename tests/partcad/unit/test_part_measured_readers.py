#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The measured-data readers, through every path a file can take them down.

'test_part_measured.py' holds the solids to answers worked out by hand; this
holds the readers to what they say about a file they cannot make a part of,
and to the libraries they read with. Those libraries are each its own type's
requirement and installed in its sandbox, not here: rasterio 1.5 wants
Python 3.12, pye57 publishes no wheel for Linux on ARM. So each is stood in
for by a module of the calls its reader makes, as the library documents them
- rasterio's 'open', its windows and its transform; laspy's 'open',
'chunk_iterator' and point records; pye57's 'E57'; pynrrd's 'read'; nibabel's
'load' - put in 'sys.modules' for one test and taken out after it. Where the
real library is installed, 'test_part_measured.py' reads real files with it.
"""

import importlib.util
import math
import os
import runpy
import struct
import sys
import types

import numpy
import pytest
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

from partcad import output

BUILTIN_IMPORT = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]


def _module(script):
    if BUILTIN_IMPORT not in sys.path:
        sys.path.append(BUILTIN_IMPORT)
    spec = importlib.util.spec_from_file_location(
        "%s_read_under_test" % script[:-3], os.path.join(BUILTIN_IMPORT, script)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


heightfield = _module("heightfield.py")
voxel_solid = _module("voxel_solid.py")
part_heightmap = _module("part_heightmap.py")
part_dem = _module("part_dem.py")
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


def solids(shape):
    explorer, found = TopExp_Explorer(shape, TopAbs_SOLID), 0
    while explorer.More():
        found += 1
        explorer.Next()
    return found


def built(result):
    assert "exception" not in result, result.get("exception")
    assert BRepCheck_Analyzer(result["shape"]).IsValid()
    return result["shape"]


def refused(result, *words):
    assert "shape" not in result
    for word in words:
        assert word in result["exception"], result["exception"]
    return result["exception"]


def stand_in(monkeypatch, name, **attributes):
    """A module named 'name' holding 'attributes', in 'sys.modules' for this test only."""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


# -- rasterio ----------------------------------------------------------------------------------------------------


class Affine:
    """rasterio's transform: x = a * column + b * row + c, y = d * column + e * row + f."""

    def __init__(self, a, b, c, d, e, f):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f


class Window:
    """'rasterio.windows.Window': a block of columns and rows, offsets and lengths possibly fractional."""

    def __init__(self, col_off, row_off, width, height):
        self.col_off, self.row_off, self.width, self.height = col_off, row_off, width, height

    def round_offsets(self):
        return Window(math.floor(self.col_off + 1e-9), math.floor(self.row_off + 1e-9), self.width, self.height)

    def round_lengths(self):
        return Window(self.col_off, self.row_off, math.ceil(self.width - 1e-9), math.ceil(self.height - 1e-9))

    def intersection(self, other):
        left, top = max(self.col_off, other.col_off), max(self.row_off, other.row_off)
        right = min(self.col_off + self.width, other.col_off + other.width)
        bottom = min(self.row_off + self.height, other.row_off + other.height)
        if right <= left or bottom <= top:
            # rasterio raises its WindowError: the reader takes any exception for it.
            raise ValueError("windows do not intersect")
        return Window(left, top, right - left, bottom - top)


def from_bounds(left, bottom, right, top, transform):
    """'rasterio.windows.from_bounds', for a raster whose first row is its north."""
    return Window(
        (left - transform.c) / transform.a,
        (top - transform.f) / transform.e,
        (right - left) / transform.a,
        (top - bottom) / -transform.e,
    )


class CRS:
    def __init__(self, geographic=False, projected=False, metres=1.0):
        self.is_geographic, self.is_projected = geographic, projected
        self.linear_units_factor = ("metre" if metres == 1.0 else "US survey foot", metres)


class Raster:
    """What 'rasterio.open' gives: bands of rows north first, as the transform says, and what nought data is."""

    def __init__(self, bands, transform, crs=None, nodata=None, driver="GTiff"):
        self.bands = [numpy.asarray(band) for band in bands]
        self.count = len(self.bands)
        self.height, self.width = self.bands[0].shape
        self.transform, self.crs, self.nodata, self.driver = transform, crs, nodata, driver

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    @property
    def bounds(self):
        t = self.transform
        return (t.c, t.f + t.e * self.height, t.c + t.a * self.width, t.f)

    def window_transform(self, window):
        t = self.transform
        return Affine(t.a, t.b, t.c + window.col_off * t.a, t.d, t.e, t.f + window.row_off * t.e)

    def read(self, band, window=None, masked=False):
        data = self.bands[band - 1]
        if window is not None:
            rows = slice(int(window.row_off), int(window.row_off + window.height))
            data = data[rows, int(window.col_off) : int(window.col_off + window.width)]
        if not masked:
            return data
        return numpy.ma.masked_equal(data, self.nodata) if self.nodata is not None else numpy.ma.masked_array(data)


def rasterio(monkeypatch, rasters):
    """rasterio, opening the 'Raster' 'rasters' holds by path, and refusing any other path as GDAL does."""

    def open_(path):
        if path not in rasters:
            # rasterio's RasterioIOError is an OSError.
            raise OSError("'%s' not recognized as a supported file format" % path)
        return rasters[path]

    windows = stand_in(monkeypatch, "rasterio.windows", Window=Window, from_bounds=from_bounds)
    return stand_in(monkeypatch, "rasterio", open=open_, windows=windows)


def utm(grid, nodata=None):
    """4 x 3 cells of 10 m in a projected reference system, the first row the north one."""
    return Raster([grid], Affine(10.0, 0.0, 320000.0, 0.0, -10.0, 4290000.0), CRS(projected=True), nodata)


def test_a_projected_model_is_read_at_its_cell_north_up_with_its_holes_left_to_fill(tmp_path, monkeypatch):
    path = str(tmp_path / "dem.tif")
    grid = numpy.array([[30.0, 30.0, 30.0, 30.0], [20.0, -9999.0, 20.0, 20.0], [10.0, 10.0, 10.0, 10.0]], "float32")
    rasterio(monkeypatch, {path: utm(grid, nodata=-9999.0)})
    heights, cell, what = part_dem.read(path, {})
    assert cell == pytest.approx((10000.0, 10000.0)) and what == "GTiff, 4 x 3"
    # [x][y], y north: a column from the south edge up.
    assert heights.shape == (4, 3) and heights[0].tolist() == [10000.0, 20000.0, 30000.0]
    assert math.isnan(heights[1, 1]) and numpy.isfinite(heights).sum() == 11
    shape = built(part_dem.run({"path": path, "parameters": {"base": 1000}}))
    xmin, ymin, zmin, xmax, ymax, zmax = box(shape)
    assert (xmin, ymin, xmax, ymax) == pytest.approx((-20000.0, -15000.0, 20000.0, 15000.0))
    assert zmin == pytest.approx(0.0, abs=1e-3) and zmax == pytest.approx(21000.0, rel=0.05)


def test_a_model_in_feet_has_its_cell_in_feet_and_one_with_no_reference_system_in_its_own_units(tmp_path, monkeypatch):
    feet, bare = str(tmp_path / "ny.tif"), str(tmp_path / "bare.tif")
    grid = numpy.arange(12, dtype="float32").reshape(3, 4)
    plane = Affine(10.0, 0.0, 980000.0, 0.0, -10.0, 200000.0)
    rasterio(
        monkeypatch,
        {
            feet: Raster([grid], plane, CRS(projected=True, metres=1200.0 / 3937.0)),
            bare: Raster([grid], Affine(2.0, 0.0, 0.0, 0.0, -3.0, 0.0), None, driver="AAIGrid"),
        },
    )
    _, cell, _ = part_dem.read(feet, {"unit": "us-ft"})
    assert cell == pytest.approx((3048.006, 3048.006), abs=1e-3)
    heights, cell, what = part_dem.read(bare, {"unit": "mm"})
    assert cell == (2000.0, 3000.0) and what == "AAIGrid, 4 x 3"
    assert heights[:, 0].tolist() == [8.0, 9.0, 10.0, 11.0]


def test_a_geographic_model_is_metres_at_its_latitude_and_bounds_take_part_of_it(tmp_path, monkeypatch):
    path = str(tmp_path / "N38W078.hgt")
    # An SRTM tile: 1201 x 1201 heights over a degree, the corners on whole degrees, falling to the south.
    step = 1.0 / 1200.0
    rows = numpy.linspace(400.0, 0.0, 1201)[:, None] + numpy.zeros((1, 1201))
    tile = Affine(step, 0.0, -78.0 - step / 2.0, 0.0, -step, 39.0 + step / 2.0)
    rasterio(monkeypatch, {path: Raster([rows.astype("int16")], tile, CRS(geographic=True), driver="SRTMHGT")})
    for bounds in ("-77.5 38.5 -77.49 38.51", [-77.5, 38.5, -77.49, 38.51], "-77.5, 38.5, -77.49, 38.51"):
        heights, cell, what = part_dem.read(path, {"bounds": bounds})
        assert heights.shape == (12, 12) and what == "SRTMHGT, 12 x 12, geographic"
        # The window's middle latitude: its top row, 588 rows down, and six more.
        east, north = part_dem.metres_per_degree(39.0 + step / 2.0 - 594 * step)
        assert cell == pytest.approx((east * step * 1000.0, north * step * 1000.0), rel=1e-12)
        # The heights fall to the south, a third of a metre a row: rows 588 to 599 of the tile.
        assert heights[0, -1] == pytest.approx(float(int(rows[588, 0])) * 1000.0)
        assert heights[0, 0] == pytest.approx(float(int(rows[599, 0])) * 1000.0)
    refused(part_dem.run({"path": path, "parameters": {"bounds": "10 10 11 11"}}), "not over", "N38W078.hgt")


def test_a_model_that_runs_south_to_north_or_east_to_west_is_turned(tmp_path, monkeypatch):
    north, west = str(tmp_path / "up.tif"), str(tmp_path / "west.tif")
    grid = numpy.array([[0.0, 1.0], [5.0, 6.0], [9.0, 10.0]], "float32")
    rasterio(
        monkeypatch,
        {
            # The first row is the south one, as a positive 'e' says.
            north: Raster([grid], Affine(10.0, 0.0, 0.0, 0.0, 10.0, 0.0), CRS(projected=True)),
            # And here the first column is the east one.
            west: Raster([grid], Affine(-10.0, 0.0, 0.0, 0.0, -10.0, 0.0), CRS(projected=True)),
        },
    )
    heights, _, _ = part_dem.read(north, {})
    assert heights[0].tolist() == [0.0, 5000.0, 9000.0] and heights[1].tolist() == [1000.0, 6000.0, 10000.0]
    heights, _, _ = part_dem.read(west, {})
    # West first: the second column is the west one, and north is the first row.
    assert heights[0].tolist() == [10000.0, 6000.0, 1000.0] and heights[1].tolist() == [9000.0, 5000.0, 0.0]


def test_what_a_model_cannot_be_made_of_is_said(tmp_path, monkeypatch):
    grid = numpy.ones((3, 4), "float32")
    paths = {name: str(tmp_path / name) for name in ("one.tif", "turned.tif", "empty.tif")}
    rasterio(
        monkeypatch,
        {
            paths["one.tif"]: utm(grid),
            paths["turned.tif"]: Raster([grid], Affine(10.0, 1.0, 0.0, 0.0, -10.0, 0.0), CRS(projected=True)),
            paths["empty.tif"]: utm(numpy.full((3, 4), -32768.0, "float32"), nodata=-32768.0),
        },
    )
    refused(part_dem.run({"path": paths["one.tif"], "parameters": {"band": 2}}), "1 band(s)", "'band' is 2")
    refused(part_dem.run({"path": paths["turned.tif"], "parameters": {}}), "rotated")
    refused(part_dem.run({"path": paths["empty.tif"], "parameters": {}}), "no-data value")
    refused(part_dem.run({"path": paths["one.tif"], "parameters": {"bounds": "1 2 0 3"}}), "west before east")
    refused(part_dem.run({"path": paths["one.tif"], "parameters": {"bounds": "1 2 3"}}), "west south east north")
    refused(part_dem.run({"path": str(tmp_path / "unknown.tif"), "parameters": {}}), "not recognized")


# -- laspy -------------------------------------------------------------------------------------------------------


class LasPoints:
    """A laspy point record: its dimensions as attributes, as long as it has points, sliced as an array is."""

    def __init__(self, dimensions):
        self.__dict__["dimensions"] = dimensions

    def __len__(self):
        return len(self.dimensions["x"])

    def __getitem__(self, index):
        return LasPoints({name: values[index] for name, values in self.dimensions.items()})

    def __getattr__(self, name):
        try:
            return self.__dict__["dimensions"][name]
        except KeyError:
            raise AttributeError(name)


class LasReader:
    """What 'laspy.open' gives: a header, and the points a chunk at a time."""

    def __init__(self, dimensions, point_format=3, version="1.2"):
        self.points = LasPoints({name: numpy.asarray(values) for name, values in dimensions.items()})
        # laspy names X, Y and Z, the stored integers, in capitals; the rest as written here.
        names = ("X", "Y", "Z", "intensity") + tuple(name for name in dimensions if name not in "xyz")
        self.header = types.SimpleNamespace(
            point_format=types.SimpleNamespace(dimension_names=names, id=point_format),
            point_count=len(self.points),
            version=version,
        )
        self.chunks = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def chunk_iterator(self, size):
        for start in range(0, len(self.points), size):
            self.chunks.append(size)
            yield self.points[start : start + size]


def laspy(monkeypatch, files):
    def open_(path):
        if path not in files:
            raise OSError("%s is not a LAS file" % path)
        return files[path]

    return stand_in(monkeypatch, "laspy", open=open_)


def test_lidar_is_read_a_chunk_at_a_time_thinned_through_the_file_in_its_colours_and_classes(tmp_path, monkeypatch):
    path = str(tmp_path / "survey.laz")
    x = numpy.arange(1000.0)
    ground = x < 500
    reader = LasReader(
        {
            "x": x,
            "y": numpy.zeros(1000),
            "z": numpy.where(ground, 1.0, 30.0),
            "classification": numpy.where(ground, 2, 6).astype(numpy.uint8),
            "red": numpy.where(ground, 65535, 0).astype(numpy.uint16),
            "green": numpy.zeros(1000, numpy.uint16),
            "blue": numpy.where(ground, 0, 65535).astype(numpy.uint16),
        },
        point_format=7,
        version="1.4",
    )
    laspy(monkeypatch, {path: reader})
    # Chunks that do not divide the step: every 7th point, wherever a chunk starts.
    monkeypatch.setattr(part_pointcloud, "LAS_CHUNK", 33)
    cloud = part_pointcloud.read(path, 143)
    assert cloud.xyz[:, 0] == pytest.approx(numpy.arange(0.0, 1000.0, 7.0))
    assert cloud.what == "LAS 1.4, point format 7" and set(reader.chunks) == {33}
    # Chunks shorter than the step: some hold no point of every 5th, and are passed over.
    monkeypatch.setattr(part_pointcloud, "LAS_CHUNK", 3)
    assert part_pointcloud.read(path, 200).xyz[:, 0] == pytest.approx(numpy.arange(0.0, 1000.0, 5.0))
    # Sixteen bits a colour, made eight.
    assert cloud.rgb.max() == 255.0 and cloud.rgb[0].tolist() == [255.0, 0.0, 0.0]
    assert cloud.classes.tolist() == numpy.where(cloud.xyz[:, 0] < 500, 2, 6).tolist()


def test_classes_keep_their_points_in_their_colours(tmp_path, monkeypatch):
    path = str(tmp_path / "street.las")
    # Ten red ground points along X, one metre apart, and a blue building's ten points above them.
    x = numpy.concatenate([numpy.arange(10.0) + 0.5, numpy.arange(10.0) + 0.5])
    laspy(
        monkeypatch,
        {
            path: LasReader(
                {
                    "x": x,
                    "y": numpy.full(20, 0.5),
                    "z": numpy.concatenate([numpy.full(10, 0.5), numpy.full(10, 8.5)]),
                    "classification": numpy.array([2] * 10 + [6] * 10),
                    "red": numpy.array([255] * 10 + [0] * 10),
                    "green": numpy.zeros(20),
                    "blue": numpy.array([0] * 10 + [255] * 10),
                }
            )
        },
    )
    result = part_pointcloud.run({"path": path, "parameters": {"classes": [2], "as": "voxels", "cell": 1000}})
    shape = built(result)
    # The ground's ten voxels, in a row, and nothing of the building.
    assert volume(shape) == pytest.approx(10 * 1000.0**3) and box(shape)[5] - box(shape)[2] == pytest.approx(1000.0)
    assert [s["color"] for s in result["cmf"]["solids"]] == ["#FF0000"]


def test_lidar_colours_are_eight_bits_where_a_writer_wrote_eight_and_none_where_it_wrote_none(tmp_path, monkeypatch):
    eight, dark, bare = (str(tmp_path / name) for name in ("eight.las", "dark.las", "bare.las"))
    xyz = {"x": numpy.arange(4.0), "y": numpy.zeros(4), "z": numpy.zeros(4)}
    laspy(
        monkeypatch,
        {
            eight: LasReader(dict(xyz, red=numpy.full(4, 200), green=numpy.full(4, 100), blue=numpy.zeros(4))),
            dark: LasReader(dict(xyz, red=numpy.zeros(4), green=numpy.zeros(4), blue=numpy.zeros(4))),
            bare: LasReader(dict(xyz)),
        },
    )
    assert part_pointcloud.read(eight).rgb[0].tolist() == [200.0, 100.0, 0.0]
    assert part_pointcloud.read(dark).rgb is None
    cloud = part_pointcloud.read(bare)
    assert cloud.rgb is None and cloud.classes is None and len(cloud.xyz) == 4
    refused(part_pointcloud.run({"path": bare, "parameters": {"classes": "2 6"}}), "this file has none")


def test_an_empty_survey_is_said_to_be_empty(tmp_path, monkeypatch):
    path, roofs = str(tmp_path / "empty.las"), str(tmp_path / "roofs.las")
    laspy(
        monkeypatch,
        {
            path: LasReader({"x": [], "y": [], "z": [], "classification": []}),
            roofs: LasReader(
                {"x": [0.0, 1.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [9.0, 9.0, 9.0], "classification": [6, 6, 6]}
            ),
        },
    )
    assert part_pointcloud.read(path).xyz.shape == (0, 3)
    refused(part_pointcloud.run({"path": path, "parameters": {}}), "holds 0 points")
    refused(part_pointcloud.run({"path": roofs, "parameters": {"classes": 2}}), "holds 0 points of those classes")


# -- pye57 -------------------------------------------------------------------------------------------------------


class E57:
    """'pye57.E57': its scans, each read whole and moved by its pose ('transform'), with or without colours."""

    def __init__(self, scans, headers=True):
        self.scans, self.headers, self.read = scans, headers, []

    @property
    def scan_count(self):
        return len(self.scans)

    def get_header(self, index):
        if not self.headers:
            raise RuntimeError("this scan's header says no point count")
        return types.SimpleNamespace(point_count=len(self.scans[index]["cartesianX"]))

    def read_scan(self, index, colors=False, ignore_missing_fields=False, transform=True):
        assert colors and ignore_missing_fields and transform
        self.read.append(index)
        return dict(self.scans[index])


def pye57(monkeypatch, files):
    def open_(path):
        if path not in files:
            raise OSError("%s is not an E57 file" % path)
        return files[path]

    return stand_in(monkeypatch, "pye57", E57=open_)


def scan(x, colour=None, z=0.5):
    found = {
        "cartesianX": numpy.asarray(x, float),
        "cartesianY": numpy.full(len(x), 0.5),
        "cartesianZ": numpy.full(len(x), z),
    }
    if colour is not None:
        for channel, value in zip(("colorRed", "colorGreen", "colorBlue"), colour):
            found[channel] = numpy.full(len(x), value)
    return found


def test_every_scan_is_read_and_thinned_as_it_is_read_and_sixteen_bit_colours_are_made_eight(tmp_path, monkeypatch):
    path = str(tmp_path / "site.e57")
    e57 = E57([scan(numpy.arange(10.0) + 0.5, (65535, 0, 0)), scan(numpy.arange(10.0) + 20.5, (0, 0, 65535))])
    pye57(monkeypatch, {path: e57})
    # Twenty points, five asked for: every 4th of each scan, from each scan's first.
    cloud = part_pointcloud.read(path, 5)
    assert cloud.xyz[:, 0].tolist() == [0.5, 4.5, 8.5, 20.5, 24.5, 28.5] and cloud.what == "E57, 2 scan(s)"
    assert cloud.rgb.max() == 255.0 and cloud.rgb[0].tolist() == [255.0, 0.0, 0.0]
    assert e57.read == [0, 1]
    # Six read for five: the part takes every second of them, and has three - two red, apart, and a blue one.
    result = part_pointcloud.run({"path": path, "parameters": {"maxPoints": 5, "as": "voxels", "cell": 1000}})
    assert solids(built(result)) == 3 and volume(result["shape"]) == pytest.approx(3 * 1000.0**3)
    assert sorted(s["color"] for s in result["cmf"]["solids"]) == ["#0000FF", "#FF0000", "#FF0000"]


def test_a_scan_with_no_colours_leaves_the_cloud_uncoloured_and_one_with_no_count_is_read_whole(tmp_path, monkeypatch):
    path, empty = str(tmp_path / "mixed.e57"), str(tmp_path / "empty.e57")
    pye57(
        monkeypatch,
        {path: E57([scan([0.5, 1.5], (255, 0, 0)), scan([2.5, 3.5])], headers=False), empty: E57([])},
    )
    cloud = part_pointcloud.read(path, 2)
    assert cloud.rgb is None and cloud.xyz[:, 0].tolist() == [0.5, 1.5, 2.5, 3.5]
    refused(part_pointcloud.run({"path": empty, "parameters": {}}), "holds no scan")


# -- pynrrd and nibabel ------------------------------------------------------------------------------------------


def nrrd(monkeypatch, files):
    def read(path):
        if path not in files:
            raise OSError("%s is not an NRRD file" % path)
        return files[path]

    return stand_in(monkeypatch, "nrrd", read=read)


def segmentation():
    labels = numpy.zeros((4, 4, 4), numpy.uint8)
    labels[0:2, 0:2, 0:1] = 1
    labels[2:4, 2:4, 3:4] = 2
    return labels


def test_an_nrrd_volume_is_read_at_its_spacings_or_its_space_directions(tmp_path, monkeypatch):
    spaced, directed, plain = (str(tmp_path / name) for name in ("spaced.nrrd", "directed.nrrd", "plain.nrrd"))
    directions = numpy.array([[2.0, 0.0, 0.0], [0.0, -3.0, 0.0], [0.0, 0.0, 4.0], [numpy.nan] * 3])
    nrrd(
        monkeypatch,
        {
            spaced: (segmentation(), {"spacings": [2.0, 3.0, 4.0]}),
            # A fourth axis of one value, as a scalar volume written with a component axis is.
            directed: (segmentation()[..., None], {"space directions": directions}),
            # Spacings that are not a voxel's size: none at all, then.
            plain: (segmentation(), {"spacings": [1.0, 0.0, 1.0]}),
        },
    )
    for path in (spaced, directed):
        grid = part_voxels.read(path, {})
        assert grid.size == (2.0, 3.0, 4.0) and grid.what == "NRRD of 2 labels" and grid.files == []
        result = part_voxels.run({"path": path, "parameters": {}})
        assert solids(built(result)) == 2 and volume(result["shape"]) == pytest.approx(8 * 2.0 * 3.0 * 4.0)
        assert box(result["shape"]) == pytest.approx((-4.0, -6.0, 0.0, 4.0, 6.0, 16.0))
        assert "dependencies" not in result
    assert part_voxels.read(plain, {}).size is None
    assert box(built(part_voxels.run({"path": plain, "parameters": {}}))) == pytest.approx((-2, -2, 0, 2, 2, 4))


def test_a_detached_nrrd_header_keys_the_part_on_its_data_or_on_nothing(tmp_path, monkeypatch):
    one, listed = str(tmp_path / "seg.nhdr"), str(tmp_path / "slices.nhdr")
    nrrd(
        monkeypatch,
        {one: (segmentation(), {"data file": "seg.raw"}), listed: (segmentation(), {"datafile": "LIST"})},
    )
    result = part_voxels.run({"path": one, "parameters": {}})
    built(result)
    assert result["dependencies"] == [os.path.join(str(tmp_path), "seg.raw")]
    # Files the header lists after itself are not told here: the part is not cached rather than keyed without them.
    result = part_voxels.run({"path": listed, "parameters": {}})
    built(result)
    assert result["dependencies"] is None
    assert part_voxels.detached(one, {"data file": "slice%02d.raw 1 9 0"}) is None
    assert part_voxels.detached(one, {"data file": "slice%d.raw 3 1 -1"}) == [
        os.path.join(str(tmp_path), "slice%d.raw" % n) for n in (3, 2, 1)
    ]


class NiftiHeader:
    def __init__(self, zooms, unit, slope=None, inter=None):
        self.zooms, self.unit, self.slope, self.inter = zooms, unit, slope, inter

    def get_zooms(self):
        return self.zooms

    def get_xyzt_units(self):
        return (self.unit, "sec")

    def get_slope_inter(self):
        return (self.slope, self.inter)


class NiftiImage:
    """'nibabel.load': the stored values ('dataobj'), and the scaled ones ('get_fdata'), as the header scales them."""

    def __init__(self, stored, header):
        self.dataobj, self.header = numpy.asarray(stored), header

    def get_fdata(self):
        slope = 1.0 if self.header.slope is None else self.header.slope
        inter = 0.0 if self.header.inter is None else self.header.inter
        return self.dataobj.astype(float) * slope + inter


def nibabel(monkeypatch, files):
    def load(path):
        if path not in files:
            raise OSError("%s is not a NIfTI file" % path)
        return files[path]

    return stand_in(monkeypatch, "nibabel", load=load)


def test_a_nifti_volume_is_read_in_its_unit_as_its_header_scales_it(tmp_path, monkeypatch):
    density, labels, scaled = (str(tmp_path / name) for name in ("scan.nii.gz", "labels.nii", "scaled.nii"))
    column = numpy.zeros((3, 3, 3), numpy.float32)
    column[1, 1, :] = 0.9
    halves = numpy.zeros((3, 3, 3), numpy.int16)
    halves[1, 1, :] = 1  # stored as one, and read as 0.6 by the header's slope and intercept
    nibabel(
        monkeypatch,
        {
            density: NiftiImage(column, NiftiHeader((0.5, 0.5, 0.5, 1.0), "meter")),
            labels: NiftiImage(
                segmentation().astype(numpy.int16), NiftiHeader((2000.0, 3000.0, 4000.0), "micron", 1.0, 0.0)
            ),
            scaled: NiftiImage(halves, NiftiHeader((1.0, 1.0, 1.0), "unknown", 0.5, 0.1)),
        },
    )
    grid = part_voxels.read(density, {"threshold": 0.5})
    assert grid.size == (500.0, 500.0, 500.0) and grid.what == "NIfTI, filled at 0.5 and above"
    shape = built(part_voxels.run({"path": density, "parameters": {"threshold": 0.5}}))
    assert box(shape) == pytest.approx((-250.0, -250.0, 0.0, 250.0, 250.0, 1500.0))
    # Integers, unscaled, are labels still.
    grid = part_voxels.read(labels, {})
    assert grid.size == pytest.approx((2.0, 3.0, 4.0)) and grid.what == "NIfTI of 2 labels"
    # Scaled to 0.6 they are densities, filled at 0.5 and above, in millimetres where the unit is not one it knows.
    grid = part_voxels.read(scaled, {})
    assert grid.size == (1.0, 1.0, 1.0) and grid.labels.sum() == 3


# -- What a point cloud's file says, and what a part asks of it --------------------------------------------------


def write(path, text):
    path.write_bytes(text if isinstance(text, bytes) else text.encode("ascii"))
    return str(path)


def test_a_ply_file_that_holds_no_point_cloud_is_said_to_be_wrong(tmp_path):
    header = "ply\nformat ascii 1.0\n"
    for text, said in (
        ("PLX\n", "not a PLY file"),
        (header + "element vertex 1\nproperty float x\n", "no 'end_header'"),
        ("ply\nformat binary_middle_endian 1.0\nelement vertex 0\nend_header\n", "format 'binary_middle_endian'"),
        (
            "ply\nformat binary_little_endian 1.0\nelement face 1\nproperty list uchar int vertex_indices\n"
            "element vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n",
            "a 'face' element of lists before its vertices",
        ),
        (header + "element face 0\nproperty list uchar int vertex_indices\nend_header\n", "holds no vertices"),
        (
            header + "element vertex 1\nproperty float x\nproperty list uchar int i\nend_header\n0 1 0\n",
            "list property",
        ),
        (header + "element vertex 2\nproperty float x\nproperty float y\nend_header\n0 0\n1 1\n", "no x, y and z"),
    ):
        with pytest.raises(ValueError, match="cloud.ply") as raised:
            part_pointcloud.read(write(tmp_path / "cloud.ply", text))
        assert said in str(raised.value)


def test_elements_before_the_vertices_are_passed_over(tmp_path):
    ascii_ = write(
        tmp_path / "ascii.ply",
        "ply\nformat ascii 1.0\ncomment by hand\n\nelement camera 2\nproperty float a\nproperty float b\n"
        "element vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
        "9 9\n8 8\n0 0 0 255 0 0\n1 0 0 255 0 0\n0 1 1 255 0 0\n",
    )
    cloud = part_pointcloud.read(ascii_)
    assert cloud.xyz.tolist() == [[0, 0, 0], [1, 0, 0], [0, 1, 1]] and cloud.rgb[:, 0].tolist() == [255] * 3
    # Big-endian, after an element of a float and a double a record.
    header = (
        "ply\nformat binary_big_endian 1.0\nelement camera 2\nproperty float a\nproperty double b\n"
        "element vertex 2\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
    ).encode("ascii")
    cameras = struct.pack(">fdfd", 9.0, 9.0, 8.0, 8.0)
    vertices = struct.pack(">ffffff", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    cloud = part_pointcloud.read(write(tmp_path / "big.ply", header + cameras + vertices))
    assert cloud.xyz.tolist() == [[1, 2, 3], [4, 5, 6]] and cloud.rgb is None and "binary big endian" in cloud.what


def test_text_has_colours_where_it_has_six_columns_of_them(tmp_path):
    with pytest.raises(ValueError, match="no line of three numbers"):
        part_pointcloud.read(write(tmp_path / "words.txt", "x y z\nsome words here\n1 2\n"))
    # A '.pts' scan: a count, then x y z, intensity, and r g b.
    pts = part_pointcloud.read(
        write(tmp_path / "scan.pts", "3\n0 0 0 10 255 0 0\n1 0 0 10 255 0 0\n0 1 1 10 0 0 255\n")
    )
    assert pts.rgb.tolist() == [[255, 0, 0], [255, 0, 0], [0, 0, 255]]
    six = part_pointcloud.read(write(tmp_path / "six.xyz", "0;0;0;0;128;0\n1;0;0;0;128;0\n0;1;1;0;128;0\n"))
    assert six.rgb[:, 1].tolist() == [128] * 3 and six.what == "text, 6 columns"
    # Six columns that are no colour - normals - are not taken for one.
    normals = part_pointcloud.read(write(tmp_path / "normals.xyz", "0 0 0 0 0 -1\n1 0 0 0 0 1\n0 1 1 0 1 0\n"))
    assert normals.rgb is None and normals.xyz.shape == (3, 3)


def test_a_cloud_too_small_or_asked_for_what_cannot_be_is_said_to_be(tmp_path):
    pair = write(tmp_path / "pair.xyz", "0 0 0\n1 1 1\n")
    refused(part_pointcloud.run({"path": pair, "parameters": {}}), "holds 2 points", "pair.xyz")
    three = write(tmp_path / "three.xyz", "0 0 0\n10 0 0\n0 10 1\n")
    for parameters, said in (
        ({"origin": "survey"}, "'origin' is 'center' or 'file', not 'survey'"),
        ({"as": "mesh"}, "'as' is one of heightfield, voxels, not 'mesh'"),
        ({"statistic": "median"}, "'statistic' is one of max, min, mean, not 'median'"),
        ({"cell": 0.001}, "makes a grid of"),
        ({"unit": "furlong"}, "'unit'"),
    ):
        refused(part_pointcloud.run({"path": three, "parameters": parameters}), said)
    refused(
        part_pointcloud.run({"path": write(tmp_path / "nan.xyz", "0 0 0\n1 0 nan\n0 1 1\n"), "parameters": {}}),
        "not a number",
    )
    refused(part_pointcloud.run({"path": str(tmp_path / "scan.obj"), "parameters": {}}), "none of them")
    assert part_pointcloud._classes(None) is None and part_pointcloud._classes(2.0) == [2]
    assert part_pointcloud._classes([2, "6"]) == [2, 6] and part_pointcloud._classes("3,4 5") == [3, 4, 5]


def test_a_cloud_gets_a_cell_of_its_own_and_is_told_when_most_of_its_cells_are_empty(tmp_path, capsys):
    # A hundred points over 9 x 9 m: about four points a cell, which is 1.8 m a cell.
    points = [(x, y, (x + y) / 10.0) for x in range(10) for y in range(10)]
    dense = write(tmp_path / "dense.xyz", "".join("%d %d %.1f\n" % p for p in points))
    built(part_pointcloud.run({"path": dense, "parameters": {}}))
    assert "hold no point" not in capsys.readouterr().err
    # The corners of 10 x 10 m, at 1 m a cell: 4 cells of 121 measured.
    corners = write(tmp_path / "corners.xyz", "0 0 0\n10 0 1\n0 10 1\n10 10 2\n")
    built(part_pointcloud.run({"path": corners, "parameters": {"cell": 1000}}))
    assert "117 of the 121 cells of 1000 mm hold no point" in capsys.readouterr().err


def test_voxels_of_an_uncoloured_cloud_are_one_solid_where_the_file_has_them(tmp_path):
    path = write(tmp_path / "line.xyz", "10.5 20.5 3.5\n11.5 20.5 3.5\n12.5 20.5 3.5\n")
    result = part_pointcloud.run({"path": path, "parameters": {"as": "voxels", "cell": 1000, "origin": "file"}})
    shape = built(result)
    assert "cmf" not in result and solids(shape) == 1
    assert box(shape) == pytest.approx((10500.0, 20500.0, 3500.0, 13500.0, 21500.0, 4500.0))


# -- What a height map's file says, and what a part asks of it ---------------------------------------------------


def test_an_ascii_grid_says_its_cell_one_way_or_another_and_its_size(tmp_path):
    path = write(tmp_path / "dxdy.asc", "ncols 3\nnrows 2\n\nxllcorner 0\nyllcorner 0\ndx 2\ndy 3\n1 2 3\n4 5 6\n")
    heights, cell, what = part_heightmap.heights_of(path, {"unit": "mm"})
    assert cell == (2.0, 3.0) and what == "ASCII grid" and heights.tolist() == [[4, 1], [5, 2], [6, 3]]
    said = part_heightmap.run({"path": write(tmp_path / "bare.asc", "1 2 3\n4 5 6\n"), "parameters": {}})
    refused(said, "not an ESRI ASCII grid")
    said = part_heightmap.run(
        {"path": write(tmp_path / "short.asc", "ncols 3\nnrows 2\n1 2 3\n4 5\n"), "parameters": {}}
    )
    refused(said, "says it is 3 x 2 and holds 5 heights")


def test_an_image_of_floats_is_in_its_unit_and_one_of_integers_in_its_levels(tmp_path):
    from PIL import Image

    floats = numpy.array([[1.0, 2.0], [3.0, 4.0]], numpy.float32)
    Image.fromarray(floats).save(tmp_path / "floats.tif")
    heights, cell, what = part_heightmap.heights_of(str(tmp_path / "floats.tif"), {"cell": "2, 3"})
    # Metres, the first row north.
    assert heights.tolist() == [[3000.0, 1000.0], [4000.0, 2000.0]] and cell == (2.0, 3.0) and "2 x 2 gray" in what
    # 32-bit levels: of 65535, unless the image holds more than that.
    for top, full in ((65535, 65535.0), (131070, 131070.0)):
        Image.fromarray(numpy.array([[0, top // 2], [top, 0]], numpy.int32)).save(tmp_path / "levels.tif")
        heights, _, _ = part_heightmap.heights_of(str(tmp_path / "levels.tif"), {"relief": 100})
        assert heights.max() == pytest.approx(top / full * 100.0)


def test_a_transparent_pixel_is_a_hole_and_an_image_of_another_kind_is_refused(tmp_path):
    from PIL import Image

    gray = numpy.full((3, 3, 2), 255, numpy.uint8)
    gray[1, 1, 1] = 0  # transparent
    Image.fromarray(gray).save(tmp_path / "holed.png")
    heights, _, _ = part_heightmap.heights_of(str(tmp_path / "holed.png"), {"relief": 10})
    assert math.isnan(heights[1, 1]) and numpy.isfinite(heights).sum() == 8
    built(part_heightmap.run({"path": str(tmp_path / "holed.png"), "parameters": {"relief": 10}}))
    Image.new("CMYK", (3, 3)).save(tmp_path / "print.jpg")
    refused(part_heightmap.run({"path": str(tmp_path / "print.jpg"), "parameters": {"relief": 10}}), "CMYK image")
    refused(
        part_heightmap.run({"path": str(tmp_path / "print.jpg"), "parameters": {"encoding": "mapbox"}}), "'encoding'"
    )


def test_an_array_is_a_height_map_in_its_unit_when_it_is_two_dimensional(tmp_path):
    numpy.save(tmp_path / "ramp.npy", numpy.array([[0, 1, 2], [3, 4, 5]], numpy.int16))
    heights, cell, what = part_heightmap.heights_of(str(tmp_path / "ramp.npy"), {"unit": "cm"})
    assert (
        heights.tolist() == [[30.0, 0.0], [40.0, 10.0], [50.0, 20.0]] and cell == (1000.0, 1000.0) and what == "array"
    )
    built(part_heightmap.run({"path": str(tmp_path / "ramp.npy"), "parameters": {"cell": [100, 100], "base": 10}}))
    numpy.save(tmp_path / "cube.npy", numpy.zeros((2, 2, 2)))
    refused(part_heightmap.run({"path": str(tmp_path / "cube.npy"), "parameters": {}}), "3-dimensional array")


def test_a_height_field_says_what_it_cannot_be_built_of():
    hill = numpy.array([[1.0, 2.0, 1.0], [2.0, 5.0, 2.0], [1.0, 2.0, 1.0]])
    with pytest.raises(ValueError, match="reaches z = 0"):
        # Turned upside down, the hill's top is below its base.
        heightfield.build(hill, 10.0, 1.0, exaggeration=-1.0)
    with pytest.raises(ValueError, match="2 x 2 heights, and this has 1 x 3"):
        heightfield.build(numpy.ones((1, 3)), 10.0, 1.0)
    with pytest.raises(ValueError, match="larger than nothing"):
        heightfield.build(hill, (10.0, 0.0), 1.0)
    with pytest.raises(ValueError, match="a height holds a value that is not a number"):
        heightfield.finite([1.0, float("inf")], "a height")
    assert [heightfield.is_number(v) for v in ("1.5", "-2", "nan", "inf", "x", None)] == [
        True,
        True,
        False,
        False,
        False,
        False,
    ]


# -- What a voxel file says, and what a part asks of it ----------------------------------------------------------


def chunk(identifier, content, children=b""):
    return identifier + struct.pack("<ii", len(content), len(children)) + content + children


def dictionary(entries):
    out = struct.pack("<i", len(entries))
    for key, value in entries.items():
        for text in (key, value):
            out += struct.pack("<i", len(text)) + text.encode()
    return out


def vox(models, scene=b"", palette=None):
    """A MagicaVoxel file of 'models' - '(size, [(x, y, z, colour)])' - its scene's chunks, and a palette."""
    body = b""
    for size, voxels in models:
        body += chunk(b"SIZE", struct.pack("<iii", *size))
        body += chunk(b"XYZI", struct.pack("<i", len(voxels)) + b"".join(struct.pack("<BBBB", *v) for v in voxels))
    body += scene
    if palette is not None:
        body += chunk(b"RGBA", bytes(palette))
    return b"VOX " + struct.pack("<i", 150) + chunk(b"MAIN", b"", body)


def trn(node, child, attributes):
    return chunk(
        b"nTRN",
        struct.pack("<i", node) + dictionary({}) + struct.pack("<iiii", child, -1, 0, 1) + dictionary(attributes),
    )


def test_a_magicavoxel_model_is_turned_as_its_scene_says(tmp_path):
    rod = ((3, 1, 1), [(0, 0, 0, 1), (1, 0, 0, 1), (2, 0, 0, 1)])
    # 33: X's 1 in the first row's second column, Y's in the second row's first, negated - a quarter turn about Z.
    assert part_voxels._rotation(33).tolist() == [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]
    assert part_voxels._rotation(4).tolist() == numpy.eye(3, dtype=int).tolist()
    scene = (
        trn(0, 1, {"_r": "33"})
        # A group of the rod, a shape of a model the file does not have, and a node it does not have.
        + chunk(b"nGRP", struct.pack("<i", 1) + dictionary({}) + struct.pack("<iiii", 3, 2, 3, 7))
        + chunk(b"nSHP", struct.pack("<i", 2) + dictionary({}) + struct.pack("<ii", 1, 0) + dictionary({}))
        + chunk(b"nSHP", struct.pack("<i", 3) + dictionary({}) + struct.pack("<ii", 1, 5) + dictionary({}))
    )
    path = write(tmp_path / "turned.vox", vox([rod], scene))
    grid = part_voxels.read(path, {})
    # Along Y now, and drawn in PartCAD's palette: the file carries none.
    assert grid.labels.shape == (1, 3, 1) and grid.colours is None and grid.what == "MagicaVoxel, 1 model"
    shape = built(part_voxels.run({"path": path, "parameters": {"size": "10, 10, 10"}}))
    assert box(shape) == pytest.approx((-5.0, -15.0, 0.0, 5.0, 15.0, 10.0))


def test_a_magicavoxel_file_with_no_scene_is_its_models_where_they_are(tmp_path):
    # Each about its middle: the first's voxel one along each axis from it, the second's two either side of it.
    path = write(tmp_path / "loose.vox", vox([((3, 3, 3), [(2, 2, 2, 3)]), ((2, 1, 1), [(0, 0, 0, 4), (1, 0, 0, 4)])]))
    grid = part_voxels.read(path, {})
    assert grid.what == "MagicaVoxel, 2 models" and grid.corner == (-1.0, 0.0, 0.0)
    assert grid.labels.shape == (3, 2, 2) and grid.labels[2, 1, 1] == 3 and grid.labels[:2, 0, 0].tolist() == [4, 4]
    # A scene that places only what the file does not hold places nothing.
    nowhere = trn(0, 1, {}) + chunk(
        b"nSHP", struct.pack("<i", 1) + dictionary({}) + struct.pack("<ii", 1, 4) + dictionary({})
    )
    said = part_voxels.run(
        {"path": write(tmp_path / "nowhere.vox", vox([((1, 1, 1), [(0, 0, 0, 1)])], nowhere)), "parameters": {}}
    )
    refused(said, "places no model it holds")


def test_a_voxel_file_that_is_not_one_is_said_to_be_wrong(tmp_path):
    for name, content, said in (
        ("a.vox", b"VOXX", "not a MagicaVoxel file"),
        ("b.vox", b"VOX " + struct.pack("<i", 150) + chunk(b"PACK", struct.pack("<i", 1)), "no MAIN chunk"),
        (
            "c.vox",
            b"VOX " + struct.pack("<i", 150) + chunk(b"MAIN", b"", chunk(b"SIZE", struct.pack("<iii", 1, 1, 1))),
            "holds no model",
        ),
        ("a.binvox", b"#vox\n", "not a binvox file"),
        ("b.binvox", b"#binvox 1\ndim 2 2 2\n", "no 'data'"),
        ("c.binvox", b"#binvox 1\n\ntranslate 0 0 0\ndata\n" + bytes([1, 8]), "says no 'dim'"),
        ("d.binvox", b"#binvox 1\ndim 2 2 2\ndata\n" + bytes([1, 7]), "is 7 voxels, and says it is 2 x 2 x 2"),
        ("e.obj", b"o mesh\n", "none of them"),
    ):
        refused(part_voxels.run({"path": write(tmp_path / name, content), "parameters": {}}), said, name)


def test_a_binvox_part_is_its_voxels_at_the_size_its_scale_makes_them(tmp_path):
    path = write(tmp_path / "full.binvox", b"#binvox 1\ndim 2 2 2\ntranslate 0 0 0\nscale 4\ndata\n" + bytes([1, 8]))
    shape = built(part_voxels.run({"path": path, "parameters": {}}))
    assert volume(shape) == pytest.approx(64.0)


def test_an_array_of_three_dimensions_or_one_more_of_one_value_is_voxels(tmp_path):
    density = numpy.zeros((2, 2, 2, 1))
    density[0, 0, 0, 0] = 0.7
    density[1, 1, 1, 0] = 0.2
    numpy.save(tmp_path / "density.npy", density)
    grid = part_voxels.read(str(tmp_path / "density.npy"), {})
    # Floats with no threshold are filled at a half.
    assert grid.labels.sum() == 1 and grid.what == "array, filled at 0.5 and above"
    numpy.save(tmp_path / "flat.npy", numpy.ones((2, 2)))
    refused(part_voxels.run({"path": str(tmp_path / "flat.npy"), "parameters": {}}), "2-dimensional array")


def test_a_voxel_part_stands_where_the_file_has_it_and_says_what_it_does_not_take(tmp_path):
    block = numpy.zeros((4, 4, 4), bool)
    block[1:3, 2:4, 3] = True
    numpy.save(tmp_path / "block.npy", block)
    path = str(tmp_path / "block.npy")
    shape = built(part_voxels.run({"path": path, "parameters": {"origin": "file", "size": 10}}))
    assert box(shape) == pytest.approx((10.0, 20.0, 30.0, 30.0, 40.0, 40.0))
    refused(part_voxels.run({"path": path, "parameters": {"up": "x"}}), "'up' is 'z' or 'y', not 'x'")
    refused(part_voxels.run({"path": path, "parameters": {"size": "0 1 1"}}), "larger than nothing")
    refused(part_voxels.run({"path": path, "parameters": {"maxBoxes": "0"}}), "more than 0", "maxBoxes")


def test_voxel_solids_say_what_they_cannot_be_made_of():
    with pytest.raises(ValueError, match="2 dimensions"):
        voxel_solid.boxes(numpy.ones((2, 2)))
    with pytest.raises(ValueError, match="not one filled voxel"):
        voxel_solid.solids(numpy.zeros((2, 2, 2)), 1.0)
    with pytest.raises(ValueError, match="larger than nothing"):
        voxel_solid.solids(numpy.ones((1, 1, 1)), (1.0, 0.0, 1.0))
    # A face of no label - one OCCT made of two - is stated as nothing.
    stated = voxel_solid.cmf([1, 2], [1, None, 2], {1: (255, 0, 0, 255)})
    assert stated["faces"][1] is None and stated["solids"][1]["color"] == "2"


# -- Each type, as its wrapper runs it ---------------------------------------------------------------------------


def test_each_script_answers_the_request_its_wrapper_hands_it(tmp_path, monkeypatch):
    """'wrapper_part_type' runs a script as '__partcad_part__', with 'request' in its globals, and reads 'output'."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    numpy.save(tmp_path / "plane.npy", numpy.ones((3, 3)))
    numpy.save(tmp_path / "cube.npy", numpy.ones((2, 2, 2), bool))
    write(tmp_path / "points.xyz", "0 0 0\n1 0 0\n0 1 1\n")
    path = str(tmp_path / "dem.tif")
    rasterio(monkeypatch, {path: utm(numpy.arange(12, dtype="float32").reshape(3, 4))})
    for script, name in (
        ("part_heightmap.py", "plane.npy"),
        ("part_voxels.py", "cube.npy"),
        ("part_pointcloud.py", "points.xyz"),
        ("part_dem.py", "dem.tif"),
    ):
        request = {"path": str(tmp_path / name), "parameters": {}}
        answered = runpy.run_path(
            os.path.join(BUILTIN_IMPORT, script), init_globals={"request": request}, run_name="__partcad_part__"
        )
        built(answered["output"])


# -- Files a package says not to keep ----------------------------------------------------------------------------


def test_a_file_already_gone_when_the_process_exits_is_no_error(tmp_path, monkeypatch):
    from partcad import file_factory_plugin

    kept = tmp_path / "place.npy"
    kept.write_bytes(b"heights")
    monkeypatch.setattr(file_factory_plugin, "_FORGOTTEN", {str(kept), str(tmp_path / "removed.npy")})
    file_factory_plugin._remove_forgotten()
    assert not kept.exists() and file_factory_plugin._FORGOTTEN == set()


def test_an_answer_of_a_package_whose_plugin_cannot_be_found_is_not_kept(monkeypatch):
    import asyncio

    import partcad as pc
    from partcad.project_external_repository import ProjectExternalRepository

    ctx = pc.Context("examples")
    repo = ProjectExternalRepository(ctx, "//ext", "/tmp/ext")

    def missing():
        raise RuntimeError("no plugin serves //ext")

    monkeypatch.setattr(repo, "_cache", object())
    monkeypatch.setattr(repo, "_cached_async", lambda key: asyncio.sleep(0))
    monkeypatch.setattr(repo, "_get_repository", missing)
    assert asyncio.run(repo._persists_async(repo._scope("objects/part/place"), fetch=True)) is False
    assert asyncio.run(repo._persists_async(repo._scope("meta"), fetch=True)) is True
