#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`landscape.py`, the helper the `gen-landscape` skill ships beside its `SKILL.md`.

What an agent cannot check for itself is whether a number the helper hands it is
right: a height a few centimetres off still looks like a height, and an object
stood on it sinks into the ground or floats above it. So the arithmetic is held
to answers worked out by hand - a B-spline reproduces a plane exactly when its
poles stand at the Greville abscissae, which is the property the whole helper is
built on - and the script it writes is built with OCCT and measured against the
helper's own evaluation of the surface.

Nothing here touches the network: the services are replaced by what they would
have answered. It is loaded from the skills library rather than imported, as
`test_skill_measure.py` loads `measure.py`, and without writing bytecode.
"""

import importlib.util
import json
import math
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

HELPER = Path(__file__).resolve().parents[3] / "ai-agents" / "common" / "skills" / "gen-landscape" / "landscape.py"


@pytest.fixture(scope="module")
def landscape():
    spec = importlib.util.spec_from_file_location("landscape", HELPER)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def planar_surface(landscape, nu=8, nv=6, extent=(-50000.0, -30000.0, 50000.0, 30000.0), plane=(0.05, -0.02, 1000.0)):
    """The data of a surface whose poles lie on the plane z = a x + b y + c."""
    x0, y0, x1, y1 = extent
    a, b, c = plane
    xs = [x0 + g * (x1 - x0) for g in landscape.greville(nu)]
    ys = [y0 + g * (y1 - y0) for g in landscape.greville(nv)]
    return {"extent": list(extent), "degree": 3, "poles": [[a * x + b * y + c for y in ys] for x in xs]}


# -- The surface -------------------------------------------------------------------------------------------------


def test_the_basis_is_a_partition_of_unity_and_reproduces_a_line(landscape):
    """Linear precision: with the poles at the Greville abscissae, X is linear in u."""
    for count in (4, 5, 9, 67):
        poles = landscape.greville(count)
        assert poles[0] == 0.0 and poles[-1] == 1.0
        for k in range(101):
            u = k / 100.0
            span, values = landscape.basis(u, count)
            assert sum(values) == pytest.approx(1.0, abs=1e-12)
            assert sum(v * poles[span - 3 + i] for i, v in enumerate(values)) == pytest.approx(u, abs=1e-12)


def test_the_knots_are_what_occt_is_given(landscape):
    knots, multiplicities = landscape.distinct_knots(7)
    assert knots == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert multiplicities == [4, 1, 1, 1, 4]
    assert len(landscape.knot_vector(7)) == 7 + 3 + 1


def test_a_surface_on_a_plane_is_the_plane(landscape):
    """Poles on a plane give that plane, at every point and not only at the poles."""
    surface = landscape.Surface(planar_surface(landscape))
    for x, y in [(-50000, -30000), (50000, 30000), (0, 0), (1234.5, -6789.0), (49999.9, 12.3)]:
        assert surface.height(x, y) == pytest.approx(0.05 * x - 0.02 * y + 1000.0, abs=1e-6)


def test_place_stands_a_footprint_on_its_highest_point(landscape):
    """On ground rising 50 mm a metre towards +X, a 2 m wide footprint stands on its +X edge."""
    surface = landscape.Surface(planar_surface(landscape, plane=(0.05, 0.0, 1000.0)))
    z, fall = landscape.rest(surface, 0.0, 0.0, (2000.0, 1000.0), 0.0)
    assert z == pytest.approx(1050.0)
    assert fall == pytest.approx(100.0)
    # Turned a quarter, the footprint's long side runs along Y and the rise across it is 0.5 m.
    z, fall = landscape.rest(surface, 0.0, 0.0, (2000.0, 1000.0), 90.0)
    assert z == pytest.approx(1025.0)
    assert fall == pytest.approx(50.0)


# -- The frame ---------------------------------------------------------------------------------------------------


def test_the_frame_measures_the_earth(landscape):
    """A degree of latitude at the equator is 110 574 m, and of longitude 111 320 m (WGS84)."""
    frame = landscape.Frame(0.0, 0.0)
    assert frame.local(1.0, 0.0)[1] == pytest.approx(110574.0, rel=1e-3)
    assert frame.local(0.0, 1.0)[0] == pytest.approx(111320.0, rel=1e-3)
    frame = landscape.Frame(37.8, -122.4)
    for x, y in [(0.0, 0.0), (1500.0, -2500.0), (-2499.0, 2499.0)]:
        lat, lon = frame.geo(x, y)
        back = frame.local(lat, lon)
        assert back[0] == pytest.approx(x, abs=1e-6) and back[1] == pytest.approx(y, abs=1e-6)


# -- The elevation tiles -----------------------------------------------------------------------------------------


def png(rows, channels=3, filters=(0, 1, 2, 3, 4)):
    """An 8-bit PNG of 'rows' of pixel tuples, each scan line filtered the next way in 'filters'."""

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    width = len(rows[0])
    raw, previous = b"", bytes(width * channels)
    for index, row in enumerate(rows):
        line = bytes(v for pixel in row for v in pixel)
        kind = filters[index % len(filters)]
        out = bytearray()
        for i, value in enumerate(line):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            predictor = (0, left, up, (left + up) >> 1, paeth(left, up, corner))[kind]
            out.append((value - predictor) & 0xFF)
        raw += bytes([kind]) + bytes(out)
        previous = line

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, len(rows), 8, 2 if channels == 3 else 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_a_png_is_read_through_every_filter(landscape):
    rows = [[((x * 37 + y * 11) % 256, (x * y) % 256, (255 - x * 3) % 256) for x in range(9)] for y in range(10)]
    width, height, channels, read = landscape.png_rgb(png(rows))
    assert (width, height, channels) == (9, 10, 3)
    assert [[tuple(line[i * 3 : i * 3 + 3]) for i in range(9)] for line in read] == rows
    rgba = [[(x, y, 7, 255) for x in range(5)] for y in range(4)]
    _, _, channels, read = landscape.png_rgb(png(rgba, channels=4))
    assert channels == 4 and tuple(read[3][16:20]) == (4, 3, 7, 255)


def test_terrarium_heights_are_decoded_and_interpolated(landscape, monkeypatch, tmp_path):
    """(R * 256 + G + B / 256) - 32768: (128, 0, 0) is sea level, (128, 100, 128) is 100.5 m."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    tile = [[(128, 100 if x >= 128 else 0, 128 if x >= 128 else 0) for x in range(256)] for y in range(256)]
    asked = []

    def fake_http(url, data=None, attempts=4, what=None):
        asked.append(url)
        return png(tile, filters=(1,))

    monkeypatch.setattr(landscape, "http", fake_http)
    terrarium = landscape.Terrarium(1)
    assert terrarium.at_pixel(10, 10) == 0.0
    assert terrarium.at_pixel(200, 10) == 100.5
    # Between the centres of pixel 127 (0 m) and pixel 128 (100.5 m), a quarter of the way.
    assert terrarium.height(*_latlon_of_pixel(1, 127.75, 64.5)) == pytest.approx(25.125, abs=1e-6)
    # A tile is fetched once, and kept: a second reader of the same zoom reads the cache.
    assert len(asked) == 1
    landscape.Terrarium(1).at_pixel(10, 10)
    assert len(asked) == 1


