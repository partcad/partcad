#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Make a landscape: a piece of the real world as a PartCAD package, to test objects in.

Shipped beside the `gen-landscape` skill's `SKILL.md`, which says when to run it.
It needs Python 3.9 or newer and nothing else: no GDAL, no numpy, no PartCAD.

    python landscape.py fetch (--address TEXT | --center LAT,LON | --corners LAT,LON LAT,LON)
                              [--size W[xD]] [--cells N] [--base MM] [--exaggeration K]
                              [--dem terrarium | opentopodata:<dataset> | flat]
                              [--no-osm] [--overpass URL] [-o site.json]
    python landscape.py package <site.json> [-o DIR] [--name NAME] [--look KIND=PART]... [--no-looks]
                                [--scatter KIND=N]... [--clear R] [--seed N] [--max-trees N]
    python landscape.py height <site.json> X Y [X Y]...
    python landscape.py place <site.json> X Y [--footprint W,D] [--heading DEG]
    python landscape.py props

`fetch` asks three public services what is at a place on Earth, and writes the
answer down as one JSON file, `site.json`:

  * where: an address is geocoded with Nominatim (OpenStreetMap's geocoder;
    one request, under its usage policy); two corners or a centre need nothing;
  * the ground: a digital elevation model, sampled into a smooth surface. By
    default the AWS Terrain Tiles ("Terrarium" PNGs: SRTM, 3DEP, EU-DEM and
    others merged by Mapzen), which need no key; `opentopodata:<dataset>`
    asks api.opentopodata.org instead (`ned10m`, `eudem25m`, `srtm30m`,
    `aster30m`, ...: 1 request a second, 1000 a day); `flat` asks nothing;
  * what stands on it: roads and paths, buildings with their heights, fences,
    walls and hedges, water, and single trees, signs, street lamps, benches,
    bollards, bins, hydrants and rocks, from OpenStreetMap through the Overpass
    API, unless `--no-osm`.

Everything is converted into one local frame, the one a PartCAD scene is in:
millimetres, X east, Y north, Z up, the origin at the centre of the area, and
the ground's lowest point `--base` (1000 mm) above z = 0, so the bottom of the
landscape is the plane z = 0 a simulator's ground plane is in. Latitude and
longitude go into that frame on the tangent plane at the centre, which over a
few kilometres is right to centimetres, and the heights stay heights: what a
model says the elevation is, minus its lowest, times `--exaggeration`.

The ground is a cubic B-spline surface with its poles on a regular grid -- at
the Greville abscissae of its knots, which makes X and Y linear in the
surface's parameters -- each pole the elevation model's height there. That is
one smooth face, which a STEP file, a hidden-line drawing and a boolean all
take as it is, and it is evaluated *here* exactly as OCCT evaluates it, so that
`height` and `place` answer with the height of the ground the scene stands on,
not of the elevation model it was made from.

`package` turns a `site.json` into a PartCAD package of its own: a directory
with a `partcad.yaml`, one build123d script (`ground.py`, its data written into
it) for `ground` - the terrain and everything lying or standing on it, roads,
paths, water, fences, walls, hedges and buildings, as one solid painted layer by
layer - and one scene, `landscape`, placing the ground and one `basic` part per
tree, sign, lamp, ... where the map has one. A prop is the solid a check and a
simulation see (a tree is its trunk), drawn through a `visual:` that is a
model from the public `//pub` collections, scaled to the size the prop is
(`props` lists them; `--look tree=//pub/...` names another, `--no-looks` draws
the props as what they are). `--scatter boulder=20` adds props where the map
has none, clear of roads, buildings, water and the middle of the area.

`height` answers with the height of the ground (z, in mm) at points of the
frame, and `place` with the `location:` that stands an object with a
footprint of W x D mm, turned by DEG, on the ground at X, Y: on the highest
point under it of the ground or the road, path or water covering it, so that
nothing of it is in either, and says when it reaches into a building, a fence,
a wall or a hedge.

Nothing here stores anything from Google: Google's terms forbid keeping or
deriving models from Google Earth, its 3D tiles or its Elevation API, so a
landscape made from them could not be committed to a package.
"""

import argparse
import json
import math
import os
import random
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

# Who is asking, as Nominatim and Overpass require an application to say.
USER_AGENT = "partcad-landscape/1 (+https://github.com/partcad/partcad)"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
OPENTOPODATA = "https://api.opentopodata.org/v1/{dataset}"
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

# WGS84.
A = 6378137.0
E2 = 6.69437999014e-3

# The degree of the ground's surface in both directions.
DEGREE = 3

# The largest area asked for, in metres along a side: past it, the tangent
# plane drifts from the ground by more than a few centimetres, and the props a
# map has are too many to be one scene.
MAX_SIDE = 5000.0

# The most elevation tiles one area may need (each is 256 x 256 heights).
MAX_TILES = 64

ATTRIBUTION = {
    "osm": {
        "name": "OpenStreetMap",
        "attribution": "© OpenStreetMap contributors, under the Open Database License (ODbL)",
        "url": "https://www.openstreetmap.org/copyright",
    },
    "nominatim": {
        "name": "Nominatim",
        "attribution": "Geocoding by Nominatim, © OpenStreetMap contributors (ODbL)",
        "url": "https://operations.osmfoundation.org/policies/nominatim/",
    },
    "terrarium": {
        "name": "AWS Terrain Tiles (Terrarium)",
        "attribution": (
            "Elevation from the AWS Terrain Tiles (Mapzen): SRTM, GMTED, ETOPO1 and NED/3DEP courtesy of the "
            "U.S. Geological Survey; EU-DEM produced using Copernicus data and information funded by the European "
            "Union; and the other sources listed at the URL"
        ),
        "url": "https://github.com/tilezen/joerd/blob/master/docs/attribution.md",
    },
    "opentopodata": {
        "name": "Open Topo Data",
        "attribution": "Elevation from api.opentopodata.org, dataset '{dataset}', under that dataset's own terms",
        "url": "https://www.opentopodata.org/#public-api",
    },
}


# -- Geodesy -----------------------------------------------------------------------------------------------------


class Frame:
    """The local frame: metres east and north of an origin, on the tangent plane there."""

    def __init__(self, lat, lon):
        self.lat, self.lon = float(lat), float(lon)
        phi = math.radians(self.lat)
        s = math.sin(phi)
        w = math.sqrt(1.0 - E2 * s * s)
        # The radii of curvature along the meridian and across it.
        self.m = A * (1.0 - E2) / (w * w * w)
        self.n = A / w
        self.cos = math.cos(phi)

    def local(self, lat, lon):
        """(x, y) in metres of a latitude and longitude."""
        return (
            math.radians(float(lon) - self.lon) * self.n * self.cos,
            math.radians(float(lat) - self.lat) * self.m,
        )

    def geo(self, x, y):
        """(lat, lon) of a point of the frame, in metres."""
        return (
            self.lat + math.degrees(float(y) / self.m),
            self.lon + math.degrees(float(x) / (self.n * self.cos)),
        )


# -- The ground's surface ----------------------------------------------------------------------------------------


def knot_vector(count, degree=DEGREE):
    """The clamped uniform knot vector of 'count' poles, flattened, on [0, 1]."""
    spans = count - degree
    return [0.0] * (degree + 1) + [k / spans for k in range(1, spans)] + [1.0] * (degree + 1)


def greville(count, degree=DEGREE):
    """Where each pole stands along [0, 1]: the mean of the 'degree' knots after it.

    With the poles there, a B-spline reproduces a straight line exactly, so the
    surface's X and Y are linear in its parameters and a height is found at a
    point of the plan without solving for anything.
    """
    knots = knot_vector(count, degree)
    return [sum(knots[i + 1 : i + degree + 1]) / degree for i in range(count)]


def distinct_knots(count, degree=DEGREE):
    """(knots, multiplicities): the knot vector the way OCCT is given one."""
    spans = count - degree
    return [k / spans for k in range(spans + 1)], [degree + 1] + [1] * (spans - 1) + [degree + 1]


def basis(u, count, degree=DEGREE):
    """(span, [N_span-degree .. N_span](u)): the B-spline basis functions not nought at 'u'.

    The NURBS Book's A2.1 and A2.2.
    """
    knots = knot_vector(count, degree)
    u = min(max(u, 0.0), 1.0)
    if u >= knots[count]:
        span = count - 1
    else:
        low, high = degree, count
        span = (low + high) // 2
        while u < knots[span] or u >= knots[span + 1]:
            if u < knots[span]:
                high = span
            else:
                low = span
            span = (low + high) // 2
    values = [1.0] + [0.0] * degree
    left = [0.0] * (degree + 1)
    right = [0.0] * (degree + 1)
    for j in range(1, degree + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            temp = values[r] / (right[r + 1] + left[j - r])
            values[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        values[j] = saved
    return span, values


class Surface:
    """The ground: z in mm over the rectangle [x0, x1] x [y0, y1], from the poles of a cubic B-spline."""

    def __init__(self, data):
        self.x0, self.y0, self.x1, self.y1 = data["extent"]
        self.poles = data["poles"]  # poles[i][j]: i along X, j along Y
        self.nu = len(self.poles)
        self.nv = len(self.poles[0])

    def height(self, x, y):
        u = (float(x) - self.x0) / (self.x1 - self.x0)
        v = (float(y) - self.y0) / (self.y1 - self.y0)
        su, bu = basis(u, self.nu)
        sv, bv = basis(v, self.nv)
        z = 0.0
        for a in range(DEGREE + 1):
            row = self.poles[su - DEGREE + a]
            z += bu[a] * sum(bv[b] * row[sv - DEGREE + b] for b in range(DEGREE + 1))
        return z

    def inside(self, x, y, margin=0.0):
        return self.x0 + margin <= x <= self.x1 - margin and self.y0 + margin <= y <= self.y1 - margin


# -- HTTP --------------------------------------------------------------------------------------------------------


def cache_dir():
    root = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(root, "partcad", "landscape")


def http(url, data=None, attempts=4, what=None):
    """The body of a GET (or a POST of 'data'), retried on what a busy public server answers."""
    delay = 2.0
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == attempts - 1:
                raise RuntimeError("%s: HTTP %d from %s" % (what or "request", e.code, url.split("?")[0]))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == attempts - 1:
                raise RuntimeError("%s: %s: %s" % (what or "request", url.split("?")[0], e))
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


def geocode(address):
    """(lat, lon, display name) of an address, from Nominatim."""
    query = urllib.parse.urlencode({"q": address, "format": "jsonv2", "limit": 1})
    found = json.loads(http(NOMINATIM + "?" + query, what="geocoding"))
    if not found:
        raise SystemExit("Nominatim found nothing at '%s': name it differently, or give --center LAT,LON" % address)
    return float(found[0]["lat"]), float(found[0]["lon"]), found[0].get("display_name", address)


# -- Elevation ---------------------------------------------------------------------------------------------------


def png_rgb(data):
    """[rows of (r, g, b)] of an 8-bit RGB or RGBA PNG, not interlaced: what a Terrarium tile is."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    position, idat, width, height, channels = 8, b"", 0, 0, 0
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or color not in (2, 6) or interlace:
                raise ValueError("a PNG of depth %d, colour type %d, interlace %d" % (depth, color, interlace))
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, previous, offset = [], bytearray(stride), 0
    for _ in range(height):
        kind = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        if kind == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif kind == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + predictor) & 0xFF
        rows.append(line)
        previous = line
    return width, height, channels, rows


