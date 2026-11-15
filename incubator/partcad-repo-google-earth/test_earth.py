#
# partcad-repo-google-earth, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of how a place is read from Google, with Google answered by the tests.

Every request goes through the 'http' function a caller hands in, so these
answer it: the Elevation API with a slope whose every height says where it was
asked, the 3D tiles with a tileset made here - a root, a nested tileset, a tile
far away that must not be fetched - whose content is a glTF made here too.
Nothing here touches the network. The answers have the shapes Google's
documentation gives them; the values are made up.
"""

import json
import math
import struct
import urllib.parse

import earth
import numpy
import pytest

LAT, LON = 38.7083, -77.0863


def decode_polyline(text):
    """Google's documented decoding of an encoded polyline, written apart from the encoder under test."""
    points, index, lat, lon = [], 0, 0, 0
    while index < len(text):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(text[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / 1e5, lon / 1e5))
    return points


def test_a_polyline_is_encoded_as_google_documents_it():
    # The example of Google's "Encoded Polyline Algorithm Format" page.
    assert earth.encode_polyline([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_the_frame_is_metres_east_north_and_up():
    frame = earth.Frame(LAT, LON)
    for x, y in [(0.0, 0.0), (150.0, 0.0), (0.0, -150.0), (120.0, 80.0)]:
        lat, lon = frame.geo(x, y)
        here = frame.local([earth.to_ecef(lat, lon, 0.0)])[0]
        assert here[:2] == pytest.approx([x, y], abs=0.01)
        # The tangent plane leaves the ellipsoid by the square of the distance over twice the radius.
        assert here[2] == pytest.approx(-(x * x + y * y) / (2 * 6.37e6), abs=0.01)
    above = frame.local([earth.to_ecef(LAT, LON, 25.0)])[0]
    assert above == pytest.approx([0.0, 0.0, 25.0], abs=1e-6)


class Elevation:
    """The Elevation API over a slope: a height in centimetres per metre north and east of the place."""

    def __init__(self):
        self.asked = []
        self.frame = earth.Frame(LAT, LON)

    def height(self, lat, lon):
        return 100.0 + (lat - LAT) * 1e5 + (lon - LON) * 1e3

    def __call__(self, url):
        parts = urllib.parse.urlsplit(url)
        assert parts.scheme + "://" + parts.netloc + parts.path == earth.ELEVATION_API
        query = dict(urllib.parse.parse_qsl(parts.query))
        assert query["key"] == "the-key"
        assert len(url) < 16384
        points = decode_polyline(query["locations"][len("enc:") :])
        self.asked.append(len(points))
        results = [{"elevation": self.height(lat, lon), "location": {"lat": lat, "lng": lon}} for lat, lon in points]
        return json.dumps({"results": results, "status": "OK"}).encode()


def test_the_ground_is_sampled_north_first_in_batches():
    google = Elevation()
    heights, cell = earth.elevation_grid(LAT, LON, (300.0, 200.0), 30, "the-key", google)
    assert heights.shape == (20, 30)
    assert cell == pytest.approx((10.0, 10.0))
    assert sum(google.asked) == 600 and max(google.asked) <= earth.ELEVATION_BATCH
    # Row 0 is the north edge; each row runs west to east.
    assert heights[0, 0] > heights[-1, 0]
    assert heights[0, -1] > heights[0, 0]
    # Each height is the middle of its cell, at five decimal places of a degree.
    frame = google.frame
    lat, lon = frame.geo(-150.0 + 5.0, 100.0 - 5.0)
    assert heights[0, 0] == pytest.approx(google.height(round(lat, 5), round(lon, 5)), abs=1e-6)


@pytest.mark.parametrize(
    "status, words",
    [("REQUEST_DENIED", "not valid"), ("OVER_DAILY_LIMIT", "billing"), ("INVALID_REQUEST", "INVALID_REQUEST")],
)
def test_what_google_refuses_is_said_in_its_words(status, words):
    def google(url):
        return json.dumps({"results": [], "status": status, "error_message": "Google says no."}).encode()

    with pytest.raises(earth.EarthError) as e:
        earth.elevations([(LAT, LON)], "the-key", google)
    assert words in str(e.value) and "Google says no." in str(e.value)


def test_a_name_is_geocoded():
    def google(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        assert query == {"address": "Mount Vernon, Virginia", "key": "the-key"}
        found = {"formatted_address": "Mount Vernon, VA 22121, USA", "geometry": {"location": {"lat": LAT, "lng": LON}}}
        return json.dumps({"results": [found], "status": "OK"}).encode()

    assert earth.geocode("Mount Vernon, Virginia", "the-key", google) == [("Mount Vernon, VA 22121, USA", LAT, LON)]


# -- 3D tiles ------------------------------------------------------------------------------------------------------


def enu_to_ecef(lat, lon):
    """The 3D Tiles 'transform' (column-major) taking the place's frame - metres east, north, up - to the Earth's."""
    frame = earth.Frame(lat, lon)
    matrix = numpy.eye(4)
    matrix[:3, 0], matrix[:3, 1], matrix[:3, 2] = frame.east, frame.north, frame.up
    matrix[:3, 3] = frame.origin
    return [float(v) for v in matrix.T.reshape(-1)]


def glb(positions_y_up, triangles, draco=False):
    """A binary glTF of one mesh, written apart from 'earth.write_glb': plain, or compressed with Draco."""
    positions = numpy.asarray(positions_y_up, dtype="<f4")
    indices = numpy.asarray(triangles, dtype="<u4").reshape(-1)
    primitive = {"attributes": {"POSITION": 0}, "indices": 1}
    if draco:
        import DracoPy

        blob = DracoPy.encode(positions, numpy.asarray(triangles, dtype=numpy.uint32))
        binary = bytes(blob)
        views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}]
        primitive["extensions"] = {"KHR_draco_mesh_compression": {"bufferView": 0, "attributes": {"POSITION": 0}}}
        accessors = [
            {"componentType": 5126, "count": len(positions), "type": "VEC3"},
            {"componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ]
    else:
        binary = positions.tobytes() + indices.tobytes()
        views = [
            {"buffer": 0, "byteOffset": 0, "byteLength": positions.nbytes},
            {"buffer": 0, "byteOffset": positions.nbytes, "byteLength": indices.nbytes},
        ]
        accessors = [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3"},
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ]
    binary += b"\x00" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        # A node moving its mesh, as Google's do: what is read has to be where the node puts it.
        "nodes": [{"children": [1], "translation": [0.0, 2.0, 0.0]}, {"mesh": 0}],
        "meshes": [{"primitives": [primitive]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


# A square 40 m a side around the place, sloping up to the east, in glTF's frame (Y up, Z towards the viewer -
# south): (east, up, -north). Two metres below what the node lifts it to.
SQUARE = [(-20.0, -2.0, 20.0), (20.0, 2.0, 20.0), (20.0, 2.0, -20.0), (-20.0, -2.0, -20.0)]
TRIANGLES = [(0, 1, 2), (0, 2, 3)]


class Tiles:
    """Google's 3D tiles over the place: a root, a nested tileset under it, and a tile on the far side of the Earth."""

    def __init__(self, draco=False):
        self.fetched = []
        self.content = glb(SQUARE, TRIANGLES, draco=draco)

    def __call__(self, url):
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        assert query["key"] == "the-key"
        self.fetched.append(parts.path)
        if parts.path == "/v1/3dtiles/root.json":
            assert "session" not in query
            return json.dumps(
                {
                    "asset": {"version": "1.0"},
                    "geometricError": 10000,
                    "root": {
                        "boundingVolume": {"sphere": list(earth.to_ecef(LAT, LON)) + [7e6]},
                        "geometricError": 5000,
                        "refine": "REPLACE",
                        "children": [
                            {
                                "boundingVolume": {"sphere": list(earth.to_ecef(LAT, LON)) + [500.0]},
                                "geometricError": 50,
                                "content": {"uri": "/v1/3dtiles/datasets/A/files/near.json?session=S1"},
                            },
                            {
                                "boundingVolume": {"sphere": list(earth.to_ecef(-LAT, LON + 180.0)) + [500.0]},
                                "geometricError": 50,
                                "content": {"uri": "/v1/3dtiles/datasets/A/files/far.json?session=S1"},
                            },
                        ],
                    },
                }
            ).encode()
        assert query.get("session") == "S1"
        if parts.path.endswith("near.json"):
            return json.dumps(
                {
                    "asset": {"version": "1.0"},
                    "geometricError": 50,
                    "root": {
                        # In the tile's own frame: its 'transform' takes its bounding volume as it takes its content.
                        "boundingVolume": {"sphere": [0.0, 0.0, 0.0, 500.0]},
                        "geometricError": 50,
                        "transform": enu_to_ecef(LAT, LON),
                        # A coarser tile of its own, replaced by its child at a finer error.
                        "content": {"uri": "coarse.glb"},
                        "children": [
                            {
                                "boundingVolume": {"box": [0, 0, 0, 30, 0, 0, 0, 30, 0, 0, 0, 10]},
                                "geometricError": 0.5,
                                "content": {"uri": "fine.glb"},
                            }
                        ],
                    },
                }
            ).encode()
        if parts.path.endswith("fine.glb"):
            return self.content
        raise AssertionError("fetched what it did not need: %s" % parts.path)


def test_the_tiles_over_a_place_are_read_in_its_frame():
    google = Tiles()
    meshes = earth.tile_meshes(LAT, LON, 30.0, 1.0, "the-key", google)
    assert [path.rsplit("/", 1)[-1] for path in google.fetched] == ["root.json", "near.json", "fine.glb"]
    positions, triangles = earth.in_frame(meshes, earth.Frame(LAT, LON))
    assert triangles.tolist() == [list(t) for t in TRIANGLES]
    # glTF (east, up, -north), lifted 2 m by its node: the square at the place, sloping up to the east.
    expected = [-20, -20, 0, 20, -20, 4, 20, 20, 4, -20, 20, 0]
    assert positions.reshape(-1).tolist() == pytest.approx(expected, abs=1e-6)


def test_a_coarser_error_stops_sooner():
    google = Tiles()
    with pytest.raises(AssertionError, match="coarse.glb"):
        earth.tile_meshes(LAT, LON, 30.0, 100.0, "the-key", google)


def test_a_bounded_number_of_tiles_is_fetched():
    # The root is not counted: the nested tileset is the one tile allowed, and its content is one too many.
    with pytest.raises(earth.EarthError, match="more than 1 tiles"):
        earth.tile_meshes(LAT, LON, 30.0, 1.0, "the-key", Tiles(), max_tiles=1)


def test_draco_compressed_tiles_are_decoded():
    pytest.importorskip("DracoPy")
    meshes = earth.tile_meshes(LAT, LON, 30.0, 1.0, "the-key", Tiles(draco=True))
    positions, triangles = earth.in_frame(meshes, earth.Frame(LAT, LON))
    # Draco quantizes positions (to 14 bits of the mesh's extent, by default): a few millimetres here.
    corners = sorted({tuple(float(v) for v in numpy.round(p, 1)) for p in positions[triangles.reshape(-1)]})
    assert corners == sorted({(-20.0, -20.0, 0.0), (20.0, -20.0, 4.0), (20.0, 20.0, 4.0), (-20.0, 20.0, 0.0)})


def test_a_mesh_is_written_as_the_gltf_partcad_reads():
    positions = numpy.array([[-20.0, -20.0, 0.0], [20.0, -20.0, 4.0], [20.0, 20.0, 4.0], [-20.0, 20.0, 0.0]])
    data = earth.write_glb(positions, numpy.array(TRIANGLES))
    ((read, triangles),) = earth.glb_meshes(data)
    # Written Y up, as glTF is - and turned back exactly as PartCAD's glTF reader turns it.
    to_partcad = numpy.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    assert (read @ to_partcad.T).reshape(-1).tolist() == pytest.approx(positions.reshape(-1).tolist())
    assert triangles.tolist() == [list(t) for t in TRIANGLES]


def test_a_mesh_is_clipped_to_the_place():
    positions = numpy.array(
        [
            [0, 0, 0],
            [5, 0, 0],
            [0, 5, 0],
            [100, 100, 0],
            [105, 100, 0],
            [100, 105, 0],
            [-50, -50, 0],
            [50, -50, 0],
            [0, 80, 0],
        ],
        dtype=float,
    )
    kept, triangles = earth.clipped(positions, numpy.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]]), (20.0, 20.0))
    # The small one inside, and the large one over the whole place with every corner outside it; not the far one.
    assert kept.tolist() == positions[[0, 1, 2, 6, 7, 8]].tolist() and triangles.tolist() == [[0, 1, 2], [3, 4, 5]]


def test_the_surface_model_is_the_highest_of_the_mesh_over_each_cell():
    # The sloping square, and a roof 3 m above part of it.
    positions = numpy.array(
        [[-20, -20, 0], [20, -20, 4], [20, 20, 4], [-20, 20, 0], [0, 0, 8], [10, 0, 8], [10, 10, 8], [0, 10, 8]],
        dtype=float,
    )
    triangles = numpy.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
    top = earth.rasterize(positions, triangles, (60.0, 40.0), 2.0)
    assert top.shape == (20, 30)

    def at(x, y):
        return top[int((20.0 - y) // 2.0), int((x + 30.0) // 2.0)]

    assert at(-11.0, -15.0) == pytest.approx(0.1 * (-11.0 + 20.0))
    assert at(5.0, 5.0) == pytest.approx(8.0)
    assert at(15.0, 15.0) == pytest.approx(0.1 * (15.0 + 20.0))
    # Beyond the square, nothing: the part type fills it from its nearest.
    assert math.isnan(at(25.0, 0.0))


def test_an_array_is_written_as_the_npy_the_heightmap_reads(tmp_path):
    path = tmp_path / "heights.npy"
    path.write_bytes(earth.npy([[1.0, 2.0], [3.0, float("nan")]]))
    read = numpy.load(str(path), allow_pickle=False)
    assert read.dtype == numpy.float32 and read[0].tolist() == [1.0, 2.0] and math.isnan(read[1, 1])
