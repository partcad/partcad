#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a place in Google Earth is, read with the user's own Google Maps Platform key.

The plugin ('google_earth_repo.py') serves a place as parts; this is how each is
made, with nothing of PartCAD in it and every request through one function, so
that it is tested without the network:

  * the ground: Google's Elevation API sampled on a grid over the place -
    'elevation_grid';
  * what stands on it: Google's Photorealistic 3D Tiles - the mesh Google Earth
    draws, buildings and trees included - gathered over the place
    ('tile_meshes'), and made either a mesh in the place's frame ('write_glb')
    or a surface model, the highest point of the mesh over each cell of a grid
    ('rasterize');
  * where a name is: Google's Geocoding API ('geocode').

The frame is the one every landscape in PartCAD is in: metres east and north
of the place's middle on the tangent plane there (a 'Frame'), and heights above
the ellipsoid, made relative by whoever builds the part.

The key is the user's, and so is the agreement with Google its use is under:
nothing here keeps what it reads anywhere but in what it returns.
"""

import base64
import json
import math
import struct
import urllib.parse

ELEVATION_API = "https://maps.googleapis.com/maps/api/elevation/json"
GEOCODING_API = "https://maps.googleapis.com/maps/api/geocode/json"
TILES_ROOT = "https://tile.googleapis.com/v1/3dtiles/root.json"

# What the Elevation API takes in one request: 512 locations, and a URL of at
# most 16 384 characters, which an encoded polyline of 400 points fits in.
ELEVATION_BATCH = 400

# The most tiles one place is gathered from: a place of a few hundred metres
# takes tens of them at a metre's error, and a mistake in the traversal should
# cost a bounded bill.
MAX_TILES = 600

A = 6378137.0
E2 = 6.69437999014e-3


class EarthError(Exception):
    """What Google answered that is not the data, in words for the user."""


# -- Geodesy -----------------------------------------------------------------------------------------------------


def to_ecef(lat, lon, height=0.0):
    """Earth-centred, Earth-fixed metres of a latitude, longitude and height above the ellipsoid."""
    phi, lam = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1.0 - E2 * math.sin(phi) ** 2)
    return (
        (n + height) * math.cos(phi) * math.cos(lam),
        (n + height) * math.cos(phi) * math.sin(lam),
        (n * (1.0 - E2) + height) * math.sin(phi),
    )


class Frame:
    """The place's frame: metres east, north and up of its middle, on the tangent plane there."""

    def __init__(self, lat, lon):
        self.lat, self.lon = float(lat), float(lon)
        phi, lam = math.radians(self.lat), math.radians(self.lon)
        self.origin = to_ecef(self.lat, self.lon)
        self.east = (-math.sin(lam), math.cos(lam), 0.0)
        self.north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
        self.up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
        s = math.sin(phi)
        w = math.sqrt(1.0 - E2 * s * s)
        self.m = A * (1.0 - E2) / (w * w * w)
        self.n = A / w

    def geo(self, x, y):
        """(lat, lon) of a point of the frame, in metres (the tangent plane, right to centimetres over kilometres)."""
        return (
            self.lat + math.degrees(y / self.m),
            self.lon + math.degrees(x / (self.n * math.cos(math.radians(self.lat)))),
        )

    def local(self, points):
        """Earth-centred points (n x 3, metres) in the frame: east, north, up."""
        import numpy

        d = numpy.asarray(points, dtype=float) - numpy.asarray(self.origin)
        return numpy.stack(
            [d @ numpy.asarray(self.east), d @ numpy.asarray(self.north), d @ numpy.asarray(self.up)], axis=-1
        )


def earth_url(lat, lon, size):
    """A Google Earth link to the place, seen from above at a distance that shows it whole."""
    return "https://earth.google.com/web/@%.6f,%.6f,0a,%dd,35y,0h,0t,0r" % (lat, lon, int(max(size) * 2.5))


# -- Requests ----------------------------------------------------------------------------------------------------


