# Landscapes

How a piece of the real world becomes a PartCAD scene to test objects in: what other tools do, which formats and
public data there are, what may and may not be taken from Google, what `/pc:gen-landscape` does about it today, and
what the core could do next. Researched in November 2026; every source is linked where it is used.

## What other tools do

They share one pipeline: a place becomes a bounding box; an elevation model (a DEM, or a TIN's points) is fetched for
it, brought into a local metric frame and made a grid or a Delaunay mesh; imagery is draped on it; and OpenStreetMap
supplies the roads, the water and the buildings, extruded to the heights their tags give.

| Tool | What it does |
| --- | --- |
| Autodesk InfraWorks Model Builder | Bing imagery on the terrain; roads, railways, buildings and water from OSM ([help](https://help.autodesk.com/cloudhelp/2016/ENU/InfraWorks-UserHelp/files/GUID-071FB6F4-AE4A-4F3D-8869-9F39D9988561.htm)); its surfaces and Civil 3D's TIN surfaces convert into each other ([help](https://help.autodesk.com/cloudhelp/2020/ENU/Civil3D-UserGuide/files/GUID-854F25B0-845A-44B2-91DD-8A45829C08E4.htm)) |
| Revit Toposolid | made from an imported CAD file or a CSV of points, downsampled above a limit in `Revit.ini` ([help](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-Model/files/GUID-A1E1DE84-29AE-4B99-B377-091C0AC45249.htm)) |
| SketchUp Add Location | imagery, an optional terrain mesh and 3D buildings ([help](https://help.sketchup.com/site-context-add-location)); it stopped using Google's data in 2017 |
| Rhino/Grasshopper: Heron, Elk, Gismo | GDAL-read DEMs (HGT, IMG, ASCII grid, GeoTIFF), OpenTopography, OSM through Overpass ([Heron](https://github.com/blueherongis/Heron), [Gismo](https://github.com/stgeorges/gismo)) |
| Blender: BlenderGIS, Blosm | GeoTIFF DEMs, SRTM through OpenTopography, OSM, basemaps ([BlenderGIS](https://github.com/domlysz/BlenderGIS)); Blosm adds Google's 3D tiles, under Google's terms ([Blosm](https://github.com/vvoovv/blosm/wiki/Documentation)) |
| Unreal, Unity | a 16-bit greyscale PNG or a RAW heightmap ([Unreal](https://dev.epicgames.com/documentation/unreal-engine/landscape-technical-guide-in-unreal-engine), [Unity](https://docs.unity.com/en-us/engine/6000.3/manual/creating-environments/script-terrain/terrain-heightmaps)) |
| Cesium | quantized-mesh terrain and OGC 3D Tiles, whose tiles are glTF ([quantized-mesh](https://github.com/CesiumGS/quantized-mesh), [3D Tiles](https://github.com/CesiumGS/3d-tiles/tree/main/specification)) |
| QGIS | Qgis2threejs exports glTF, DEMto3D exports STL ([Qgis2threejs](https://plugins.qgis.org/plugins/Qgis2threejs/), [DEMto3D](https://plugins.qgis.org/plugins/DEMto3D/)) |
| FreeCAD | the GeoData workbench imports OSM, and SRTM as points |

## Formats

- **Elevation, as a raster**: GeoTIFF, and its cloud-optimized form COG ([cogeo.org](https://cogeo.org/)), which is
  read in byte ranges over HTTP and is how Copernicus publishes its DEM; SRTM's HGT (big-endian int16, 1x1 degree,
  named after its south-west corner); ESRI ASCII grid; DTED; IMG. And the tile encodings made for the web, regular
  PNGs: **Terrarium**, `height = R * 256 + G + B / 256 - 32768` metres
  ([spec](https://github.com/tilezen/joerd/blob/master/docs/formats.md)), and Mapbox's Terrain-RGB,
  `height = -10000 + (R * 65536 + G * 256 + B) * 0.1`.
- **Elevation, as points**: LAS/LAZ (USGS delivers LAS 1.4 as LAZ), COPC (an octree LAZ), E57.
- **Terrain as a surface**: LandXML surfaces (points and faces), IFC 4.3's `IfcGeographicElement` of type `TERRAIN`
  shaped as an `IfcTriangulatedIrregularNetwork`, CityGML and CityJSON 2.0 for a city with its buildings, and
  quantized-mesh or 3D Tiles for streaming.
- **What a CAD tool writes back**: glTF/GLB for a textured picture, STL for a print, STEP for CAD. A STEP with a
  B-rep face per triangle is very heavy; a regular grid is better written as one surface (below) or as AP242's
  tessellated geometry.

For a tool whose output is a STEP solid, a **regular grid** is what to read - a COG GeoTIFF or a Terrarium PNG - since
a closed solid is then the grid's surface, four walls and a base.

## Public data

| Source | Licence | Key | Notes |
| --- | --- | --- | --- |
| [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) | attribution per source dataset ([list](https://github.com/tilezen/joerd/blob/master/docs/attribution.md)) | no | `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, zoom 0-15 (about 4.8 m a pixel at the equator): SRTM, GMTED, ETOPO1, NED/3DEP, EU-DEM, UK LIDAR and others merged by Mapzen. What `/pc:gen-landscape` reads by default. |
| [Copernicus GLO-30/90](https://registry.opendata.aws/copernicus-dem/) | free, with a notice (© DLR / Airbus, under Copernicus) ([licence](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf)) | no | COG on S3, `copernicus-dem-30m/Copernicus_DSM_COG_10_N47_00_E008_00_DEM/...tif`. A surface model: it has the buildings and the trees in it. |
| SRTM GL1, NASADEM, ASTER GDEM v3 | public domain / no restrictions | Earthdata login | 30 m |
| ALOS AW3D30, FABDEM | JAXA's terms; FABDEM CC BY-NC-SA | account | FABDEM is bare earth, non-commercial |
| [USGS 3DEP](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer) | public domain | no | down to 1 m lidar in the USA: `exportImage?bbox=W,S,E,N&bboxSR=4326&size=W,H&format=tiff&pixelType=F32&f=image` (float32 TIFF), and a point query at `epqs.nationalmap.gov/v1/json` |
| [Open Topo Data](https://www.opentopodata.org) | per dataset | no | `api.opentopodata.org/v1/{dataset}?locations=lat,lon|...`, 100 points a request, 1 a second, 1000 a day: `ned10m`, `eudem25m`, `srtm30m`, `aster30m`, `mapzen`, ... `/pc:gen-landscape --dem opentopodata:<dataset>`. |
| [OpenTopography](https://opentopography.org/developers) | per dataset | yes, not to be shared or embedded | SRTM, AW3D30, NASADEM, COP30; 50 calls a day |
| National lidar: UK EA, France RGE ALTI, Netherlands AHN4 | OGL-like, Etalab 2.0, CC0 | no | 0.5-1 m; national projections, downloaded by area |
| Mapbox Terrain-RGB, MapTiler | their terms | token | |
| [OpenStreetMap](https://www.openstreetmap.org/copyright), through [Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) | ODbL: credit OSM; a database made of it stays ODbL | no | an identifying User-Agent; well under 10 000 queries a day; trees (`natural=tree`), roads (`highway`), buildings (`building`, `height`, `building:levels`), fences and walls (`barrier`), signs (`traffic_sign`), lamps, benches, water |
| [Nominatim](https://operations.osmfoundation.org/policies/nominatim/) | ODbL | no | address to latitude and longitude: at most 1 request a second, an identifying User-Agent, results cached, no bulk geocoding |
| Imagery: Sentinel-2, NAIP | free and open; public domain | no | to drape a texture, which PartCAD does not do yet |

Every elevation source has its own vertical datum (SRTM EGM96, Copernicus EGM2008, 3DEP NAVD88, Terrarium none
stated). Inside one landscape that does not matter - only differences of height do - and the absolute heights are
kept as a note, not used.

## Google Earth and Google's data

**Nothing Google-derived can be kept in a package.** In detail:

- **KML/KMZ** carries placemarks, paths, polygons, models and overlays - no terrain. What a user drew in Google
  Earth is theirs, and its coordinates are a fine way to say where a landscape is.
- **Google Earth's pictures** may be used non-commercially with attribution, and "you may not use output, or use third
  party tools to capture output, from Google Earth ... to reconstruct 3D models"
  ([geo guidelines](https://about.google/brand-resource-center/products-and-services/geo-guidelines/)).
- **Photorealistic 3D Tiles** (the Map Tiles API: a key, billing, attribution in the renderer) are for visualization:
  "geodata extraction" and "offline uses" are forbidden, and a model of one's own may be shown over them only if it
  was not "extracted, traced, or otherwise derived" from them ([policies](https://developers.google.com/maps/documentation/tile/policies)).
- **The Maps Platform terms**, §3.2.3: no exporting, extracting, scraping, pre-fetching, storing or rehosting Google
  Maps content, elevation values included, and no creating content from it - "build terrain models based on
  elevation values from the Elevation API" is the terms' own example ([terms](https://cloud.google.com/maps-platform/terms)).
- **The Elevation API** may not be cached or stored either ([policies](https://developers.google.com/maps/documentation/elevation/policies)).
- Add-ons that capture Google's 3D tiles into Blender (Blosm's import, MapsModelsImporter through RenderDoc) put
  their users under those terms, or say they are for education only.

So a landscape committed with a package can come from the open sources above and not from Google; a Google Maps link
or a KML is used for its coordinates only. (A reading of the terms, not legal advice.)

## What `/pc:gen-landscape` does

`ai-agents/common/skills/gen-landscape/`: a skill and its helper, `landscape.py`, standard-library Python with no GDAL
and no PartCAD. `fetch` geocodes an address with Nominatim (or takes a point or two corners), samples the AWS
Terrain Tiles (or Open Topo Data), asks Overpass for the map, and writes `site.json` in the scene's frame - mm, X
east, Y north, the origin at the centre, the lowest ground 1000 mm above z = 0. `package` writes a package of its
own: one build123d script for the ground and everything on it (one part, `ground`, one solid, each face painted
with `set_cmf`), one `basic` part per kind of prop with a `//pub` model as its `visual:`, and a `landscape` scene.
`place` gives the `location:` that stands an object on the ground, or on the road or path that covers it.

Four decisions made it fast and exact:

- **The ground is one cubic B-spline surface whose poles stand at the Greville abscissae of their knots.** A
  B-spline reproduces a straight line exactly with its poles there, so the surface's X and Y are linear in its
  parameters (u, v): it is a height field, and the helper evaluates z(x, y) exactly as OCCT does - to 0.000 mm over
  200 random points of a 250 m site - which is what `place` stands objects on. One smooth face is also what a STEP
  file, a hidden-line drawing and a shaded render each take best: the ground is six faces, not a hundred thousand
  triangles.
- **Draping is done in (u, v), not with booleans.** Since (x, y) to (u, v) is a scaling, a footprint drawn on the
  plan is the same polygon in the surface's parameters: a road's underside is a face trimmed on the ground's own
  surface by straight 2D edges, its top the same on the surface lifted by its thickness, its sides ruled, sewn into a
  solid. The only boolean is the footprint's union, on the plane. The first version cut each layer out of a slab
  with `BRepAlgoAPI_Common`; for the 25 roads of 250 m of San Francisco that took 205 s to fuse and 129 s to cut,
  and left the ground an unorientable shape. Done in (u, v), the roads take 11 s, the 109 buildings 1.8 s, and every
  layer is a valid solid.
- **The ground and everything on it is one solid, not a solid per layer.** Draped layers touch the ground along its
  surface, and a boolean between two solids that touch along a curved face is the slowest thing OCCT does: the
  terrain against its roads, against its buildings, the roads against the paths, each ran past 150 s and was
  stopped. As separate parts, `pc qual test`'s interference check intersected every such pair and did not finish in
  20 minutes; as the solids of one compound part, every prop checked against it cost 29 s, because the compound's
  own solids were intersected with each other each time. So the plan is cut into pieces where the layers' footprints
  meet (a General Fuse on the plane, which is quick), each piece rises to its level - the surface, a thickness above
  it, a roof - a riser stands wherever two pieces differ, and it is all sewn into one solid: 5 654 faces for the San
  Francisco block, built in 31 s, valid, each face painted as its layer, and a prop checked against it in 4 s.
- **A prop is the solid a check sees, drawn as a catalog model.** A tree is its trunk, a `basic` cylinder with a
  `height` parameter; its `visual:` is an alias of `//pub/collection/printables/models:556482`, offset so that its
  base's centre is the origin and scaled by `"%height / 20.513%"`, which works because a visual is asked for with the
  values of every parameter it shares with its part.

What the `//pub` collections offered, measured with `pc info`:

| Wanted | Found | Verdict |
| --- | --- | --- |
| tree | Printables 556482, a low-poly tree, 20.5 mm, standing on Z, CC-BY-SA | the default |
| traffic cone | NVIDIA SimReady `trafficcone_a01` (and 15 more cones), USD | good, but the NVIDIA Omniverse licence is not an open one: `--all-looks` |
| bollard, path lights, planters, benches, outdoor furniture | NVIDIA ArchVis residential (`CircularBollard`, `SquareBollard`, `Outdoors/Planters/*`, `Furniture/Outdoors/*`), commercial (`WaitingBench`, `WillowBench`) | the same licence |
| plants | NVIDIA ArchVis `Plants/*` (pot plants, a yucca) | indoor scale |
| trees, palms, rocks | the Moana Island Scene's elements (`isPalmRig`, `isIronwoodA1`, `isLavaRocks`, ...) | millions of triangles, 40-550 MB each, licensed for research only |
| a person, for scale | Pixar's `HumanFemale` | Pixar's licence: personal testing only |
| road signs | Printables 129303 (stop, 1:10), 910289 (German signs) | the best file is a flat plate, not a sign on a post |
| lamp post, park bench | Printables 868119, 251988 | the best file is one print piece laid flat (an arm, a seat) |
| boulder | Printables 443887 (a scanned rock), 1672830 | took longer than five minutes to build |

So the tree is drawn as a model by default, the cone and the bollard under `--all-looks`, and the rest as their
`basic` solids until somebody finds a model that is one file, standing up, openly licensed - the skill says how to
look. Fences, walls and hedges are not catalog objects at all: they follow the ground along their line, which a
straight panel cannot.

Measured on 250 x 250 m around Lombard Street, San Francisco (63 m of relief; 109 buildings, 25 roads, 103 paths,
21 hedges, 29 trees, 26 signs): `fetch` 47 s, most of it Overpass; the first render of the whole scene 60 s, and
23 s once its parts are cached; `pc qual test` of a scene placing that landscape and one object, 325 s the first time
- every one of the 72 props intersected with the ground - and 0.2 s after, from the cache. It reported what it
should: the object, placed before `place` stood things on the asphalt, 100 mm into a road; a hydrant the map puts
inside a hedge. One thing it reported was no overlap at all: a sign standing exactly on a road's top surface was
taken for a sign entirely inside the ground, which a millimetre of clearance under everything stood on cured.

## Limits, and what the core could do next

- **A simulation does not see the ground.** MuJoCo collides with convex hulls, and the hull of `ground` is the block
  around the whole landscape: its valleys filled, its buildings and roads inside. MuJoCo has height fields (`hfield`); a `terrain` part the sim plugins can
  write as one would make landscapes simulable. Until then, physics is for `--dem flat`.
- **A `terrain` part type** in `//builtin`, like `wall`: a heightmap file (GeoTIFF, ASCII grid, a 16-bit PNG, a
  Terrarium tile) or a `site.json` made into this surface by PartCAD itself, so that the ground is declared rather
  than generated as a script with its data inlined, and its heights could be asked of PartCAD (`pc` answering what
  `landscape.py height` answers).
- **A `landscape` scene type**, like `walls`: its links worked out from the map's features, as a `walls` scene's are
  from a sketch, so that a landscape is a declaration of where and how much rather than a generated file.
- **Checking a landscape still takes minutes.** Every prop is intersected with the whole ground, 4 s each against
  a ground of 5 600 faces; the landscape's verdict is taken once and cached against its hash, and a user's scene then
  only checks what crosses into it. A check of overlaps that first asked whether two shapes come within a tolerance
  of each other (`BRepExtrema`) before building a boolean, or a scene that could say its props stand on its ground (an
  `expected` pair, as a joint's `interferes` is), would make it seconds.
- **What an object runs into is `ground`**, whichever building, wall or fence it is: the price of one solid. A
  check that named the face it found the overlap on, and the colour that face is painted, would name it again.
- **Imagery**: Sentinel-2 or NAIP draped as a texture, which `texture_mapping` could carry.
- **Better elevation where it exists**: 3DEP's 1 m lidar in the USA, and national lidar elsewhere, through the
  float32 TIFF the 3DEP service exports or a COG reader.
