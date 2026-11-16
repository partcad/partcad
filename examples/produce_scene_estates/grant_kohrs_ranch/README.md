# Grant-Kohrs Ranch, Ranch House

Grant-Kohrs Ranch, Ranch House (1618 acres), its house as the Historic American Buildings Survey measured it: the outside one solid, the inside its rooms' walls and furniture, on the ground where it stands.

## Usage
Grant-Kohrs Ranch, Ranch House: 1618 acres, at 46.40827, -112.73868 (Wikipedia).
Its house as the Historic American Buildings Survey measured it, everything worked out by
`../make_estate.py` from `estate.json` - what was read off the survey's drawings - and the ground
around it from the gen-landscape skill.

![The estate where it stands: the house on its graded pad, in the landscape around it.](./images/outside.png)

![The house: its outside, one solid painted face by face.](./images/shell.png)

![Second floor, rear wing, furnished, drawn through the walls nearest the camera.](./images/storey-3.png)

![Second floor, rear wing from above: its rooms' walls and furniture.](./images/plan-3.png)

```shell
pc render -t png --style shaded -S estate     # the house where it stands
pc render -t png --style shaded -S interior   # its rooms, furnished
pc qual test -S house                         # nothing inside it shares space with anything else
```

- `shell` is the outside, one solid painted face by face: everything solid of the house -
  walls, roof, chimneys, dormers, porches, steps - less the air its rooms stand in, with every door
  and window cut through it. It is the house as it looks from outside, and stays as it is.
- Each room is a `walls` scene on its floor's outline (`room-<storey>-<n>`, on the sketch
  `plan-<storey>-<n>`): its walls as thick as its storey's thinnest partition lets them be, and
  under a roof only as high as the roof lets them stand. Where a room's walls reach into the outside
  walls, they are carved out of the shell, so the two never share space.
- Its furniture is NVIDIA's ArchVis and SimReady models from `//pub/collection/openusd`: each a
  `basic` part as large as `pc info` measured it and where it is - what a check collides with and a
  simulation moves - drawn as the model, set against the walls by what each room is for, clear of
  its doors.
- `landscape` is the ground around it and what OpenStreetMap maps on it (the gen-landscape
  skill), with what the survey's site plan shows of the grounds,, less the house's own outline, with a level pad graded under the house at 5143.4 mm.
  The house stands a millimetre above it.

The scenes declare `timeout:`, so the examples' CI sweep (`--fast-only`) passes them over: render
them here, where nothing is left out: `./render_images.sh grant_kohrs_ranch 3`, beside `make_estate.py`.

### The ground from Google Earth instead

With a Google Maps Platform key of your own (`pc login //pub/collection/google-earth:google_earth_repo`;
see [partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth)), the ground
can be what Google Earth shows here, fetched with your key whenever it is built and kept nowhere:
link
`//pub/collection/google-earth/places:surface;lat=46.408270,lon=-112.738680,size=400` in place of `landscape`.
Its frame is this landscape's - X east, Y north, the house's middle at the origin - so the house's
`location` holds; stand it at the height `pc info` measures for the surface there.

### What is approximate

- Scale: 7.61 mm per pixel of the 3840-px thumbnails. The plan scale bar (1/4"=1'-0"), the 66'-3" front and the 89'-0" overall depth agree; several labelled room sizes read ~3-5% larger than measured, so room polygons follow the drawing, not the labels.
- The elevation sheet's printed scale bar does not match the drawn building; elevation measurements were rescaled by matching the six front-window centres to the plan (7.7 mm/px horizontally, 7.4 mm/px vertically assumed; heights +/-5%).
- Floor levels are not dimensioned on the sheets used: first floor +300, second floors +3000 (front) and +3650 (wing) are estimates from window sills and the stair/steps.
- The second-floor sheet is the Commons JPEG rendering of a TIFF; it was registered to the first floor by the outside faces of the front wall and end walls (offset 17 px in X, 13 px in Y).
- Side windows of the front block were read on the north elevation and assumed the same on the south end (the parlor fireplace sits between them, as the plan shows).
- Wing south-side windows on the second floor are placed one per room at mid-length (not read individually). Chimney positions along the wing are approximate.
- Orientation (105 deg) is from imagery, not a survey; OSM has only a point for the house.
- 21 rooms drawn edge to edge, or nearer each other than two thin walls, are moved in by up to a few centimetres, so that each has walls of its own.

### Sources

- [First floor plan with room sizes](https://commons.wikimedia.org/wiki/File:First_Floor_Plan_-_Grant-Kohrs_Ranch,_Ranch_House,_Highway_10,_Deer_Lodge,_Powell_County,_MT_HABS_MONT,39-DELO,1-A-_(sheet_2_of_5).png): Public domain (HABS MT-39-A, US government work)
- [Second floor plan with 23'-5"/19'-7"/23'-3" and 89'-0" dimensions (second_floor_plan.jpg, Commons JPEG rendering of the TIFF)](https://commons.wikimedia.org/wiki/File:Second_Floor_Plan_-_Grant-Kohrs_Ranch,_Ranch_House,_Highway_10,_Deer_Lodge,_Powell_County,_MT_HABS_MONT,39-DELO,1-A-_(sheet_3_of_5).tif): Public domain (HABS)
- [Basement plan](https://commons.wikimedia.org/wiki/File:Basement_Plan_-_Grant-Kohrs_Ranch,_Ranch_House,_Highway_10,_Deer_Lodge,_Powell_County,_MT_HABS_MONT,39-DELO,1-A-_(sheet_1_of_5).png): Public domain (HABS)
- [East (front) and north elevations](https://commons.wikimedia.org/wiki/File:East_and_North_Elevations_-_Grant-Kohrs_Ranch,_Ranch_House,_Highway_10,_Deer_Lodge,_Powell_County,_MT_HABS_MONT,39-DELO,1-A-_(sheet_4_of_5).png): Public domain (HABS)
- [South and west elevations](https://commons.wikimedia.org/wiki/File:South_and_West_Elevations_-_Grant-Kohrs_Ranch,_Ranch_House,_Highway_10,_Deer_Lodge,_Powell_County,_MT_HABS_MONT,39-DELO,1-A-_(sheet_5_of_5).png): Public domain (HABS)
- [House location](https://www.openstreetmap.org/node/848249342): ODbL (OpenStreetMap contributors)
- [Location and orientation check](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer): Esri World Imagery (viewing only; nothing copied into the model)
- [Acreage, ownership](https://en.wikipedia.org/wiki/Grant%E2%80%93Kohrs_Ranch_National_Historic_Site): CC BY-SA
- [Terrain samples](https://epqs.nationalmap.gov/v1/json): Public domain (USGS 3DEP)


## Sketches

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