def _json(http, url, what):
    try:
        answer = json.loads(http(url))
    except ValueError:
        raise EarthError("%s: Google did not answer with JSON" % what)
    if not isinstance(answer, dict):
        raise EarthError("%s: Google answered with something that is not an object" % what)
    return answer


def _checked(answer, what):
    """The answer of a Maps web service, or its error in Google's own words."""
    status = answer.get("status")
    if status not in (None, "OK", "ZERO_RESULTS"):
        said = answer.get("error_message") or ""
        hint = {
            "REQUEST_DENIED": "the key is not valid, or the API is not enabled for its project",
            "OVER_DAILY_LIMIT": "the key's project has no billing, or its quota is spent",
            "OVER_QUERY_LIMIT": "too many requests: try again shortly",
        }.get(status, "")
        raise EarthError("%s: %s%s%s" % (what, status, ": " + said if said else "", " (%s)" % hint if hint else ""))
    return answer


def encode_polyline(points):
    """Google's encoded polyline of [(lat, lon)]: what a long list of locations is sent as."""
    out, last = [], (0, 0)
    for lat, lon in points:
        here = (int(round(lat * 1e5)), int(round(lon * 1e5)))
        for value in (here[0] - last[0], here[1] - last[1]):
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last = here
    return "".join(out)


def elevations(points, key, http):
    """Heights (metres above mean sea level) of [(lat, lon)] from the Elevation API, in order."""
    heights = []
    for start in range(0, len(points), ELEVATION_BATCH):
        chunk = points[start : start + ELEVATION_BATCH]
        url = ELEVATION_API + "?" + urllib.parse.urlencode({"locations": "enc:" + encode_polyline(chunk), "key": key})
        answer = _checked(_json(http, url, "elevation"), "elevation")
        results = answer.get("results") or []
        if len(results) != len(chunk):
            raise EarthError("elevation: asked for %d heights and Google answered %d" % (len(chunk), len(results)))
        heights.extend(float(result["elevation"]) for result in results)
    return heights


def elevation_grid(lat, lon, size, samples, key, http):
    """'(heights, cell)': the ground over the place, rows north first, each from west to east; cell in metres.

    'size' is the place's (width, depth) in metres; 'samples' the heights along
    its longer side. Each height is at the middle of its cell.
    """
    import numpy

    width, depth = float(size[0]), float(size[1])
    cell = max(width, depth) / float(samples)
    nx, ny = max(2, int(round(width / cell))), max(2, int(round(depth / cell)))
    frame = Frame(lat, lon)
    points = []
    for row in range(ny):
        y = depth / 2.0 - (row + 0.5) * (depth / ny)
        for column in range(nx):
            x = -width / 2.0 + (column + 0.5) * (width / nx)
            points.append(frame.geo(x, y))
    heights = numpy.array(elevations(points, key, http), dtype=float).reshape(ny, nx)
    return heights, (width / nx, depth / ny)


def geocode(text, key, http):
    """[(name, lat, lon)] Google's Geocoding API finds for 'text', best first."""
    url = GEOCODING_API + "?" + urllib.parse.urlencode({"address": text, "key": key})
    answer = _checked(_json(http, url, "geocoding"), "geocoding")
    found = []
    for result in answer.get("results") or []:
        where = (result.get("geometry") or {}).get("location") or {}
        if "lat" in where and "lng" in where:
            found.append((result.get("formatted_address") or text, float(where["lat"]), float(where["lng"])))
    return found


# -- Photorealistic 3D Tiles -------------------------------------------------------------------------------------


def _matrix(values):
    """A 3D Tiles 'transform' (16 numbers, column-major) as a 4 x 4 row-major array."""
    import numpy

    return numpy.asarray(values, dtype=float).reshape(4, 4).T


