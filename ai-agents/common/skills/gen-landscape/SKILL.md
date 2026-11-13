---
name: gen-landscape
description: Generate a PartCAD landscape - a piece of the real world at an address, a point or between two corners, as a scene to drop objects into and test them - from public data, the ground from an elevation model (the AWS Terrain Tiles, or Open Topo Data) and the roads, paths, buildings, fences, walls, hedges, water, trees, signs, street lamps, benches and bollards from OpenStreetMap. It writes a package of its own with the ground as one smooth B-spline solid on a flat base at z = 0, what is draped on it, one `basic` part per prop drawn through a model from the public `//pub` collections, and a `landscape` scene; then stands the user's objects on the ground at its exact height and validates the result with the PartCAD CLI. Nothing is taken from Google, whose terms forbid it. Use for /pc:gen-landscape, or when the user asks for terrain, a landscape, a site, a real place, a street, or a test ground at an address or coordinates.
---

# pc:gen-landscape

Generate a **landscape**: a piece of the real world as a PartCAD scene, to stand
objects in and test them. The text after the command (`$ARGUMENTS`) says where:
an address, a point, or two corners, and what is to be tested there.

What is made is a **package of its own**, a directory beside the user's
`partcad.yaml`, generated whole by `landscape.py` - the helper in this skill's
directory - and never edited by hand:

| File | What it is |
|---|---|
| `site.json` | what was fetched: the ground's surface, the map's features in the scene's frame, and where each came from |
| `ground.py` | one build123d script for the ground and every layer on it, its data written into it |
| `partcad.yaml` | the `ground` part, a `basic` part per kind of prop, their colours, the `landscape` scene, and the attributions the data asks for |
| `landscape.assy` | the scene: the ground, and one link per prop |

The user's objects then go into **a scene of the user's own**, which places
the landscape and them (§5). Nothing in a landscape is manufacturable.

The scene is in one frame: **millimetres, X east, Y north, Z up, the origin at
the centre of the area**, and the ground's lowest point 1000 mm above z = 0,
so that the landscape stands on the plane every simulator writes its ground
in, as `/pc:gen-scene` §4 asks of a bottom surface.

## 1. Where, and how much

Read `$ARGUMENTS` for the place and the area:

- **An address** or a place name: `--address "Lombard Street, San Francisco"`.
  Nominatim geocodes it; say which place it found (the helper prints it, and
  the package's `desc` keeps it), since a name can be found somewhere else.
- **A point**, `LAT,LON` in decimal degrees: `--center 37.8021,-122.4188`.
- **Two corners**, opposite ones: `--corners 37.801,-122.420 37.803,-122.417`.
  The area is the rectangle between them, along north and east.
- **A link or a file the user has**: a Google Maps link carries its point after
  the `@` (`.../@37.8021,-122.4188,17z`), and a KML or KMZ the user drew in
  Google Earth carries the corners of its placemark or polygon. The coordinates
  are the user's to give; take them and nothing else (§2).

The size is the area's sides in metres, `--size 300` (the default, a square)
or `--size 400x250`, east by north, up to 5 km a side. Pick it from what is
being tested: a vehicle's course or a drone's flight wants a few hundred
metres; a robot in a street, 100-200; anything that only needs the ground and
the next building, 50-100. A larger area holds more of the map, and every prop
is a link of the scene: keep it as small as the test needs.

Ask only when the place is genuinely ambiguous. Otherwise proceed and state
what you assumed.

## 2. Fetch

```sh
python3 <this skill's directory>/landscape.py fetch --address "<place>" --size 300 -o site.json
```

It prints the area, the range of the ground's height and what the map has
there (`map: 109 building, 25 road, 29 tree, ...`), and writes `site.json`.
Nothing it needs is installed: it is Python's standard library.

| Option | What it does |
|---|---|
| `--dem terrarium` | (default) the AWS Terrain Tiles: SRTM, 3DEP, EU-DEM and others merged, about 5 m a pixel, no key |
| `--dem opentopodata:<dataset>` | api.opentopodata.org's `ned10m` (USA), `eudem25m` (Europe), `srtm30m`, `aster30m`, `mapzen`, ...: 1 request a second, 1000 a day |
| `--dem flat` | no elevation: a level ground, for a physics test (§5) or no network |
| `--cells 64` | the surface's spans along the longer side; more follows the ground more closely and builds slower |
| `--exaggeration 1` | the heights times this, to see a gentle slope |
| `--no-osm` | the ground alone |
| `--overpass <url>` | another Overpass API server, when the public ones are busy |

The services are public and shared: one `fetch` asks Nominatim once and
Overpass once, which is what their usage policies allow. **Do not loop it.** An
elevation tile is kept in `~/.cache/partcad/landscape`, so a second fetch of the
same place asks only Overpass again. When Overpass is busy the helper tries the
other public servers, then says so; wait a minute rather than retrying in a loop.

**Google's data is not a source**, and say so if the user asks for it: Google's
terms forbid storing or deriving models from Google Earth, Google's
Photorealistic 3D Tiles and its Elevation API, so a landscape made from them
could not be kept in a package or committed. A Google Maps link's coordinates
and the user's own KML are fine: they are the user's.

## 3. Package

Write the package **directly beside the user's `partcad.yaml`**, in a
directory named for the place - PartCAD finds a package only in a package's own
directory, and the helper refuses anywhere else:

```sh
python3 <this skill's directory>/landscape.py package site.json -o <place>
```

It writes the four files of the table above, `site.json` copied in, and prints
what is in it. Then `pc --no-ansi list scenes` names the scene,
`//<package>/<place>:landscape` (`//<place>:landscape` under a root package).

What it makes:

- **`ground`**, one solid, each layer of it in its own colour:
  - the terrain: a smooth face on top, its sides and its base flat, the base at
    z = 0;
  - draped on it: water, roads (100 mm), paths (50 mm), fences (1200 mm, or the
    height the map gives), walls and hedges, each following the ground exactly,
    its underside the ground's surface;
  - the buildings: a block per building on the map, standing on the ground up
    to its roof, from its `height` or its `building:levels`, else 6 m. A block is
    where a building is and how high; it has no roof shape, doors or windows.

  It is one solid, not a part per layer, because the layers touch along the
  ground's surface: as solids of their own - parts, or the solids of one
  compound - every check of an overlap would intersect them with each other
  there, which is where a boolean is slowest, to learn nothing. So the plan is
  cut into pieces where the layers meet, each piece rises to its level, and a
  riser stands wherever two pieces differ. `ground;layer=roads` builds one layer
  alone, as a solid of its own, to look at it or export it.
- **Props**, one link per thing on the map: `tree`, `sign`, `signal`, `lamp`,
  `bench`, `bin`, `bollard`, `hydrant`, `boulder`. Rows of trees and woods are
  planted at 8 m. Each prop is a `basic` part, the solid a check and a simulation
  see (a tree is its trunk, which is what something runs into), standing on the
  highest point under it of whatever covers the ground there - the asphalt of a
  road, not the ground under it - a sign turned to face the nearest road and a
  bench the nearest road or path. A prop the map puts where it would reach into
  a building is left out, and the helper says so.

Its options:

| Option | What it does |
|---|---|
| `--scatter boulder=20` | adds props the map does not have, where nothing else is: obstacles for a test. Repeatable: `--scatter cone=12` |
| `--clear 10000` | mm around the origin that `--scatter` leaves free, for the objects under test |
| `--look tree=<part>` | draws a kind of prop as another `//pub` model (below) |
| `--no-looks` | draws every prop as the solid it is |
| `--all-looks` | also draws the props whose `//pub` model is not openly licensed |
| `--seed`, `--max-trees` | the randomness of scattering and planting, and the most trees it plants |

### What a prop is drawn as

A prop is drawn through its `visual:` (see `/pc:gen-scene` §3): a model from
the `//pub` collections, moved so that the centre of its base is at the origin
and scaled to the prop's height. `landscape.py props` lists them:

| Prop | Drawn as | Licence |
|---|---|---|
| `tree` | `//pub/collection/printables/models:556482`, a low-poly tree | CC-BY-SA |
| `cone` | `//pub/collection/openusd/nvidia/assets/simready:trafficcone_a01` | NVIDIA Omniverse licence: `--all-looks` |
| `bollard` | `//pub/collection/openusd/nvidia/assets/archvis-residential:CircularBollard` | NVIDIA Omniverse licence: `--all-looks` |

The rest are drawn as themselves until a model is found for them. To find one:

```sh
pc --no-ansi search parts -P '//pub/collection/openusd/nvidia/assets...' -k bench
pc --no-ansi search parts -P //pub/collection/printables/models -k "street lamp"
```

A model is a good look when **one file is the whole object, standing up** -
`pc --no-ansi info <part>` shows its `BoundingBox`, and the object's height has to
be its Z. A model site's best file is often one piece of a print laid flat (a
lamp post's arm, a bench's seat, a sign's plate): name the file that is the whole
thing, `<number>;file=<name>`, or pass it by. Leave out what takes minutes to
build: a scanned rock or a Moana Island element is millions of triangles. Then
`--look bench=<part>` measures it with `pc info` and draws every bench as it.

Every look carries its licence into the package's `docs:`, beside the data's
attributions. A `//pub` collection asks for its own terms before it fetches:
NVIDIA's is not an open licence, the Moana Island Scene is for research only,
Pixar's assets are for personal testing only. Say which licences the package now
draws under.

## 4. Build it, and look at it

```sh
for view in iso top; do
  mkdir -p /tmp/pc-render/$view
  pc --no-ansi render -t png -S --view $view --style shaded --size 1400x1000 -O /tmp/pc-render/$view <landscape scene>
done
```

The first build takes about a minute for 250 m of a city, and is cached. Check
the pictures against the place:

- the ground is under everything, its base flat, and its shape is the place's:
  the hill, the valley;
- the roads lie on the ground along the streets, and the buildings stand on it
  where the map has them;
- the props stand on the ground, neither in it nor above it.

Under an IDE, `pc --no-ansi ide view -S <landscape scene>` shows it in the 3D
view.

## 5. Drop the objects in

The objects under test go into **a scene of the user's own**, in their own
package, written as `/pc:gen-scene` writes one: the landscape is a sub-scene,
fixed, and every object is a link placed with `location:`.

```yaml
# test-on-<place>.assy
links:
  - scene: //<place>:landscape
    name: landscape
    fixed: true
  - part: rover                                   # the object under test
    name: rover
    location: [[0, 0, 34643], [0, 0, 1], 30]      # from 'landscape.py place'
    fixed: false                                  # mobile: it is what is being tested
```

```yaml
# partcad.yaml
scenes:
  test-on-<place>:
    type: assy
    path: test-on-<place>.assy
    desc: <what is being tested, where>
    gravity: [0, 0, -9.81]
```

**Stand each object on the ground with `place`**, never with a guessed z:

```sh
python3 <this skill's directory>/landscape.py place <place>/site.json 0 0 --footprint 1200,800 --heading 30
# location: [[0, 0, 34643], [0, 0, 1], 30]
# the ground falls 356.5 mm across the footprint: it stands on its highest corner
# it stands on a road, a path or water, 100 mm thick
```

It evaluates the ground's own surface - the B-spline OCCT builds, to the
micrometre - at points across the footprint turned by the heading, adds the
thickness of the road, path or water over each, and stands the object's base, at
the origin of its part, 1 mm above the highest of them: nothing of it is in the
ground, and nothing touches it along a face, which a boolean can take for one
solid inside the other.
It says how far the ground falls across the footprint; where that matters (a
vehicle that has to stand level, a robot's wheels), move the object to flatter
ground or say so. Where the footprint reaches into a building, a fence, a wall or
a hedge, it says `it is in: ...`: move the object. `landscape.py height site.json X Y` is
the height at a point.

Choose where from the top render: the middle of the area is kept clear of
scattered props (`--clear`), and the roads, paths and open ground are what most
tests want. A point of the map is a point of the frame: `fetch` printed the
origin, and the frame is metres east and north of it, times 1000.

Then validate the user's scene as `/pc:gen-scene` §6 does:

```sh
pc --no-ansi qual test -S test-on-<place>
```

Its overlap warnings are judged by what they touch. The props stand on the
ground and touch it, which is no overlap; a prop the map puts in a hedge, or
against a fence, can overlap it, and is left as the map has it. One between an
object under test and `ground` is the finding - the object is in the ground, a
building, a wall or a fence; render the two with `--filter` to see which.

The landscape is a scene inside the user's, and is checked as one: its own
inside first, once - every prop against the ground, a few seconds each, so a
few minutes for a city block - and kept against its hash; then only what the
user's scene adds, against it. Run `pc qual test -S <landscape scene>` once
after `package`, to pay for the first while nothing else waits on it.

**A simulation does not see this ground.** MuJoCo collides with each part's
convex hull, and `ground`'s hull is the block around the whole landscape: the
valleys filled, the buildings and the roads inside it. Simulate on a landscape fetched
with `--dem flat` and `--no-osm`, or in an area small and convex enough that its
hull is its shape, and say so. A height field, which MuJoCo has, is not yet
something PartCAD writes.

## 6. Keep it, change it

Commit the package with the user's: `site.json` is what it was made from, and
`landscape.py package <place>/site.json -o <place>` writes the same package from
it, offline. To change the props or the looks, run `package` again with other
options; to see the place as it is now, run `fetch` again. Never edit the
generated files: the next run writes over them.

What the data asks of whoever uses it is in the package's `docs:`: the elevation
model's attribution, OpenStreetMap's (© OpenStreetMap contributors, ODbL), and
each look's licence. A landscape shown publicly credits them.

## 7. Finalize

Summarize:

- the place, as Nominatim found it, the origin's latitude and longitude, the
  area's size, and the range of the ground's height;
- what the map had there, and what was left out (nothing is left out silently:
  the helper prints the counts);
- each prop's look and its licence, and the props drawn as themselves;
- where each object under test stands, and how far the ground falls under it;
- what `pc qual test` found;
- how to view it: `pc ide view -S <the user's scene>`.
