# Google Earth for PartCAD

Places in Google Earth, as parts, published as `//pub/collection/google-earth`. A part here is
a **reference** to a place: its kind, its middle and its size, and nothing else. It is made when
it is built, from Google's data, fetched with **your own Google Maps Platform key**, under
Google's terms, which you accept for yourself when you get that key.

| Part | What it is | From | Built as |
| --- | --- | --- | --- |
| `elevation` | the ground | the [Elevation API](https://developers.google.com/maps/documentation/elevation) | a `heightmap`: a solid, a box below and the ground on top |
| `surface` | what stands there - buildings, trees - as Google Earth shows it | the [Photorealistic 3D Tiles](https://developers.google.com/maps/documentation/tile/3d-tiles) | a `heightmap`: the highest point of the mesh over each cell; drawn as `tiles` |
| `tiles` | Google Earth's mesh itself, in the place's frame | the Photorealistic 3D Tiles | a `gltf`: a surface, not a solid |

Each is one script, `google_earth_repo.py`, serving the package's external dependency `places`
(the protocol is PartCAD's repository plugin's; see "Repositories" in PartCAD's
`config_package.rst`). Every part is a solid you can place, measure, simulate and export -
`surface` is the one to put a scene on, and a picture of it is drawn with Google Earth's own
mesh (`visual: tiles`).

## Setting it up

In the [Google Cloud console](https://console.cloud.google.com/google/maps-apis/credentials):
create a project with billing, enable the **Elevation API**, the **Map Tiles API** and the
**Geocoding API**, create an API key, and restrict it to those three. Then:

```shell
pc login //pub/collection/google-earth:google_earth_repo
```

which asks for the key (or `pc login --agent ... --set api_key=...`, or `GOOGLE_MAPS_API_KEY` in
the environment the plugin runs in) and checks that Google takes it. PartCAD keeps it in your
`~/.partcad/config.yaml`, never in a package.

## Using it

A name says the place: `lat` and `lon`, its middle, in degrees; `size`, its width x depth in
metres (`300`, or `400x300`). Then, per part:

* `elevation`: `samples`, the heights along the longer side (64; 2 to 512).
* `surface` and `tiles`: `resolution`, the surface model's cell in metres (1); `error`, the
  coarsest geometric error of the tiles read, in metres (1); `base`, how far the lowest of the
  surface stands above z = 0, in **millimetres** (1000) - the `heightmap` type's own, in its
  own unit, so that the `tiles` a `surface` is drawn as stand where it does.

```shell
pc search parts -P //pub/collection/google-earth/places -k "Mount Vernon, Virginia"
pc inspect "//pub/collection/google-earth/places:surface;lat=38.708300,lon=-77.086300,size=300"
```

and, in a scene - `site.assy`:

```yaml
links:
  - part: //pub/collection/google-earth/places:surface;lat=38.708300,lon=-77.086300,resolution=0.5,size=300
    name: ground
    fixed: true
```

with `partcad.yaml` saying:

```yaml
scenes:
  site:
    type: assy
    path: site.assy
    gravity: [0, 0, -9.81]
```

Exported to MuJoCo, both `heightmap` parts are written as an `<hfield>`, which MuJoCo collides
with as the surface it is (see the `partcad-sim-mujoco` plugin).

## Google's terms

Nothing of Google's is in this package: a part is a reference until whoever builds it fetches
it, with their key. And nothing fetched is kept:

* the package's `meta` says `"persist": false`, so PartCAD keeps what this plugin answers in the
  memory of the process that fetched it and writes none of it to disk; a file it serves is
  written only because a part type reads a path, and is removed when the process exits;
* every part says `cache: false`, so what is built of it is not kept either.

Every part carries a link to the place in Google Earth (`url`) and Google's attribution
(`desc`); show it wherever you show the part.

## What it cannot do (yet)

* **Untested against Google.** The tests answer Google from tables, in the shapes Google's
  documentation gives; nothing here has fetched a real place yet.
* **One mesh, no textures.** Google's tiles are textured; `tiles` is their geometry only.
* **At most 600 tiles a place** (`earth.MAX_TILES`): a few hundred metres at a metre's error.
  A larger place needs a larger `error`.
* The Elevation API is sampled at 400 points a request, each a billed request.

## Tests

```shell
pip install partcad pytest DracoPy==2.1.0
pytest
```

Nothing in them touches the network. Without DracoPy the one test of a Draco-compressed tile
is skipped.