def _sphere(volume, transform):
    """'(centre, radius)' around a tile's bounding volume, in Earth-centred metres."""
    import numpy

    if "box" in volume:
        box = numpy.asarray(volume["box"], dtype=float)
        centre = transform @ numpy.append(box[:3], 1.0)
        axes = box[3:].reshape(3, 3) @ transform[:3, :3].T
        return centre[:3], float(numpy.sqrt((axes**2).sum(axis=1)).sum())
    if "sphere" in volume:
        sphere = volume["sphere"]
        centre = transform @ numpy.append(numpy.asarray(sphere[:3], dtype=float), 1.0)
        return centre[:3], float(sphere[3]) * float(numpy.abs(transform[:3, :3]).max())
    if "region" in volume:
        west, south, east, north, low, high = (float(v) for v in volume["region"])
        lat, lon = math.degrees((south + north) / 2.0), math.degrees((west + east) / 2.0)
        centre = numpy.asarray(to_ecef(lat, lon, (low + high) / 2.0))
        corner = numpy.asarray(to_ecef(math.degrees(south), math.degrees(west), low))
        return centre, float(numpy.linalg.norm(centre - corner)) + (high - low)
    raise EarthError("a tile has a bounding volume of no kind 3D Tiles defines")


def _with_key(url, key, session):
    """'url' with the key, and the session the root handed out, in its query."""
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query["key"] = key
    if session and "session" not in query:
        query["session"] = session
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def tile_meshes(lat, lon, radius, max_error, key, http, max_tiles=MAX_TILES):
    """[(positions, triangles)] of the 3D tiles over a place: Earth-centred metres, and vertex indices.

    Walks the tileset from its root, into every tile whose bounding volume
    reaches within 'radius' metres of the place's middle, down to the tiles
    whose geometric error is at most 'max_error' metres (or that have no
    children), and reads their content: a nested tileset is walked on, a glTF
    read (see 'glb_meshes'). Google refines by replacement, so a tile's own
    content is read only where it is not refined further.
    """
    import numpy

    frame = Frame(lat, lon)
    centre = numpy.asarray(frame.origin)
    meshes, session = [], [None]
    seen = [0]

    def fetch(url):
        seen[0] += 1
        if seen[0] > max_tiles:
            raise EarthError(
                "the place takes more than %d tiles at an error of %s m: make it smaller or the error larger"
                % (max_tiles, max_error)
            )
        return http(_with_key(url, key, session[0]))

    def walk(tile, base, parent):
        transform = parent @ _matrix(tile["transform"]) if "transform" in tile else parent
        middle, reach = _sphere(tile.get("boundingVolume") or {}, transform)
        if float(numpy.linalg.norm(middle - centre)) > reach + radius:
            return
        children = tile.get("children") or []
        refine = float(tile.get("geometricError", 0.0)) > max_error and children
        if refine:
            for child in children:
                walk(child, base, transform)
            return
        content = tile.get("content") or {}
        uri = content.get("uri") or content.get("url")
        if uri:
            read(urllib.parse.urljoin(base, uri), transform)
        for child in children if not refine and not uri else []:
            walk(child, base, transform)

    def read(url, transform):
        path = urllib.parse.urlsplit(url).path
        if session[0] is None:
            session[0] = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("session")
        data = fetch(url)
        if path.endswith(".json"):
            tileset = json.loads(data)
            walk(tileset["root"], url, transform)
        elif path.endswith(".glb"):
            for positions, triangles in glb_meshes(data):
                # glTF is Y-up; a tile's content is turned Z-up before its transform (3D Tiles 1.0, section 6).
                z_up = numpy.stack([positions[:, 0], -positions[:, 2], positions[:, 1]], axis=-1)
                world = numpy.c_[z_up, numpy.ones(len(z_up))] @ transform.T
                meshes.append((world[:, :3], triangles))

    root = json.loads(http(_with_key(TILES_ROOT, key, None)))
    if not isinstance(root, dict) or "root" not in root:
        raise EarthError("tiles: Google's answer is not a tileset: %s" % (str(root)[:200]))
    walk(root["root"], TILES_ROOT, numpy.eye(4))
    return meshes