def _latlon_of_pixel(zoom, px, py):
    scale = 256 * 2**zoom
    lon = px / scale * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / scale))))
    return lat, lon


# -- The map -----------------------------------------------------------------------------------------------------


def test_lines_and_polygons_are_cut_to_the_area(landscape):
    rect = (-10.0, -10.0, 10.0, 10.0)
    # In, out and back in again: two runs.
    runs = landscape.clip_line([(-5.0, 0.0), (20.0, 0.0), (20.0, 5.0), (0.0, 5.0)], rect)
    assert [[tuple(p) for p in run] for run in runs] == [[(-5.0, 0.0), (10.0, 0.0)], [(10.0, 5.0), (0.0, 5.0)]]
    square = landscape.clip_polygon([(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)], rect)
    assert abs(landscape.area(square)) == pytest.approx(100.0)
    assert landscape.clip_polygon([(30.0, 30.0), (40.0, 30.0), (40.0, 40.0)], rect) == []


def overpass_answer(frame):
    """What Overpass answers for a small area: one of each kind of thing the helper reads."""

    def node(x, y, **tags):
        lat, lon = frame.geo(x, y)
        return {"lat": lat, "lon": lon, "tags": tags}

    def way(identifier, points, closed=False, **tags):
        geometry = [{"lat": frame.geo(x, y)[0], "lon": frame.geo(x, y)[1]} for x, y in points]
        nodes = list(range(len(points)))
        if closed:
            geometry.append(geometry[0])
            nodes.append(0)
        return {"type": "way", "id": identifier, "nodes": nodes, "geometry": geometry, "tags": tags}

    return {
        "elements": [
            dict(node(10.0, 20.0, natural="tree", height="12 m"), type="node", id=1),
            dict(node(-30.0, 5.0, highway="stop"), type="node", id=2),
            dict(node(500.0, 5.0, natural="tree"), type="node", id=3),  # outside the area
            dict(node(0.0, 0.0, amenity="bench"), type="node", id=4),
            dict(node(30.0, 20.0, amenity="waste_basket"), type="node", id=5),  # inside building 13
            way(10, [(-200.0, -40.0), (200.0, -40.0)], highway="residential", lanes="2"),
            way(11, [(-200.0, 40.0), (200.0, 40.0)], highway="footway"),
            way(12, [(-50.0, -50.0), (-50.0, 50.0)], highway="primary", tunnel="yes"),
            way(13, [(20.0, 10.0), (40.0, 10.0), (40.0, 30.0), (20.0, 30.0)], closed=True, building="yes"),
            way(
                14,
                [(-80.0, 60.0), (-60.0, 60.0), (-60.0, 80.0), (-80.0, 80.0)],
                closed=True,
                building="house",
                height="9",
            ),
            way(15, [(60.0, -90.0), (60.0, 90.0)], barrier="fence"),
            way(16, [(-90.0, -90.0), (-70.0, -90.0), (-70.0, -70.0), (-90.0, -70.0)], closed=True, natural="water"),
        ]
    }