class Terrarium:
    """Heights in metres from the AWS Terrain Tiles, in the Terrarium encoding, at one zoom level."""

    def __init__(self, zoom):
        self.zoom = zoom
        self.tiles = {}

    @staticmethod
    def zoom_for(lat, spacing):
        """The coarsest zoom whose pixels are at most half 'spacing' metres: its data is no finer at 15."""
        for zoom in range(10, 16):
            if 156543.03392 * math.cos(math.radians(lat)) / 2**zoom <= spacing / 2.0:
                return zoom
        return 15

    def pixel(self, lat, lon):
        """Global pixel coordinates of a point at this zoom (Web Mercator)."""
        scale = 256 * 2**self.zoom
        phi = math.radians(lat)
        return (
            (lon + 180.0) / 360.0 * scale,
            (1.0 - math.log(math.tan(phi) + 1.0 / math.cos(phi)) / math.pi) / 2.0 * scale,
        )

    def load(self, tx, ty):
        key = (tx, ty)
        if key in self.tiles:
            return self.tiles[key]
        path = os.path.join(cache_dir(), "terrarium", str(self.zoom), str(tx), "%d.png" % ty)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
        else:
            data = http(TERRARIUM.format(z=self.zoom, x=tx, y=ty), what="elevation tile")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)
        _, _, channels, rows = png_rgb(data)
        heights = [
            [
                row[i * channels] * 256 + row[i * channels + 1] + row[i * channels + 2] / 256.0 - 32768.0
                for i in range(256)
            ]
            for row in rows
        ]
        self.tiles[key] = heights
        return heights

    def at_pixel(self, px, py):
        tx, ty = int(px // 256), int(py // 256)
        return self.load(tx, ty)[int(py) - ty * 256][int(px) - tx * 256]

    def height(self, lat, lon):
        """Bilinear between the centres of the four pixels around the point."""
        px, py = self.pixel(lat, lon)
        px, py = px - 0.5, py - 0.5
        ix, iy = math.floor(px), math.floor(py)
        fx, fy = px - ix, py - iy
        h00, h10 = self.at_pixel(ix, iy), self.at_pixel(ix + 1, iy)
        h01, h11 = self.at_pixel(ix, iy + 1), self.at_pixel(ix + 1, iy + 1)
        return (h00 * (1 - fx) + h10 * fx) * (1 - fy) + (h01 * (1 - fx) + h11 * fx) * fy

    def tiles_for(self, corners):
        xs, ys = zip(*(self.pixel(lat, lon) for lat, lon in corners))
        return (int(max(xs) // 256) - int(min(xs) // 256) + 2) * (int(max(ys) // 256) - int(min(ys) // 256) + 2)


def opentopodata_heights(dataset, points):
    """Heights in metres at [(lat, lon)], 100 a request and one request a second, as the public API asks."""
    heights = []
    for start in range(0, len(points), 100):
        chunk = points[start : start + 100]
        locations = "|".join("%.7f,%.7f" % point for point in chunk)
        url = (
            OPENTOPODATA.format(dataset=urllib.parse.quote(dataset))
            + "?"
            + urllib.parse.urlencode({"locations": locations, "interpolation": "bilinear"})
        )
        answer = json.loads(http(url, what="elevation"))
        if answer.get("status") != "OK":
            raise SystemExit("opentopodata: %s" % answer.get("error", answer))
        for result in answer["results"]:
            if result.get("elevation") is None:
                raise SystemExit("opentopodata: '%s' has no height at %s" % (dataset, result.get("location")))
            heights.append(float(result["elevation"]))
        if start + 100 < len(points):
            time.sleep(1.1)
    return heights


# -- OpenStreetMap -----------------------------------------------------------------------------------------------

OVERPASS_QUERY = """[out:json][timeout:90];
(
  node["natural"~"^(tree|stone|rock)$"]({bbox});
  node["traffic_sign"]({bbox});
  node["highway"~"^(stop|give_way|traffic_signals|street_lamp)$"]({bbox});
  node["amenity"~"^(bench|waste_basket)$"]({bbox});
  node["barrier"="bollard"]({bbox});
  node["emergency"="fire_hydrant"]({bbox});
  way["natural"="tree_row"]({bbox});
  way["highway"]({bbox});
  way["building"]({bbox});
  way["barrier"~"^(fence|wall|hedge|guard_rail|retaining_wall|city_wall)$"]({bbox});
  way["natural"="water"]({bbox});
  way["waterway"~"^(river|stream|canal|ditch|drain)$"]({bbox});
  way["landuse"="forest"]({bbox});
  way["natural"="wood"]({bbox});
);
out geom;
"""

# How wide a road is, in metres, by its class, where it does not say.
ROAD_WIDTH = {
    "motorway": 11.0,
    "trunk": 10.0,
    "primary": 8.0,
    "secondary": 7.0,
    "tertiary": 6.5,
    "unclassified": 5.5,
    "residential": 5.5,
    "living_street": 5.0,
    "service": 3.5,
    "track": 3.0,
    "road": 5.0,
    "motorway_link": 5.0,
    "trunk_link": 5.0,
    "primary_link": 5.0,
    "secondary_link": 5.0,
    "tertiary_link": 5.0,
}
PATH_WIDTH = {
    "footway": 2.0,
    "path": 1.5,
    "cycleway": 2.0,
    "pedestrian": 4.0,
    "steps": 1.5,
    "bridleway": 2.0,
    "corridor": 1.5,
}
# A barrier: (layer, height, width), in metres, where the way does not say.
BARRIERS = {
    "fence": ("fences", 1.2, 0.05),
    "guard_rail": ("fences", 0.8, 0.1),
    "wall": ("walls", 1.5, 0.3),
    "retaining_wall": ("walls", 1.0, 0.4),
    "city_wall": ("walls", 4.0, 1.5),
    "hedge": ("hedges", 1.5, 0.8),
}
WATERWAY_WIDTH = {"river": 10.0, "canal": 8.0, "stream": 2.0, "ditch": 1.0, "drain": 1.0}


def number(value, default=None):
    """A number out of an OSM tag ('7', '7 m', '7.5;8'), or the default."""
    if value is None:
        return default
    text = str(value).split(";")[0].strip().lower().replace(",", ".")
    for unit in ("m", "meters", "metres"):
        if text.endswith(" " + unit) or text.endswith(unit):
            text = text[: -len(unit)].strip()
    try:
        return float(text)
    except ValueError:
        return default


def point_kind(tags):
    natural, highway = tags.get("natural"), tags.get("highway")
    if natural == "tree":
        return "tree"
    if natural in ("stone", "rock"):
        return "boulder"
    if highway == "traffic_signals":
        return "signal"
    if highway == "street_lamp":
        return "lamp"
    if highway in ("stop", "give_way") or "traffic_sign" in tags:
        return "sign"
    if tags.get("amenity") == "bench":
        return "bench"
    if tags.get("amenity") == "waste_basket":
        return "bin"
    if tags.get("barrier") == "bollard":
        return "bollard"
    if tags.get("emergency") == "fire_hydrant":
        return "hydrant"
    return None


def clip_segment(p, q, rect):
    """The part of the segment p-q inside the rectangle, or None (Liang-Barsky)."""
    x0, y0, x1, y1 = rect
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for edge_p, edge_q in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if edge_p == 0:
            if edge_q < 0:
                return None
            continue
        t = edge_q / edge_p
        if edge_p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (p[0] + t0 * dx, p[1] + t0 * dy), (p[0] + t1 * dx, p[1] + t1 * dy)


def clip_line(points, rect):
    """A polyline cut to the rectangle: the runs of it inside, each a polyline of its own."""
    runs, run = [], []
    for p, q in zip(points, points[1:]):
        clipped = clip_segment(p, q, rect)
        if clipped is None:
            if len(run) > 1:
                runs.append(run)
            run = []
            continue
        a, b = clipped
        if run and math.dist(run[-1], a) < 1e-6:
            run.append(b)
        else:
            if len(run) > 1:
                runs.append(run)
            run = [a, b]
        if math.dist(b, q) > 1e-6:
            runs.append(run)
            run = []
    if len(run) > 1:
        runs.append(run)
    return runs


def clip_polygon(points, rect):
    """A polygon cut to the rectangle (Sutherland-Hodgman); its first point is not repeated at the end."""
    x0, y0, x1, y1 = rect
    edges = (
        (lambda p: p[0] >= x0, lambda p, q: (x0, p[1] + (q[1] - p[1]) * (x0 - p[0]) / (q[0] - p[0]))),
        (lambda p: p[0] <= x1, lambda p, q: (x1, p[1] + (q[1] - p[1]) * (x1 - p[0]) / (q[0] - p[0]))),
        (lambda p: p[1] >= y0, lambda p, q: (p[0] + (q[0] - p[0]) * (y0 - p[1]) / (q[1] - p[1]), y0)),
        (lambda p: p[1] <= y1, lambda p, q: (p[0] + (q[0] - p[0]) * (y1 - p[1]) / (q[1] - p[1]), y1)),
    )
    polygon = list(points)
    for inside, cross in edges:
        if not polygon:
            break
        result = []
        for i, q in enumerate(polygon):
            p = polygon[i - 1]
            if inside(q):
                if not inside(p):
                    result.append(cross(p, q))
                result.append(q)
            elif inside(p):
                result.append(cross(p, q))
        polygon = result
    return polygon


def area(polygon):
    return 0.5 * sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(polygon, polygon[1:] + polygon[:1]))


def overpass(bbox, url=None):
    """The Overpass answer for the area: (south, west, north, east) in degrees."""
    query = OVERPASS_QUERY.replace("{bbox}", "%.7f,%.7f,%.7f,%.7f" % bbox)
    errors = []
    for endpoint in [url] if url else OVERPASS:
        try:
            return json.loads(http(endpoint, data=urllib.parse.urlencode({"data": query}).encode(), what="Overpass"))
        except (RuntimeError, ValueError) as e:
            errors.append(str(e))
    raise SystemExit("OpenStreetMap could not be asked: %s. Try --overpass URL, or --no-osm" % "; ".join(errors))


def features(answer, frame, rect):
    """{'points': [...], 'lines': [...], 'areas': [...]} in the frame, in metres, cut to the rectangle."""
    points, lines, areas = [], [], []
    for element in answer.get("elements", []):
        tags = element.get("tags") or {}
        if element["type"] == "node":
            kind = point_kind(tags)
            x, y = frame.local(element["lat"], element["lon"])
            if kind and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                point = {"kind": kind, "x": x, "y": y, "osm": "node/%d" % element["id"]}
                if kind == "tree":
                    point["height"] = number(tags.get("height"))
                    point["leaf"] = tags.get("leaf_type")
                if tags.get("direction") is not None:
                    point["direction"] = number(tags.get("direction"))
                points.append(point)
            continue
        if element["type"] != "way" or not element.get("geometry"):
            continue
        geometry = [frame.local(node["lat"], node["lon"]) for node in element["geometry"] if node]
        if len(geometry) < 2:
            continue
        closed = element.get("nodes") and element["nodes"][0] == element["nodes"][-1] and len(geometry) > 3
        reference = "way/%d" % element["id"]
        if tags.get("tunnel") not in (None, "no") or number(tags.get("layer"), 0) < 0:
            continue
        if "building" in tags and closed:
            outline = clip_polygon(geometry[:-1], rect)
            if len(outline) >= 3 and abs(area(outline)) > 1.0:
                levels = number(tags.get("building:levels"))
                height = number(tags.get("height"), (levels or 2.0) * 3.0 + (1.0 if levels else 0.0))
                areas.append({"kind": "building", "outline": outline, "height": height, "osm": reference})
            continue
        if (tags.get("natural") == "water" or tags.get("landuse") == "reservoir") and closed:
            outline = clip_polygon(geometry[:-1], rect)
            if len(outline) >= 3 and abs(area(outline)) > 1.0:
                areas.append({"kind": "water", "outline": outline, "osm": reference})
            continue
        if (tags.get("landuse") == "forest" or tags.get("natural") == "wood") and closed:
            outline = clip_polygon(geometry[:-1], rect)
            if len(outline) >= 3 and abs(area(outline)) > 1.0:
                areas.append({"kind": "wood", "outline": outline, "leaf": tags.get("leaf_type"), "osm": reference})
            continue
        line = None
        highway, barrier, waterway = tags.get("highway"), tags.get("barrier"), tags.get("waterway")
        if highway in ROAD_WIDTH:
            lanes = number(tags.get("lanes"))
            width = number(tags.get("width"), lanes * 3.25 if lanes else ROAD_WIDTH[highway])
            line = {"kind": "road", "layer": "roads", "width": width, "thickness": 0.1}
        elif highway in PATH_WIDTH:
            line = {"kind": "path", "layer": "paths", "width": number(tags.get("width"), PATH_WIDTH[highway])}
            line["thickness"] = 0.05
        elif barrier in BARRIERS:
            layer, height, width = BARRIERS[barrier]
            line = {"kind": barrier, "layer": layer, "width": number(tags.get("width"), width)}
            line["thickness"] = number(tags.get("height"), height)
        elif waterway in WATERWAY_WIDTH:
            line = {"kind": waterway, "layer": "water", "width": number(tags.get("width"), WATERWAY_WIDTH[waterway])}
            line["thickness"] = 0.05
        elif tags.get("natural") == "tree_row":
            line = {"kind": "tree_row"}
        if line is None:
            continue
        line["osm"] = reference
        if tags.get("bridge") not in (None, "no"):
            line["bridge"] = True
        for run in clip_line(geometry, rect):
            lines.append(dict(line, points=run))
    return {"points": points, "lines": lines, "areas": areas}


# -- fetch -------------------------------------------------------------------------------------------------------


def latlon(text):
    try:
        lat, lon = (float(v) for v in text.replace(" ", "").split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("'%s' is not LAT,LON" % text)
    if not (-85.0 < lat < 85.0 and -180.0 <= lon <= 180.0):
        raise argparse.ArgumentTypeError("'%s' is not a latitude in (-85, 85) and a longitude" % text)
    return lat, lon


def size(text):
    try:
        values = [float(v) for v in text.lower().replace("m", "").split("x")]
    except ValueError:
        raise argparse.ArgumentTypeError("'%s' is not W or WxD in metres" % text)
    if len(values) == 1:
        values *= 2
    if len(values) != 2 or not all(0 < v <= MAX_SIDE for v in values):
        raise argparse.ArgumentTypeError("a side is more than nothing and at most %d m" % MAX_SIDE)
    return values


def fetch(args):
    sources, query = [], {}
    if args.address:
        lat, lon, name = geocode(args.address)
        sources.append(ATTRIBUTION["nominatim"])
        query = {"address": args.address, "found": name}
    elif args.center:
        lat, lon = args.center
        query = {"center": [lat, lon]}
    if args.corners:
        (lat_a, lon_a), (lat_b, lon_b) = args.corners
        lat, lon = (lat_a + lat_b) / 2.0, (lon_a + lon_b) / 2.0
        frame = Frame(lat, lon)
        xa, ya = frame.local(lat_a, lon_a)
        xb, yb = frame.local(lat_b, lon_b)
        width, depth = abs(xb - xa), abs(yb - ya)
        if not (0 < width <= MAX_SIDE and 0 < depth <= MAX_SIDE):
            raise SystemExit("the corners are %.0f x %.0f m apart: a side is at most %d m" % (width, depth, MAX_SIDE))
        query = {"corners": [[lat_a, lon_a], [lat_b, lon_b]]}
    else:
        frame = Frame(lat, lon)
        width, depth = args.size
    query["size"] = [round(width, 3), round(depth, 3)]
    rect = (-width / 2.0, -depth / 2.0, width / 2.0, depth / 2.0)

    # The poles: 'cells' spans along the longer side, the same spacing along
    # the other, and never fewer than the four a cubic needs.
    spacing = max(width, depth) / args.cells
    nu = max(DEGREE + 1, int(round(width / spacing)) + DEGREE)
    nv = max(DEGREE + 1, int(round(depth / spacing)) + DEGREE)
    xs = [rect[0] + g * width for g in greville(nu)]
    ys = [rect[1] + g * depth for g in greville(nv)]

    corners = [frame.geo(x, y) for x in (rect[0], rect[2]) for y in (rect[1], rect[3])]
    print("area: %.0f x %.0f m around %.6f, %.6f; %d x %d poles" % (width, depth, lat, lon, nu, nv), file=sys.stderr)
    if args.dem == "flat":
        elevations = [[0.0] * nv for _ in range(nu)]
        dem = {"dem": "flat"}
    elif args.dem.startswith("opentopodata:"):
        dataset = args.dem.split(":", 1)[1]
        points = [frame.geo(x, y) for x in xs for y in ys]
        heights = opentopodata_heights(dataset, points)
        elevations = [heights[i * nv : (i + 1) * nv] for i in range(nu)]
        attribution = dict(ATTRIBUTION["opentopodata"])
        attribution["attribution"] = attribution["attribution"].format(dataset=dataset)
        sources.append(attribution)
        dem = {"dem": "opentopodata", "dataset": dataset}
    elif args.dem == "terrarium":
        zoom = Terrarium.zoom_for(lat, min(spacing, width, depth))
        terrarium = Terrarium(zoom)
        while zoom > 10 and terrarium.tiles_for(corners) > MAX_TILES:
            zoom -= 1
            terrarium = Terrarium(zoom)
        # Each pole is the mean of nine samples a third of the spacing apart,
        # so a pole stands for the ground around it rather than one pixel.
        step = spacing / 3.0
        elevations = []
        for x in xs:
            column = []
            for y in ys:
                samples = [
                    terrarium.height(*frame.geo(x + dx * step, y + dy * step)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                ]
                column.append(sum(samples) / len(samples))
            elevations.append(column)
        sources.append(ATTRIBUTION["terrarium"])
        dem = {"dem": "terrarium", "zoom": zoom, "tiles": len(terrarium.tiles)}
    else:
        raise SystemExit("--dem is 'terrarium', 'opentopodata:<dataset>' or 'flat', not '%s'" % args.dem)

    lowest = min(min(column) for column in elevations)
    highest = max(max(column) for column in elevations)
    poles = [[round(args.base + (e - lowest) * 1000.0 * args.exaggeration, 1) for e in column] for column in elevations]
    print(
        "ground: %.1f to %.1f m (%s)" % (lowest, highest, ", ".join("%s %s" % kv for kv in dem.items())),
        file=sys.stderr,
    )

    found = {"points": [], "lines": [], "areas": []}
    if not args.no_osm:
        south, west = frame.geo(rect[0], rect[1])
        north, east = frame.geo(rect[2], rect[3])
        found = features(overpass((south, west, north, east), args.overpass), frame, rect)
        sources.append(ATTRIBUTION["osm"])
        counts = {}
        for group in found.values():
            for feature in group:
                counts[feature["kind"]] = counts.get(feature["kind"], 0) + 1
        print(
            "map: %s" % (", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())) or "nothing"), file=sys.stderr
        )

    site = {
        "landscape": 1,
        "query": query,
        "origin": {"lat": round(lat, 8), "lon": round(lon, 8)},
        "frame": "millimetres; X east, Y north, Z up; the origin at the centre of the area, on z = 0",
        "surface": {
            "extent": [round(v * 1000.0, 3) for v in rect],
            "degree": DEGREE,
            "poles": poles,
            "base": args.base,
            "exaggeration": args.exaggeration,
            "lowest": round(lowest, 3),
            "highest": round(highest, 3),
            "elevation": dict(dem, note="z = base + (elevation - lowest) * 1000 * exaggeration, elevation in metres"),
        },
        "features": scaled(found, 1000.0),
        "sources": sources,
        "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(site, f, indent=1)
        f.write("\n")
    print("wrote %s" % args.output, file=sys.stderr)


def scaled(found, factor):
    """The features with every length in metres multiplied by 'factor'."""
    lengths = ("x", "y", "height", "width", "thickness")
    out = {"points": [], "lines": [], "areas": []}
    for group, items in found.items():
        for item in items:
            copy = {}
            for key, value in item.items():
                if key in lengths and isinstance(value, (int, float)):
                    copy[key] = round(value * factor, 1)
                elif key in ("points", "outline"):
                    copy[key] = [[round(p[0] * factor, 1), round(p[1] * factor, 1)] for p in value]
                else:
                    copy[key] = value
            out[group].append(copy)
    return out


# -- Props -------------------------------------------------------------------------------------------------------

# What each kind of prop is. 'height' is its default height in mm; 'body' is
# the solid that stands for it - ('cylinder', radius) or ('box', [x, y]) in mm,
# and None for a box as wide as its look scaled to its height. 'look' is the
# //pub model it is drawn as: its part, its bounding box in its own units
# ([xmin, ymin, zmin, xmax, ymax, zmax], Z up), and what its licence is, which
# a package that draws it inherits; only the openly licensed ones are drawn
# unless --all-looks says otherwise. Each was built with PartCAD and measured.
PROPS = {
    "tree": {
        "desc": "A tree, as its trunk: what a robot runs into. Drawn whole.",
        "height": 10000.0,
        "body": ("cylinder", 200.0),
        "color": "bark",
        "look": {
            "part": "//pub/collection/printables/models:556482",
            "bbox": [-7.2735, -9.9299, -0.3052, 7.1888, 9.8549, 20.2080],
            "license": "CC-BY-SA, 'Low poly tree' on Printables (printables.com/model/556482)",
            "color": "foliage",
            "open": True,
        },
    },
    "boulder": {"desc": "A boulder.", "height": 900.0, "body": ("box", [1400.0, 1100.0]), "color": "stone"},
    "sign": {
        "desc": "A road sign on its post, its face towards -Y.",
        "height": 2600.0,
        "body": ("box", [750.0, 80.0]),
        "color": "sign",
    },
    "signal": {"desc": "A traffic light on its pole.", "height": 3600.0, "body": ("cylinder", 80.0), "color": "metal"},
    "lamp": {"desc": "A street lamp.", "height": 6000.0, "body": ("cylinder", 90.0), "color": "metal"},
    "bench": {
        "desc": "A bench, its front towards -Y.",
        "height": 850.0,
        "body": ("box", [1800.0, 650.0]),
        "color": "wood",
    },
    "bin": {"desc": "A litter bin.", "height": 950.0, "body": ("cylinder", 250.0), "color": "metal"},
    "bollard": {
        "desc": "A bollard.",
        "height": 1000.0,
        "body": ("cylinder", 100.0),
        "color": "metal",
        "look": {
            "part": "//pub/collection/openusd/nvidia/assets/archvis-residential:CircularBollard",
            "bbox": [-53.1947, -53.1885, 1.1929, 53.1947, 53.1885, 497.3394],
            "license": "NVIDIA Omniverse License Agreement, not an open licence: read it before using what is built",
            "open": False,
        },
    },
    "hydrant": {"desc": "A fire hydrant.", "height": 800.0, "body": ("cylinder", 150.0), "color": "signal-red"},
    "cone": {
        "desc": "A traffic cone.",
        "height": 700.0,
        "body": ("cylinder", 180.0),
        "color": "signal-red",
        "look": {
            "part": "//pub/collection/openusd/nvidia/assets/simready:trafficcone_a01",
            "bbox": [-85.0203, -85.0203, 0.0166, 85.0203, 85.0203, 154.7936],
            "license": "NVIDIA Omniverse License Agreement, not an open licence: read it before using what is built",
            "open": False,
        },
    },
}

# What a prop faces, its front (-Y) turned towards the nearest line of these
# layers, unless the map gives its direction: a road sign faces the road.
FACING = {"sign": ("roads",), "signal": ("roads",), "bench": ("roads", "paths")}

# The colours a landscape is drawn in: a picture only, none of them claimed.
COLORS = {
    "ground": ("#8A9A5B", "The ground: grass and soil."),
    "asphalt": ("#4A4A4F", "A road."),
    "gravel": ("#B8A98C", "A path."),
    "building": ("#C9B8A0", "A building."),
    "fence": ("#7A5C3E", "A fence or a guard rail."),
    "masonry": ("#A39E93", "A wall."),
    "hedge": ("#3F6B35", "A hedge."),
    "water": ("#4A7FB0", "Water."),
    "bark": ("#6B4A2F", "A tree's trunk."),
    "foliage": ("#4E7D3A", "A tree's leaves."),
    "stone": ("#8C8A83", "Stone."),
    "sign": ("#D8D8D8", "A sign."),
    "metal": ("#5F6B73", "Painted metal."),
    "wood": ("#9C7A54", "Wood."),
    "signal-red": ("#D2452F", "Signal red."),
}

# The layers draped on the ground, in the order the scene places them: what
# 'ground.py' builds for each, and its colour.
LAYERS = {
    "terrain": ("ground", "The ground: a smooth surface through the elevation model, on a flat base at z = 0."),
    "water": ("water", "Water: lakes, ponds, rivers and streams, a thin skin on the ground."),
    "roads": ("asphalt", "The roads, 100 mm of asphalt on the ground."),
    "paths": ("gravel", "The footpaths and cycle paths, 50 mm on the ground."),
    "buildings": ("building", "The buildings, standing on the ground to their roof height, as blocks."),
    "fences": ("fence", "The fences and guard rails, standing on the ground along their line."),
    "walls": ("masonry", "The garden and retaining walls, standing on the ground along their line."),
    "hedges": ("hedge", "The hedges, standing on the ground along their line."),
}


def heading_to(x, y, lines, layers=("roads", "paths")):
    """The heading (degrees) that turns a prop's front (-Y) towards the nearest line of the layers, or None."""
    best, target = None, None
    for line in lines:
        if line.get("layer") not in layers:
            continue
        for p, q in zip(line["points"], line["points"][1:]):
            dx, dy = q[0] - p[0], q[1] - p[1]
            length2 = dx * dx + dy * dy
            t = 0.0 if not length2 else max(0.0, min(1.0, ((x - p[0]) * dx + (y - p[1]) * dy) / length2))
            cx, cy = p[0] + t * dx, p[1] + t * dy
            d = math.hypot(cx - x, cy - y)
            if best is None or d < best:
                best, target = d, (cx, cy)
    if target is None or best < 1.0:
        return None
    return math.degrees(math.atan2(target[1] - y, target[0] - x)) + 90.0


def footprint_of(kind, height):
    """(x, y) in mm: the footprint of a prop's solid."""
    shape, value = PROPS[kind]["body"]
    if shape == "cylinder":
        return 2 * value, 2 * value
    return value


# What lies on the ground, as thick as it is: a thing standing on a road
# stands on the asphalt. The tall layers - fences, walls, hedges, buildings -
# are not stood on; a thing in one of them is in it, and 'place' says so.
FLAT = ("roads", "paths", "water")
TALL = ("fences", "walls", "hedges")


class Cover:
    """What covers the ground at a point of the plan: how thick the flat layers there are, and what tall one."""

    def __init__(self, features):
        self.lines = [line for line in features["lines"] if line.get("layer") and line.get("width", 0) > 0]
        self.water = [area["outline"] for area in features["areas"] if area["kind"] == "water"]
        self.buildings = [area["outline"] for area in features["areas"] if area["kind"] == "building"]

    def thickness(self, x, y):
        found = 0.0
        for line in self.lines:
            if (
                line["layer"] in FLAT
                and line["thickness"] > found
                and near_line(x, y, line["points"], line["width"] / 2.0)
            ):
                found = line["thickness"]
        if found < 50.0 and any(in_polygon(x, y, outline) for outline in self.water):
            found = 50.0
        return found

    def standing_in(self, x, y):
        """The tall thing at a point, if any: 'building', 'fence', 'wall', 'hedge', ..."""
        if any(in_polygon(x, y, outline) for outline in self.buildings):
            return "building"
        for line in self.lines:
            if line["layer"] in TALL and near_line(x, y, line["points"], line["width"] / 2.0):
                return line["kind"]
        return None


# How far above what it stands on a thing is stood: nothing a picture shows,
# and the difference between two solids that touch along a face - which a
# boolean can take for one inside the other - and two that do not.
CLEARANCE = 1.0

# Points across a footprint, a side's worth of them: 9, so that the edge of a
# road passing under it is found.
SAMPLES = [k / 4.0 - 1.0 for k in range(9)]


def footprint_points(x, y, footprint, heading):
    """Points across a footprint turned by heading: its corners, its middle, and between."""
    half_x, half_y = footprint[0] / 2.0, footprint[1] / 2.0
    c, s = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    for fx in SAMPLES:
        for fy in SAMPLES:
            px, py = fx * half_x, fy * half_y
            yield x + px * c - py * s, y + px * s + py * c


def rest(surface, x, y, footprint, heading, cover=None):
    """The z that stands a footprint turned by heading on the highest ground under it, and the ground's fall there.

    On whatever flat layer covers the ground there, with 'cover': a road's top, not the ground under it.
    """
    heights = []
    for gx, gy in footprint_points(x, y, footprint, heading):
        if surface.inside(gx, gy):
            heights.append(surface.height(gx, gy) + (cover.thickness(gx, gy) if cover else 0.0))
    if not heights:
        heights = [surface.height(x, y)]
    return max(heights), max(heights) - min(heights)


def in_polygon(x, y, polygon):
    inside = False
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def near_line(x, y, points, distance):
    for p, q in zip(points, points[1:]):
        dx, dy = q[0] - p[0], q[1] - p[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if not length2 else max(0.0, min(1.0, ((x - p[0]) * dx + (y - p[1]) * dy) / length2))
        if math.hypot(p[0] + t * dx - x, p[1] + t * dy - y) < distance:
            return True
    return False


class Occupancy:
    """What is taken: the areas, the lines with their widths, and the props placed so far."""

    def __init__(self, features, clear):
        self.areas = [a["outline"] for a in features["areas"] if a["kind"] in ("building", "water")]
        self.lines = [(line["points"], line.get("width", 0.0) / 2.0) for line in features["lines"] if "layer" in line]
        self.props = []
        self.clear = clear

    def free(self, x, y, radius):
        if math.hypot(x, y) < self.clear + radius:
            return False
        if any(in_polygon(x, y, outline) for outline in self.areas):
            return False
        if any(near_line(x, y, outline + outline[:1], radius + 500.0) for outline in self.areas):
            return False
        if any(near_line(x, y, points, half + radius + 500.0) for points, half in self.lines):
            return False
        return all(math.hypot(x - px, y - py) >= radius + pr for px, py, pr in self.props)

    def take(self, x, y, radius):
        self.props.append((x, y, radius))


# -- package -----------------------------------------------------------------------------------------------------


def slug(text):
    keep = "".join(c.lower() if c.isalnum() else "-" for c in text)
    return "-".join(part for part in keep.split("-") if part) or "site"


def yaml_string(text):
    return json.dumps(text, ensure_ascii=False)


def fmt(value):
    return ("%.3f" % value).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def package(args):
    with open(args.site, encoding="utf-8") as f:
        site = json.load(f)
    surface = Surface(site["surface"])
    feats = site["features"]
    out = args.output
    # A package is found where a package's own directory has it, and nowhere
    # deeper: written anywhere else, nothing would ever find it.
    parent = os.path.dirname(os.path.abspath(out))
    if not os.path.isfile(os.path.join(parent, "partcad.yaml")) and not args.force:
        raise SystemExit(
            "%s is not in a PartCAD package's own directory (%s has no partcad.yaml), so nothing would find it: "
            "write it beside a partcad.yaml, or say --force" % (out, parent)
        )
    os.makedirs(out, exist_ok=True)
    kept = os.path.join(out, "site.json")
    if os.path.abspath(kept) != os.path.abspath(args.site):
        with open(kept, "w", encoding="utf-8") as f:
            json.dump(site, f, indent=1)
            f.write("\n")
    rng = random.Random(args.seed)

    looks = {}
    if not args.no_looks:
        for kind, spec in PROPS.items():
            if spec.get("look") and (spec["look"].get("open") or args.all_looks):
                looks[kind] = dict(spec["look"])
    for assignment in args.look or []:
        kind, _, part = assignment.partition("=")
        if kind not in PROPS:
            raise SystemExit("--look: '%s' is not a kind of prop (%s)" % (kind, ", ".join(PROPS)))
        bbox = probe_bbox(part, args.site_dir or os.getcwd())
        looks[kind] = {"part": part, "bbox": bbox, "license": "see %s" % part}

    # The props: the map's, then the rows of trees and the woods it has, then
    # what --scatter asks for, each where nothing else is.
    occupancy = Occupancy(feats, args.clear)
    cover = Cover(feats)
    props = []
    inside_buildings = []

    def add(kind, x, y, height=None, heading=None):
        if not surface.inside(x, y):
            return False
        height = height or PROPS[kind]["height"]
        if heading is None:
            heading = rng.uniform(0.0, 360.0)
        footprint = footprint_of(kind, height)
        # The map puts a thing inside a building where it was mapped against the wall, or indoors.
        if any(cover.standing_in(px, py) == "building" for px, py in footprint_points(x, y, footprint, heading)):
            inside_buildings.append(kind)
            return False
        z, fall = rest(surface, x, y, footprint, heading, cover)
        z += CLEARANCE
        props.append({"kind": kind, "x": x, "y": y, "z": z, "heading": heading % 360.0, "height": height})
        occupancy.take(x, y, max(footprint) / 2.0)
        return True

    for point in feats["points"]:
        heading = None
        if point["kind"] in FACING:
            heading = point.get("direction")
            if heading is None:
                heading = heading_to(point["x"], point["y"], feats["lines"], FACING[point["kind"]])
            else:
                # OSM's 'direction' is the compass bearing the thing faces.
                heading = 180.0 - heading
        add(point["kind"], point["x"], point["y"], point.get("height"), heading)

    trees = sum(1 for prop in props if prop["kind"] == "tree")
    for line in feats["lines"]:
        if line["kind"] != "tree_row":
            continue
        for x, y in along(line["points"], 8000.0):
            if trees < args.max_trees and occupancy.free(x, y, 1500.0):
                trees += add("tree", x, y)
    for wood in feats["areas"]:
        if wood["kind"] != "wood":
            continue
        xs, ys = [p[0] for p in wood["outline"]], [p[1] for p in wood["outline"]]
        attempts = int(abs(area(wood["outline"])) / (8000.0 * 8000.0)) * 3
        for _ in range(attempts):
            if trees >= args.max_trees:
                break
            x, y = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
            if in_polygon(x, y, wood["outline"]) and occupancy.free(x, y, 3000.0):
                trees += add("tree", x, y, rng.uniform(0.8, 1.2) * PROPS["tree"]["height"])
    for assignment in args.scatter or []:
        kind, _, count = assignment.partition("=")
        if kind not in PROPS:
            raise SystemExit("--scatter: '%s' is not a kind of prop (%s)" % (kind, ", ".join(PROPS)))
        wanted, placed = int(count or 1), 0
        radius = max(footprint_of(kind, PROPS[kind]["height"])) / 2.0
        for _ in range(wanted * 50):
            if placed >= wanted:
                break
            x = rng.uniform(surface.x0 + radius, surface.x1 - radius)
            y = rng.uniform(surface.y0 + radius, surface.y1 - radius)
            if occupancy.free(x, y, radius):
                placed += add(kind, x, y, rng.uniform(0.7, 1.3) * PROPS[kind]["height"] if kind == "boulder" else None)
        if placed < wanted:
            print("--scatter %s: room for %d of %d" % (kind, placed, wanted), file=sys.stderr)

    if inside_buildings:
        print("left out, inside a building on the map: %s" % ", ".join(sorted(inside_buildings)), file=sys.stderr)
    layers = draped_layers(site, surface)
    write_ground(os.path.join(out, "ground.py"), site, layers)
    write_assy(os.path.join(out, "landscape.assy"), layers, props)
    write_yaml(os.path.join(out, "partcad.yaml"), site, layers, props, looks, args)
    counts = {}
    for prop in props:
        counts[prop["kind"]] = counts.get(prop["kind"], 0) + 1
    print(
        "wrote %s: %s; %s"
        % (
            out,
            ", ".join(sorted(layers)) or "the ground",
            ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())) or "no props",
        ),
        file=sys.stderr,
    )


def along(points, pitch):
    """Points every 'pitch' mm along a polyline, starting half a pitch in."""
    position, out = pitch / 2.0, []
    walked = 0.0
    for p, q in zip(points, points[1:]):
        length = math.dist(p, q)
        while position <= walked + length:
            t = (position - walked) / length
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
            position += pitch
        walked += length
    return out


def draped_layers(site, surface):
    """{layer: {'thickness': mm, 'lines': [[width, points]], 'areas': [outline]}} of what is draped or stands."""
    layers = {}
    for line in site["features"]["lines"]:
        layer = line.get("layer")
        if not layer or line.get("width", 0) <= 0:
            continue
        entry = layers.setdefault(layer, {"thickness": line["thickness"], "lines": [], "areas": [], "tops": []})
        # One thickness per layer: the tallest of its lines, so a wall says
        # how high the highest one is. Fences and walls differ enough to be
        # layers of their own.
        entry["thickness"] = max(entry["thickness"], line["thickness"])
        entry["lines"].append([line["width"], line["points"]])
    for item in site["features"]["areas"]:
        if item["kind"] == "water":
            entry = layers.setdefault("water", {"thickness": 50.0, "lines": [], "areas": [], "tops": []})
            entry["areas"].append(item["outline"])
        elif item["kind"] == "building":
            entry = layers.setdefault("buildings", {"thickness": 0.0, "lines": [], "areas": [], "tops": []})
            ground = max(surface.height(x, y) for x, y in item["outline"] if surface.inside(x, y, -1.0))
            entry["areas"].append(item["outline"])
            entry["tops"].append(round(ground + item["height"], 1))
    return layers


GROUND_SCRIPT = """# The ground of a landscape and what stands on it: generated by the `gen-landscape`
# skill's landscape.py from site.json. Do not edit it; run landscape.py again.
#
# Every layer, as one part (`layer` "all") or one at a time (`ground;layer=roads`),
# so that they all stand on the one surface: a cubic B-spline surface with its poles on a regular
# grid, at the Greville abscissae of its knots. That makes X and Y linear in the
# surface's parameters, so an outline drawn on the plan is the same outline in
# the surface's (u, v) - a straight edge stays straight - and a face of the
# ground cut to it is made directly, with no intersection of surfaces at all.
#
# Every layer is solids between two levels over outlines on the plan: the
# ground is the whole area between z = 0 and the surface; a road, a path or water
# lies between the surface and the surface lifted by its thickness; a fence, a
# wall or a hedge is the same with its height as its thickness; a building stands
# between the surface and its flat roof. A layer's outlines are the union of its
# footprints, worked out on the plane, where it is quick.
import math

from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_BuilderAlgo, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeSolid,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Sewing,
)
from OCP.BRepFill import BRepFill
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.BRep import BRep_Tool
from OCP.GCE2d import GCE2d_MakeSegment
from OCP.Geom import Geom_BSplineSurface
from OCP.gp import gp_Pnt, gp_Pnt2d
from OCP.ShapeFix import ShapeFix_Solid
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
    TopTools_ListOfShape,
)

layer = "all"

SURFACE = @SURFACE@
LAYERS = @LAYERS@
PAINT = @PAINT@

X0, Y0, X1, Y1 = SURFACE["extent"]
_SURFACES = {}


def _array(values, kind):
    array = kind(1, len(values))
    for index, value in enumerate(values, 1):
        array.SetValue(index, value)
    return array


def surface(lift=0.0):
    # The ground's surface, lifted by 'lift' along Z: the same surface, its poles higher.
    if lift in _SURFACES:
        return _SURFACES[lift]
    degree, poles = SURFACE["degree"], SURFACE["poles"]
    nu, nv = len(poles), len(poles[0])
    knots = {}
    for count in (nu, nv):
        spans = count - degree
        flat = [0.0] * (degree + 1) + [k / spans for k in range(1, spans)] + [1.0] * (degree + 1)
        knots[count] = (
            [sum(flat[i + 1 : i + degree + 1]) / degree for i in range(count)],
            _array([k / spans for k in range(spans + 1)], TColStd_Array1OfReal),
            _array([degree + 1] + [1] * (spans - 1) + [degree + 1], TColStd_Array1OfInteger),
        )
    grid = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i, g in enumerate(knots[nu][0]):
        for j, h in enumerate(knots[nv][0]):
            grid.SetValue(i + 1, j + 1, gp_Pnt(X0 + g * (X1 - X0), Y0 + h * (Y1 - Y0), poles[i][j] + lift))
    built = Geom_BSplineSurface(grid, knots[nu][1], knots[nv][1], knots[nu][2], knots[nv][2], degree, degree)
    _SURFACES[lift] = built
    return built


def highest():
    return max(max(column) for column in SURFACE["poles"])


def edge(level, p, q):
    # The edge over the plan's segment p-q at a level: ('surface', lift) or ('plane', z).
    kind, value = level
    if kind == "plane":
        return BRepBuilderAPI_MakeEdge(gp_Pnt(p[0], p[1], value), gp_Pnt(q[0], q[1], value)).Edge()
    a = gp_Pnt2d((p[0] - X0) / (X1 - X0), (p[1] - Y0) / (Y1 - Y0))
    b = gp_Pnt2d((q[0] - X0) / (X1 - X0), (q[1] - Y0) / (Y1 - Y0))
    made = BRepBuilderAPI_MakeEdge(GCE2d_MakeSegment(a, b).Value(), surface(value)).Edge()
    BRepLib.BuildCurves3d_s(made)
    return made


def ring_edges(level, ring):
    return [edge(level, p, q) for p, q in zip(ring, ring[1:] + ring[:1])]


def wire(edges):
    made = BRepBuilderAPI_MakeWire()
    for e in edges:
        made.Add(e)
    return made.Wire()


def face(level, rings, edges):
    # A face at a level, bounded by the rings' edges: on the surface, or flat.
    kind, value = level
    if kind == "plane":
        made = BRepBuilderAPI_MakeFace(wire(edges[0]), True)
    else:
        made = BRepBuilderAPI_MakeFace(surface(value), wire(edges[0]), True)
    for hole in edges[1:]:
        made.Add(wire(hole))
    result = made.Face()
    if kind != "plane":
        BRepLib.BuildCurves3d_s(result)
    return result


def between(rings, lower, upper):
    # The solid over a plan's region - its outer ring, then its holes - from one level to another.
    rings = [_clean(ring) for ring in rings]
    if len(rings[0]) < 3:
        return None
    rings = [_oriented(ring, index == 0) for index, ring in enumerate(rings) if len(ring) >= 3]
    low = [ring_edges(lower, ring) for ring in rings]
    high = [ring_edges(upper, ring) for ring in rings]
    sewing = BRepBuilderAPI_Sewing(0.01)
    sewing.Add(face(lower, rings, low))
    sewing.Add(face(upper, rings, high))
    for bottom, top in zip(low, high):
        for a, b in zip(bottom, top):
            sewing.Add(BRepFill.Face_s(a, b))
    sewing.Perform()
    shells = TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL)
    if not shells.More():
        return None
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells.Current())).Solid()
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    return fix.Solid()


def _clean(ring):
    out = []
    for p in ring:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1.0:
            out.append((p[0], p[1]))
    while len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= 1.0:
        out.pop()
    return out


def _oriented(ring, outer):
    area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(ring, ring[1:] + ring[:1]))
    return ring if (area > 0) == outer else list(reversed(ring))


def _polygon(points):
    made = BRepBuilderAPI_MakePolygon()
    for x, y in points:
        made.Add(gp_Pnt(x, y, 0.0))
    made.Close()
    return BRepBuilderAPI_MakeFace(made.Wire(), True).Face()


def _band(width, points):
    # A line 'width' wide on the plan: a rectangle per segment and an octagon at each joint. A thin line
    # - a fence, a hedge - has no octagons: its rectangles reach on past their ends by half its width,
    # which fills a bend, in a fraction of the faces.
    faces, half = [], width / 2.0
    reach = half if width <= 1500.0 else 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length = math.hypot(bx - ax, by - ay)
        if length < 1.0:
            continue
        dx, dy = (bx - ax) / length * reach, (by - ay) / length * reach
        ax, ay, bx, by = ax - dx, ay - dy, bx + dx, by + dy
        nx, ny = -(by - ay) / (length + 2 * reach) * half, (bx - ax) / (length + 2 * reach) * half
        faces.append(_polygon([(ax + nx, ay + ny), (ax - nx, ay - ny), (bx - nx, by - ny), (bx + nx, by + ny)]))
    radius = half / math.cos(math.pi / 8)
    for x, y in points[1:-1] if not reach else []:
        corners = [(x + radius * math.cos(k * math.pi / 4 + math.pi / 8), y + radius * math.sin(k * math.pi / 4 + math.pi / 8)) for k in range(8)]
        faces.append(_polygon(corners))
    return faces


def regions(spec):
    # The union of a layer's footprints on the plan, as regions: [outer ring, holes...].
    return [_rings(f) for f in union(spec)]


def _rings(f):
    outer = BRepTools.OuterWire_s(f)
    rings = [_ring(outer)]
    wires = TopExp_Explorer(f, TopAbs_WIRE)
    while wires.More():
        if not wires.Current().IsSame(outer):
            rings.append(_ring(TopoDS.Wire_s(wires.Current())))
        wires.Next()
    return rings


def union(spec):
    # The union of a layer's footprints on the plan, as faces at z = 0.
    faces = []
    for width, points in spec["lines"]:
        faces.extend(_band(width, points))
    for outline in spec["areas"]:
        try:
            faces.append(_polygon(outline))
        except Exception:  # an outline the map draws crossing itself: left out
            pass
    if not faces:
        return []
    shape = faces[0]
    if len(faces) > 1:
        arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        arguments.Append(faces[0])
        for f in faces[1:]:
            tools.Append(f)
        fuse = BRepAlgoAPI_Fuse()
        fuse.SetArguments(arguments)
        fuse.SetTools(tools)
        fuse.SetFuzzyValue(1e-3)
        fuse.Build()
        shape = fuse.Shape()
    unify = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    unify.Build()
    found = []
    explorer = TopExp_Explorer(unify.Shape(), TopAbs_FACE)
    while explorer.More():
        found.append(TopoDS.Face_s(explorer.Current()))
        explorer.Next()
    return found


def _ring(w):
    points = []
    explorer = BRepTools_WireExplorer(w)
    while explorer.More():
        p = BRep_Tool.Pnt_s(explorer.CurrentVertex())
        points.append((p.X(), p.Y()))
        explorer.Next()
    return points


def compound(shapes):
    result, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        if shape is not None:
            builder.Add(result, shape)
    return result


def terrain():
    return between([[(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)]], ("plane", 0.0), ("surface", 0.0))


def draped(spec):
    return compound(between(rings, ("surface", 0.0), ("surface", spec["thickness"])) for rings in regions(spec))


def buildings(spec):
    return compound(
        between([outline], ("surface", 0.0), ("plane", roof)) for outline, roof in zip(spec["areas"], spec["tops"])
    )


def build(name):
    # One layer, painted: 'set_cmf', handed to every part script, says what it is drawn in.
    if name == "terrain":
        shape = terrain()
    elif name == "buildings":
        shape = buildings(LAYERS[name])
    else:
        shape = draped(LAYERS[name])
    if "set_cmf" in globals() and PAINT.get(name):
        set_cmf(shape, color=PAINT[name])  # noqa: F821 - handed in by the script runner
    return shape


# What wins where two layers' footprints meet: a building stands over a path
# through it, a fence across a road, a road over the water it crosses.
PRIORITY = ("buildings", "walls", "hedges", "fences", "roads", "paths", "water")


def _listed(shapes):
    return list(shapes)


def _perimeter(p):
    # How far along the area's boundary a point of it is, anticlockwise from its south-west corner.
    x, y = p
    width, depth = X1 - X0, Y1 - Y0
    if abs(y - Y0) < 1e-3:
        return x - X0
    if abs(x - X1) < 1e-3:
        return width + y - Y0
    if abs(y - Y1) < 1e-3:
        return 2 * width + depth - (x - X0)
    return 2 * width + 2 * depth - (y - Y0)


def ground():
    # The whole ground as one solid. The plan is cut into pieces where the layers' footprints meet,
    # each piece rises to its own level - the surface, a layer's thickness above it, or a roof -
    # and a riser stands wherever two neighbours differ: no two solids touch, so nothing anywhere
    # has to intersect one curved face with another.
    items = []
    spec = LAYERS.get("buildings")
    if spec:
        for outline, roof in zip(spec["areas"], spec["tops"]):
            try:
                items.append((("plane", roof), PAINT.get("buildings"), [_polygon(_clean(outline))]))
            except Exception:  # an outline the map draws crossing itself: left out
                pass
    for name in PRIORITY[1:]:
        if name in LAYERS:
            items.append((("surface", LAYERS[name]["thickness"]), PAINT.get(name), union(LAYERS[name])))

    area = _polygon([(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)])
    arguments = TopTools_ListOfShape()
    arguments.Append(area)
    for _, _, faces in items:
        for f in faces:
            arguments.Append(f)
    cut = BRepAlgoAPI_BuilderAlgo()
    cut.SetArguments(arguments)
    cut.SetFuzzyValue(1e-3)
    cut.Build()
    plan = cut.Shape()
    pieces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(plan, TopAbs_FACE, pieces)

    def images(f):
        made = _listed(cut.Modified(f))
        return made if made else [f]

    inside = set(pieces.FindIndex(f) for f in images(area))
    owner = {}
    for index in range(len(items) - 1, -1, -1):  # the lowest first, for the highest to win
        for f in items[index][2]:
            for piece in images(f):
                found = pieces.FindIndex(piece)
                if found in inside:
                    owner[found] = index

    def level(i):
        return items[owner[i]][0] if i in owner else ("surface", 0.0)

    def paint(i):
        return items[owner[i]][1] if i in owner else PAINT.get("terrain")

    faces = []
    for i in sorted(inside):
        rings = _rings(TopoDS.Face_s(pieces.FindKey(i)))
        rings = [_oriented(ring, index == 0) for index, ring in enumerate(rings)]
        edges = [ring_edges(level(i), ring) for ring in rings]
        faces.append((face(level(i), rings, edges), paint(i)))

    neighbours = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(plan, TopAbs_EDGE, TopAbs_FACE, neighbours)
    boundary = []
    for e in range(1, neighbours.Extent() + 1):
        edge_shape = TopoDS.Edge_s(neighbours.FindKey(e))
        a = BRep_Tool.Pnt_s(TopExp.FirstVertex_s(edge_shape))
        b = BRep_Tool.Pnt_s(TopExp.LastVertex_s(edge_shape))
        p, q = (a.X(), a.Y()), (b.X(), b.Y())
        if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6:
            continue
        sides = sorted(set(pieces.FindIndex(f) for f in _listed(neighbours.FindFromIndex(e))) & inside)
        if len(sides) == 1:
            # The area's side: ground from the base up to the surface, and what lies there above it.
            boundary.append(p)
            faces.append((BRepFill.Face_s(edge(("plane", 0.0), p, q), edge(("surface", 0.0), p, q)), PAINT.get("terrain")))
            if level(sides[0]) == ("surface", 0.0):
                continue
            low, high, colour = ("surface", 0.0), level(sides[0]), paint(sides[0])
        elif len(sides) == 2 and level(sides[0]) != level(sides[1]):
            low, high = level(sides[0]), level(sides[1])
            ranks = [owner.get(side, len(items)) for side in sides]
            colour = paint(sides[ranks.index(min(ranks))])
        else:
            continue
        faces.append((BRepFill.Face_s(edge(low, p, q), edge(high, p, q)), colour))

    ring = sorted(set((round(x, 6), round(y, 6)) for x, y in boundary), key=_perimeter)
    faces.append((face(("plane", 0.0), [ring], [ring_edges(("plane", 0.0), ring)]), PAINT.get("terrain")))

    sewing = BRepBuilderAPI_Sewing(0.01)
    for f, _ in faces:
        sewing.Add(f)
    sewing.Perform()
    shells = TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL)
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells.Current())).Solid()
    # Turned the right way out, and a face whose hole touches its outline at a corner mended. The fix
    # makes new faces of some, and says which: what each face is painted follows it there.
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    solid = fix.Solid()

    if "set_cmf" in globals():
        sewn, colours = TopTools_IndexedMapOfShape(), {}
        for f, colour in faces:
            if not colour:
                continue
            made = fix.Context().Apply(sewing.Modified(f))
            pieces = TopExp_Explorer(made, TopAbs_FACE)
            while pieces.More():
                colours[sewn.Add(pieces.Current())] = colour
                pieces.Next()
        explorer = TopExp_Explorer(solid, TopAbs_FACE)
        while explorer.More():
            colour = colours.get(sewn.FindIndex(explorer.Current()))
            if colour:
                set_cmf(explorer.Current(), color=colour)  # noqa: F821 - handed in by the script runner
            explorer.Next()
    return solid


# The whole ground is one solid: as parts of their own, the layers would touch
# along the ground's surface, and a check of overlaps would intersect every pair
# of them there - the slowest thing a boolean does - to learn nothing.
if layer == "all":
    result = ground()
else:
    result = build(layer)

if "show_object" in locals():
    show_object(result, name=layer)
"""


def write_ground(path, site, layers):
    surface = site["surface"]
    data = {"extent": surface["extent"], "degree": surface["degree"], "poles": surface["poles"]}
    text = GROUND_SCRIPT.replace("@SURFACE@", json.dumps(data, separators=(",", ":")))
    text = text.replace("@LAYERS@", json.dumps(layers, separators=(",", ":")))
    paint = {name: ":" + color for name, (color, _) in LAYERS.items() if name == "terrain" or name in layers}
    text = text.replace("@PAINT@", json.dumps(paint, sort_keys=True))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_assy(path, layers, props):
    lines = [
        "# The landscape: its ground, what is draped on it, and its props, each where the map has it.",
        "# Generated by the `gen-landscape` skill's landscape.py: do not edit it; run landscape.py again.",
        "links:",
    ]
    lines += ["  - part: ground", "    name: ground", "    fixed: true"]
    counts = {}
    for prop in props:
        counts[prop["kind"]] = counts.get(prop["kind"], 0) + 1
        lines += [
            "  - part: %s" % prop["kind"],
            "    name: %s-%d" % (prop["kind"], counts[prop["kind"]]),
            "    params: {height: %s}" % fmt(round(prop["height"], 0)),
            "    location: [[%s, %s, %s], [0, 0, 1], %s]"
            % (
                fmt(round(prop["x"], 1)),
                fmt(round(prop["y"], 1)),
                fmt(round(prop["z"], 1)),
                fmt(round(prop["heading"], 1)),
            ),
            "    fixed: true",
        ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_yaml(path, site, layers, props, looks, args):
    query = site["query"]
    where = (
        query.get("found")
        or query.get("address")
        or ", ".join("%.6f" % v for v in (query.get("center") or [site["origin"]["lat"], site["origin"]["lon"]]))
    )
    width, depth = query["size"]
    lines = [
        "# A landscape: generated by the `gen-landscape` skill's landscape.py from site.json.",
        "# Do not edit it; run `landscape.py package` again. A scene of your own places this",
        "# one (`scene: <this package>:landscape`) and the objects you test in it.",
        "#",
        "# The frame: millimetres, X east, Y north, Z up, the origin at the centre of the area.",
        "# `landscape.py height site.json X Y` is the height of the ground at a point of it, and",
        "# `landscape.py place site.json X Y --footprint W,D` a location standing an object there.",
        "desc: %s"
        % yaml_string(
            "%.0f x %.0f m of the world around %s, as a landscape to test objects in." % (width, depth, where)
        ),
        "manufacturable: false",
        "",
        "# Where its data came from, and what each source asks of whoever uses what was made of it.",
        "docs:",
        "  usage: |",
        "    The landscape is the scene `landscape`. Place it in a scene of your own,",
        "    with the objects to test, at z = the ground's height (`landscape.py height`).",
        "",
        "    Origin: %.8f, %.8f. Fetched %s." % (site["origin"]["lat"], site["origin"]["lon"], site["fetched"]),
        "    Ground: %.1f to %.1f m above the elevation model's datum, the lowest at z = %s mm."
        % (site["surface"]["lowest"], site["surface"]["highest"], fmt(float(site["surface"]["base"]))),
        "",
    ]
    for source in site["sources"]:
        lines.append("    - %s: %s (%s)" % (source["name"], source["attribution"], source["url"]))
    used = sorted({prop["kind"] for prop in props})
    for kind in used:
        if kind in looks:
            lines.append("    - The %s is drawn as %s: %s" % (kind, looks[kind]["part"], looks[kind]["license"]))
    lines += ["", "colors:"]
    wanted = {LAYERS[layer][0] for layer in LAYERS if layer == "terrain" or layer in layers}
    wanted |= {PROPS[kind]["color"] for kind in used if not (kind in looks and looks[kind].get("color"))}
    wanted |= {looks[kind].get("color") for kind in used if kind in looks and looks[kind].get("color")}
    for name in sorted(wanted):
        display, desc = COLORS[name]
        lines += [
            "  %s:" % name,
            "    desc: %s" % yaml_string(desc),
            '    display: "%s"' % display,
            "    manufacturable: false",
        ]
    built = [name for name in LAYERS if name == "terrain" or name in layers]
    lines += [
        "",
        "parts:",
        "  ground:",
        "    type: build123d",
        "    path: ground.py",
        "    desc: %s"
        % yaml_string(
            "The ground, on a flat base at z = 0, and what lies or stands on it that is not a prop (%s), "
            "one part with each layer in its own colour." % ", ".join(name for name in built if name != "terrain")
            if len(built) > 1
            else "The ground, on a flat base at z = 0."
        ),
        "    manufacturable: false",
        "    parameters:",
        "      layer:",
        "        type: string",
        "        default: all",
        "        enum: [%s]" % ", ".join(["all"] + built),
        "        desc: Every layer, or one of them alone.",
    ]
    for kind in used:
        spec = PROPS[kind]
        shape, value = spec["body"]
        look = looks.get(kind)
        lines += [
            "  %s:" % kind,
            "    type: basic",
            "    desc: %s" % yaml_string(spec["desc"] + " Its origin is the centre of its base."),
            "    manufacturable: false",
            "    parameters:",
            "      height: {type: float, default: %s, desc: How high it is in mm.}" % fmt(spec["height"]),
        ]
        # A visual is asked for with the values of every parameter it shares with
        # its part: a look of a colour of its own takes it only if the part has none.
        if not (look and look.get("color")):
            lines.append('      color: {type: string, default: ":%s"}' % spec["color"])
        if shape == "cylinder":
            lines.append('    cylinder: {radius: %s, height: "%%height%%"}' % fmt(value))
        else:
            lines.append('    cuboid: [%s, %s, "%%height%%"]' % (fmt(value[0]), fmt(value[1])))
        lines.append('    offset: [[0, 0, "%height / 2%"], [0, 0, 1], 0]')
        if look:
            lines.append("    visual: %s-look" % kind)
    for kind in used:
        look = looks.get(kind)
        if not look:
            continue
        x0, y0, z0, x1, y1, z1 = look["bbox"]
        lines += [
            "  %s-look:" % kind,
            "    type: alias",
            "    source: %s" % yaml_string(look["part"]),
            "    desc: %s" % yaml_string("What a %s is drawn as: %s" % (kind, look["license"])),
            "    private: true",
            "    manufacturable: false",
            "    parameters:",
            "      height: {type: float, default: %s}" % fmt(PROPS[kind]["height"]),
        ]
        if look.get("color"):
            lines.append('      color: {type: string, default: ":%s"}' % look["color"])
        lines += [
            "    # Its base's centre to the origin, in its own units, then scaled to the prop's height.",
            "    offset: [[%s, %s, %s], [0, 0, 1], 0]"
            % (fmt(round(-(x0 + x1) / 2.0, 4)), fmt(round(-(y0 + y1) / 2.0, 4)), fmt(round(-z0, 4))),
            '    scale: "%%height / %s%%"' % fmt(round(z1 - z0, 4)),
        ]
    lines += [
        "",
        "scenes:",
        "  landscape:",
        "    type: assy",
        "    path: landscape.assy",
        "    desc: %s" % yaml_string("The landscape: the ground, what is draped on it, and its props, all fixed."),
        "    gravity: [0, 0, -9.81]",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def probe_bbox(part, where):
    """A catalog part's bounding box, measured by PartCAD: 'pc info' run in the package that will draw it."""
    import re
    import subprocess

    print("measuring %s with pc info ..." % part, file=sys.stderr)
    run = subprocess.run(["pc", "--no-ansi", "info", part], cwd=where, capture_output=True, text=True)
    text = run.stdout + run.stderr
    found = re.search(r"BoundingBox: \{'max': \[([^\]]*)\],\s*'min': \[([^\]]*)\]", text)
    if run.returncode != 0 or not found:
        raise SystemExit("pc info %s did not say how large it is:\n%s" % (part, text[-2000:]))
    high = [float(v) for v in found.group(1).split(",")]
    low = [float(v) for v in found.group(2).split(",")]
    return low + high


# -- height, place, props ----------------------------------------------------------------------------------------


def height(args):
    with open(args.site, encoding="utf-8") as f:
        surface = Surface(json.load(f)["surface"])
    values = args.xy
    if len(values) % 2:
        raise SystemExit("height: give X Y pairs")
    for x, y in zip(values[::2], values[1::2]):
        if not surface.inside(x, y):
            print("%s %s outside" % (fmt(x), fmt(y)))
            continue
        print("%s %s %s" % (fmt(x), fmt(y), fmt(round(surface.height(x, y), 1))))


def place(args):
    with open(args.site, encoding="utf-8") as f:
        site = json.load(f)
    surface = Surface(site["surface"])
    cover = Cover(site["features"])
    if not surface.inside(args.x, args.y):
        raise SystemExit(
            "%s, %s is outside the landscape: X from %s to %s, Y from %s to %s"
            % (fmt(args.x), fmt(args.y), fmt(surface.x0), fmt(surface.x1), fmt(surface.y0), fmt(surface.y1))
        )
    z, fall = rest(surface, args.x, args.y, args.footprint, args.heading, cover)
    z += CLEARANCE
    on = sorted(
        {cover.standing_in(gx, gy) for gx, gy in footprint_points(args.x, args.y, args.footprint, args.heading)}
        - {None}
    )
    flat = cover.thickness(args.x, args.y)
    print("location: [[%s, %s, %s], [0, 0, 1], %s]" % (fmt(args.x), fmt(args.y), fmt(round(z, 1)), fmt(args.heading)))
    print(
        "# the ground falls %s mm across the footprint: %s"
        % (fmt(round(fall, 1)), "level" if fall < 20 else "it stands on its highest corner")
    )
    if flat:
        print("# it stands on a road, a path or water, %s mm thick" % fmt(flat))
    if on:
        print("# it is in: %s - move it" % ", ".join(on))


def props(_args):
    for kind, spec in PROPS.items():
        look = spec.get("look")
        print(
            "%-8s %6s mm  %-28s %s"
            % (
                kind,
                fmt(spec["height"]),
                "%s %s" % spec["body"],
                (
                    "%s%s  (%s)" % (look["part"], "" if look.get("open") else " [--all-looks]", look["license"])
                    if look
                    else "-"
                ),
            )
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("fetch", help="ask where, the ground and the map, and write site.json")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--address", help="a place to geocode with Nominatim")
    where.add_argument("--center", type=latlon, help="LAT,LON of the middle of the area")
    where.add_argument("--corners", type=latlon, nargs=2, metavar="LAT,LON", help="two opposite corners of the area")
    p.add_argument("--size", type=size, default=[300.0, 300.0], help="W or WxD in metres around the centre (300)")
    p.add_argument("--cells", type=int, default=64, help="spans of the surface along the longer side (64)")
    p.add_argument("--base", type=float, default=1000.0, help="mm from z = 0 to the lowest ground (1000)")
    p.add_argument("--exaggeration", type=float, default=1.0, help="heights times this (1)")
    p.add_argument("--dem", default="terrarium", help="terrarium (default), opentopodata:<dataset>, or flat")
    p.add_argument("--no-osm", action="store_true", help="ask OpenStreetMap nothing: the ground alone")
    p.add_argument("--overpass", help="an Overpass API interpreter URL to ask instead of the public ones")
    p.add_argument("-o", "--output", default="site.json")
    p.set_defaults(func=fetch)

    p = commands.add_parser("package", help="write a PartCAD package of a site.json")
    p.add_argument("site")
    p.add_argument("-o", "--output", default=".", help="the package's directory (.)")
    p.add_argument("--look", action="append", metavar="KIND=PART", help="draw a kind of prop as this //pub part")
    p.add_argument("--no-looks", action="store_true", help="draw every prop as the solid it is")
    p.add_argument(
        "--all-looks", action="store_true", help="draw props as //pub models of any licence, not open ones only"
    )
    p.add_argument("--force", action="store_true", help="write the package even where no package will find it")
    p.add_argument("--scatter", action="append", metavar="KIND=N", help="place N more of a kind where nothing is")
    p.add_argument("--clear", type=float, default=10000.0, help="mm around the origin --scatter leaves free (10000)")
    p.add_argument("--seed", type=int, default=1, help="what --scatter and the woods are random with (1)")
    p.add_argument("--max-trees", type=int, default=300, help="the most trees rows and woods add (300)")
    p.add_argument("--site-dir", help="where 'pc info' measures a --look (the current directory)")
    p.set_defaults(func=package)

    p = commands.add_parser("height", help="the height of the ground at points of the frame")
    p.add_argument("site")
    p.add_argument("xy", type=float, nargs="+", metavar="X Y")
    p.set_defaults(func=height)

    p = commands.add_parser("place", help="the location that stands an object on the ground")
    p.add_argument("site")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)
    p.add_argument(
        "--footprint", default=[0.0, 0.0], type=lambda t: [float(v) for v in t.split(",")], help="W,D in mm (a point)"
    )
    p.add_argument("--heading", type=float, default=0.0, help="degrees about Z (0)")
    p.set_defaults(func=place)

    p = commands.add_parser("props", help="list the kinds of prop and the //pub models they are drawn as")
    p.set_defaults(func=props)

    args = parser.parse_args(argv)
    if args.command == "fetch" and args.cells < 1:
        parser.error("--cells is at least 1")
    args.func(args)


if __name__ == "__main__":
    main()