def glb_meshes(data):
    """[(positions, triangles)] of every triangle primitive a binary glTF draws, through its nodes' transforms.

    Positions in the glTF's own frame (metres, Y up); a primitive compressed with
    Draco (KHR_draco_mesh_compression, which Google's tiles are) is decoded with
    DracoPy, which the plugin's sandbox installs.
    """
    import numpy

    magic, _version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise EarthError("a tile's content is not a binary glTF")
    offset, document, binary = 12, None, b""
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<I4s", data, offset)
        chunk = data[offset + 8 : offset + 8 + length]
        if kind == b"JSON":
            document = json.loads(chunk)
        elif kind == b"BIN\x00":
            binary = chunk
        offset += 8 + length
    if document is None:
        raise EarthError("a tile's glTF has no JSON chunk")

    def view(index):
        bv = document["bufferViews"][index]
        start = bv.get("byteOffset", 0)
        return binary[start : start + bv["byteLength"]]

    def accessor(index):
        acc = document["accessors"][index]
        kinds = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
        dtype = numpy.dtype("<" + kinds[acc["componentType"]])
        raw = view(acc["bufferView"])[acc.get("byteOffset", 0) :]
        stride = document["bufferViews"][acc["bufferView"]].get("byteStride") or dtype.itemsize * width
        rows = numpy.ndarray((acc["count"], width), dtype=dtype, buffer=raw, strides=(stride, dtype.itemsize))
        return numpy.array(rows, dtype=float)

    def primitive_mesh(primitive):
        if primitive.get("mode", 4) != 4:
            return None
        draco = (primitive.get("extensions") or {}).get("KHR_draco_mesh_compression")
        if draco is not None:
            import DracoPy

            decoded = DracoPy.decode(bytes(view(draco["bufferView"])))
            positions = numpy.asarray(decoded.points, dtype=float).reshape(-1, 3)
            triangles = numpy.asarray(decoded.faces, dtype=numpy.int64).reshape(-1, 3)
            return positions, triangles
        positions = accessor(primitive["attributes"]["POSITION"])
        if "indices" in primitive:
            triangles = accessor(primitive["indices"]).astype(numpy.int64).reshape(-1, 3)
        else:
            triangles = numpy.arange(len(positions), dtype=numpy.int64).reshape(-1, 3)
        return positions, triangles

    def local(node):
        if "matrix" in node:
            return _matrix(node["matrix"])
        matrix = numpy.eye(4)
        x, y, z, w = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
        rotation = numpy.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )
        matrix[:3, :3] = rotation * numpy.asarray(node.get("scale", (1.0, 1.0, 1.0)))
        matrix[:3, 3] = node.get("translation", (0.0, 0.0, 0.0))
        return matrix

    found = []

    def visit(index, parent):
        node = document["nodes"][index]
        transform = parent @ local(node)
        if "mesh" in node:
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                mesh = primitive_mesh(primitive)
                if mesh is not None:
                    positions, triangles = mesh
                    placed = numpy.c_[positions, numpy.ones(len(positions))] @ transform.T
                    found.append((placed[:, :3], triangles))
        for child in node.get("children") or []:
            visit(child, transform)

    scene = document.get("scenes", [{}])[document.get("scene", 0)] if document.get("scenes") else None
    roots = scene.get("nodes", []) if scene else range(len(document.get("nodes") or []))
    for index in roots:
        visit(index, numpy.eye(4))
    return found


def in_frame(meshes, frame):
    """'(positions, triangles)': every mesh in the place's frame (metres), as one."""
    import numpy

    positions, triangles, offset = [], [], 0
    for points, faces in meshes:
        positions.append(frame.local(points))
        triangles.append(faces + offset)
        offset += len(points)
    if not positions:
        return numpy.zeros((0, 3)), numpy.zeros((0, 3), dtype=numpy.int64)
    return numpy.concatenate(positions), numpy.concatenate(triangles)