def test_the_map_is_read_into_the_frame(landscape):
    frame = landscape.Frame(47.0, 8.0)
    found = landscape.features(overpass_answer(frame), frame, (-100.0, -100.0, 100.0, 100.0))
    points = {p["kind"]: p for p in found["points"]}
    assert sorted(points) == ["bench", "bin", "sign", "tree"]
    assert points["tree"]["height"] == 12.0
    assert points["tree"]["x"] == pytest.approx(10.0, abs=1e-6) and points["tree"]["y"] == pytest.approx(20.0, abs=1e-6)
    lines = {line["kind"]: line for line in found["lines"]}
    assert sorted(lines) == ["fence", "path", "road"]  # the tunnel is under the ground: left out
    assert lines["road"]["width"] == pytest.approx(6.5)  # two lanes of 3.25 m
    assert lines["road"]["points"][0][0] == pytest.approx(-100.0) and lines["road"]["points"][-1][0] == pytest.approx(
        100.0
    )
    assert lines["path"]["width"] == 2.0 and lines["path"]["layer"] == "paths"
    assert lines["fence"]["thickness"] == 1.2 and lines["fence"]["layer"] == "fences"
    buildings = sorted((a for a in found["areas"] if a["kind"] == "building"), key=lambda a: a["height"])
    assert [b["height"] for b in buildings] == [6.0, 9.0]  # no height or levels: two storeys of 3 m
    assert sum(1 for a in found["areas"] if a["kind"] == "water") == 1


# -- The package -------------------------------------------------------------------------------------------------


def site_json(landscape, tmp_path, plane=(0.002, 0.001, 1000.0)):
    frame = landscape.Frame(47.0, 8.0)
    found = landscape.features(overpass_answer(frame), frame, (-100.0, -100.0, 100.0, 100.0))
    surface = planar_surface(landscape, nu=10, nv=10, extent=(-100000.0, -100000.0, 100000.0, 100000.0), plane=plane)
    site = {
        "landscape": 1,
        "query": {"center": [47.0, 8.0], "size": [200.0, 200.0]},
        "origin": {"lat": 47.0, "lon": 8.0},
        "surface": dict(surface, base=1000.0, exaggeration=1.0, lowest=400.0, highest=408.0, elevation={"dem": "flat"}),
        "features": landscape.scaled(found, 1000.0),
        "sources": [landscape.ATTRIBUTION["osm"]],
        "fetched": "2026-11-13",
    }
    path = tmp_path / "site.json"
    path.write_text(json.dumps(site))
    return path


def package_args(site, out, **extra):
    values = dict(
        site=str(site),
        output=str(out),
        look=None,
        no_looks=False,
        all_looks=False,
        force=False,
        scatter=None,
        clear=10000.0,
        seed=1,
        max_trees=300,
        site_dir=None,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def test_a_package_is_written_only_where_a_package_finds_it(landscape, tmp_path):
    site = site_json(landscape, tmp_path)
    with pytest.raises(SystemExit, match="no partcad.yaml"):
        landscape.package(package_args(site, tmp_path / "place"))


def test_the_package_places_every_prop_on_the_ground(landscape, tmp_path):
    (tmp_path / "partcad.yaml").write_text("name: //\n")
    site = site_json(landscape, tmp_path)
    out = tmp_path / "place"
    landscape.package(package_args(site, out, scatter=["boulder=3"]))
    assert sorted(p.name for p in out.iterdir()) == ["ground.py", "landscape.assy", "partcad.yaml", "site.json"]

    declared = yaml.safe_load((out / "partcad.yaml").read_text())
    assert declared["manufacturable"] is False
    assert set(declared["parts"]) == {"ground", "bench", "boulder", "sign", "tree", "tree-look"}
    ground = declared["parts"]["ground"]
    assert ground["path"] == "ground.py" and ground["parameters"]["layer"]["default"] == "all"
    assert ground["parameters"]["layer"]["enum"] == ["all", "terrain", "water", "roads", "paths", "buildings", "fences"]
    assert declared["parts"]["tree"]["visual"] == "tree-look"
    look = declared["parts"]["tree-look"]
    assert look["source"] == landscape.PROPS["tree"]["look"]["part"] and look["private"] is True
    assert look["scale"] == "%height / 20.513%"
    # Not openly licensed: drawn only under --all-looks.
    assert "cone-look" not in declared["parts"] and "bollard-look" not in declared["parts"]
    assert declared["scenes"]["landscape"]["path"] == "landscape.assy"
    assert any("OpenStreetMap" in line for line in declared["docs"]["usage"].splitlines())

    data = json.loads(site.read_text())
    surface = landscape.Surface(data["surface"])
    cover = landscape.Cover(data["features"])
    links = yaml.safe_load((out / "landscape.assy").read_text())["links"]
    # The ground is one link: its layers touch along its surface, and nothing is learnt checking them.
    assert links[0] == {"part": "ground", "name": "ground", "fixed": True}
    props = [link for link in links if link["part"] in landscape.PROPS]
    assert len(props) == len(links) - 1
    assert sorted(link["name"] for link in props) == [
        "bench-1",
        "boulder-1",
        "boulder-2",
        "boulder-3",
        "sign-1",
        "tree-1",
    ]
    for link in props:
        (x, y, z), axis, heading = link["location"]
        footprint = landscape.footprint_of(link["part"], link["params"]["height"])
        expected, _ = landscape.rest(surface, x, y, footprint, heading, cover)
        # Stood a millimetre clear: a boolean can take two solids touching along a face for one inside the other.
        assert z == pytest.approx(expected + landscape.CLEARANCE, abs=0.1), link["name"]
        assert link["fixed"] is True
    # The bin the map has inside a building is left out: the list above has none.
    tree = next(link for link in props if link["part"] == "tree")
    assert tree["params"]["height"] == 12000
    # A sign faces the nearest road - not the footway, nearer still: the road runs along X at y = -40 m, so -Y
    # turned towards it is -Y itself.
    sign = next(link for link in props if link["part"] == "sign")
    assert sign["location"][2] % 360.0 == pytest.approx(0.0, abs=1e-6)


# -- The ground, built ------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ocp():
    return pytest.importorskip("OCP")


def run_ground(path, layer):
    source = path.read_text().replace('layer = "all"', "layer = %r" % layer, 1)
    painted = []
    scope = {"set_cmf": lambda shape, color=None: painted.append(color), "painted": painted}
    exec(compile(source, str(path), "exec"), scope)
    return scope


def test_the_ground_occt_builds_is_the_surface_the_helper_evaluates(landscape, ocp, tmp_path):
    """A curved ground, built by the generated script: valid, standing on z = 0, and at the helper's heights."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer

    (tmp_path / "partcad.yaml").write_text("name: //\n")
    site = site_json(landscape, tmp_path)
    data = json.loads(site.read_text())
    # A hill in the middle, so that the surface is not a plane any more.
    extent = data["surface"]["extent"]
    poles = data["surface"]["poles"]
    count = len(poles)
    for i in range(count):
        for j in range(count):
            poles[i][j] += 3000.0 * math.exp(-((i - count / 2) ** 2 + (j - count / 2) ** 2) / 8.0)
    site.write_text(json.dumps(data))
    out = tmp_path / "place"
    landscape.package(package_args(site, out, no_looks=True))
    surface = landscape.Surface(data["surface"])

    scope = run_ground(out / "ground.py", "terrain")
    assert BRepCheck_Analyzer(scope["result"]).IsValid()
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(scope["result"], box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    assert (xmin, ymin, zmin) == pytest.approx((extent[0], extent[1], 0.0), abs=0.01)
    assert (xmax, ymax) == pytest.approx((extent[2], extent[3]), abs=0.01)

    occt = scope["surface"](0.0)
    for u, v in [(0.0, 0.0), (0.5, 0.5), (0.13, 0.71), (1.0, 0.4)]:
        point = occt.Value(u, v)
        assert point.Z() == pytest.approx(surface.height(point.X(), point.Y()), abs=1e-6)

    for layer in ("roads", "paths", "fences", "water", "buildings"):
        built = run_ground(out / "ground.py", layer)
        assert BRepCheck_Analyzer(built["result"]).IsValid(), layer
        assert built["painted"] == [built["PAINT"][layer]]

    # The part as a scene places it: one solid, every face of it painted as its layer.
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    whole = run_ground(out / "ground.py", "all")
    assert BRepCheck_Analyzer(whole["result"]).IsValid()
    solids = TopExp_Explorer(whole["result"], TopAbs_SOLID)
    count = 0
    while solids.More():
        count += 1
        solids.Next()
    assert count == 1
    faces = TopExp_Explorer(whole["result"], TopAbs_FACE)
    count = 0
    while faces.More():
        count += 1
        faces.Next()
    assert len(whole["painted"]) == count
    assert set(whole["painted"]) == {":asphalt", ":building", ":fence", ":gravel", ":ground", ":water"}


def test_place_stands_an_object_on_what_covers_the_ground(landscape, tmp_path, capsys):
    """On the road, on its asphalt; in a building, said to be in it."""
    (tmp_path / "partcad.yaml").write_text("name: //\n")
    site = site_json(landscape, tmp_path)
    surface = landscape.Surface(json.loads(site.read_text())["surface"])
    landscape.place(SimpleNamespace(site=str(site), x=0.0, y=-40000.0, footprint=[0.0, 0.0], heading=0.0))
    said = capsys.readouterr().out
    z = float(said.split("[[")[1].split("]")[0].split(",")[2])
    assert z == pytest.approx(surface.height(0.0, -40000.0) + 100.0 + landscape.CLEARANCE, abs=0.1)
    assert "on a road, a path or water, 100 mm thick" in said
    landscape.place(SimpleNamespace(site=str(site), x=30000.0, y=20000.0, footprint=[1000.0, 1000.0], heading=0.0))
    assert "it is in: building - move it" in capsys.readouterr().out