def clipped(positions, triangles, size):
    """The triangles whose plan reaches over the place's rectangle, and the positions they use, renumbered.

    By their bounding boxes: a triangle larger than the place, every corner of
    it outside, is still over it.
    """
    import numpy

    half = numpy.asarray(size, dtype=float) / 2.0
    corners = positions[triangles][..., :2]
    low, high = corners.min(axis=1), corners.max(axis=1)
    keep = ((low <= half) & (high >= -half)).all(axis=1)
    kept = triangles[keep]
    used = numpy.unique(kept)
    renumber = numpy.full(len(positions), -1, dtype=numpy.int64)
    renumber[used] = numpy.arange(len(used))
    return positions[used], renumber[kept]


def rasterize(positions, triangles, size, cell):
    """The surface model of a mesh: over each cell of the place, the highest point of the mesh, NaN where none.

    Rows north first, each from west to east, as 'elevation_grid' gives them.
    Each triangle is sampled at the middles of the cells its plan covers, at
    the height of its plane there.
    """
    import numpy

    width, depth = float(size[0]), float(size[1])
    nx, ny = max(2, int(round(width / cell))), max(2, int(round(depth / cell)))
    dx, dy = width / nx, depth / ny
    top = numpy.full((ny, nx), -numpy.inf)
    corners = positions[triangles]
    for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in corners:
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            continue
        low_x, high_x = min(ax, bx, cx), max(ax, bx, cx)
        low_y, high_y = min(ay, by, cy), max(ay, by, cy)
        c0 = max(0, int(math.floor((low_x + width / 2.0) / dx - 0.5)) + 1)
        c1 = min(nx - 1, int(math.floor((high_x + width / 2.0) / dx - 0.5)))
        r0 = max(0, int(math.floor((depth / 2.0 - high_y) / dy - 0.5)) + 1)
        r1 = min(ny - 1, int(math.floor((depth / 2.0 - low_y) / dy - 0.5)))
        if c0 > c1 or r0 > r1:
            continue
        xs = -width / 2.0 + (numpy.arange(c0, c1 + 1) + 0.5) * dx
        ys = depth / 2.0 - (numpy.arange(r0, r1 + 1) + 0.5) * dy
        gx, gy = numpy.meshgrid(xs, ys)
        l1 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / det
        l2 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        if not inside.any():
            continue
        z = l1 * az + l2 * bz + l3 * cz
        block = top[r0 : r1 + 1, c0 : c1 + 1]
        top[r0 : r1 + 1, c0 : c1 + 1] = numpy.where(inside, numpy.maximum(block, z), block)
    top[~numpy.isfinite(top)] = numpy.nan
    return top


def write_glb(positions, triangles):
    """A binary glTF of one mesh: positions in the place's frame (metres, Z up) written Y-up, as glTF is."""
    import numpy

    y_up = numpy.stack([positions[:, 0], positions[:, 2], -positions[:, 1]], axis=-1).astype("<f4")
    indices = numpy.asarray(triangles, dtype="<u4").reshape(-1)
    vertex_bytes, index_bytes = y_up.tobytes(), indices.tobytes()
    binary = vertex_bytes + index_bytes
    binary += b"\x00" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0", "generator": "partcad-repo-google-earth"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vertex_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vertex_bytes), "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(y_up),
                "type": "VEC3",
                "min": [float(v) for v in y_up.min(axis=0)] if len(y_up) else [0.0, 0.0, 0.0],
                "max": [float(v) for v in y_up.max(axis=0)] if len(y_up) else [0.0, 0.0, 0.0],
            },
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
    }
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def npy(array):
    """The bytes of a NumPy '.npy' file of 'array', as float32."""
    import io

    import numpy

    out = io.BytesIO()
    numpy.save(out, numpy.asarray(array, dtype="<f4"), allow_pickle=False)
    return out.getvalue()


def b64(data):
    return base64.b64encode(data).decode("ascii")
