# Grant-Kohrs Ranch, Ranch House

Grant-Kohrs Ranch, Ranch House (1618 acres), its house as the Historic American Buildings Survey measured it: the outside one solid, the inside its rooms' walls and furniture, on the ground where it stands.

Grant-Kohrs Ranch, Ranch House: 1618 acres, at 46.40827, -112.73868 (Wikipedia).
Its house as the Historic American Buildings Survey measured it, everything worked out by
`../make_estate.py` from `estate.json` - what was read off the survey's drawings - and the ground
around it from the gen-landscape skill.

Its scenes nest, and each is pictured below: `estate`, the whole of it where it stands, then the house,
then each storey furnished and the same storey from above (`storey-<n>`, `storey-<n>-above`);
each storey's plan is a sketch, `plan-<n>`.

First floor has more furniture than one picture has memory for, and is pictured in parts, each a scene
which the storey's own places: its rooms in the house's main block (`storey-<n>-main`), its
largest wing (`-wing`) where the rest is more than one picture too, and the rest (`-wings`).

- `shell` is the outside, one solid painted face by face: everything solid of the house -
  walls, roof, chimneys, dormers, porches, steps - less the air its rooms stand in, with every door
  and window cut through it. It is the house as it looks from outside, and stays as it is.
- Each storey's plan, `plan-<storey>`, is the outlines of all of its rooms, which are on its
  level; `plan-<storey>;room=<storey>-<n>` is one of them alone.
- Each room is a `walls` scene on its outline (`room-<storey>-<n>`): its walls as thick as its
  storey's thinnest partition lets them be, and under a roof only as high as the roof lets them
  stand. Where a room's walls reach into the outside walls, they are carved out of the shell, so the
  two never share space.
- Its furniture is NVIDIA's ArchVis and SimReady models from `//pub/collection/openusd`: each a
  `basic` part as large as `pc info` measured it and where it is - what a check collides with and a
  simulation moves - drawn as the model, set against the walls by what each room is for, clear of
  its doors.
- `landscape` is the ground around it and what OpenStreetMap maps on it (the gen-landscape
  skill), with what the survey's site plan shows of the grounds, less the house's own outline, with a level pad graded under the house at 5143.4 mm.
  The house stands a millimetre above it.

### What is approximate

- Scale: 7.61 mm per pixel of the 3840-px thumbnails. The plan scale bar (1/4"=1'-0"), the 66'-3" front and the 89'-0" overall depth agree; several labelled room sizes read ~3-5% larger than measured, so room polygons follow the drawing, not the labels.
- The elevation sheet's printed scale bar does not match the drawn building; elevation measurements were rescaled by matching the six front-window centres to the plan (7.7 mm/px horizontally, 7.4 mm/px vertically assumed; heights +/-5%).
- Floor levels are not dimensioned on the sheets used: first floor +300, second floors +3000 (front) and +3650 (wing) are estimates from window sills and the stair/steps.
- The second-floor sheet is the Commons JPEG rendering of a TIFF; it was registered to the first floor by the outside faces of the front wall and end walls (offset 17 px in X, 13 px in Y).
- Side windows of the front block were read on the north elevation and assumed the same on the south end (the parlor fireplace sits between them, as the plan shows).
- Wing south-side windows on the second floor are placed one per room at mid-length (not read individually). Chimney positions along the wing are approximate.
- Orientation (105 deg) is from imagery, not a survey; OSM has only a point for the house.
- 23 rooms drawn edge to edge, nearer each other than two thin walls, or out to the house's own outline, are moved in by up to a few centimetres, so that each has walls of its own and the outside stays whole.
- The rooms' walls are whole: a `walls` scene stands a wall on every edge of its outline and has no doorways yet, so a room's doors are measured - its furniture keeps clear of them - but not cut through its walls.


## Usage
```shell
pc render -t png --style shaded -S estate     # the house where it stands
pc render -t png --style shaded -S interior   # its rooms, furnished
pc qual test -S house                         # nothing inside it shares space with anything else
```

The scenes declare `timeout:`, so the examples' CI sweep (`--fast-only`) passes over them and their
pictures: render them here, where nothing is left out, with `./render_images.sh grant_kohrs_ranch`, beside
`make_estate.py`. Each picture is a `render:` on the object it is of: `house` and `estate` leave
the inside out of theirs (`filter:`), which nobody outside sees.

### The ground from Google Earth instead

With a Google Maps Platform key of your own (`pc login //pub/collection/google-earth:google_earth_repo`;
see [partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth)), the ground
can be what Google Earth shows here, fetched with your key whenever it is built and kept nowhere:
link
`//pub/collection/google-earth/places:surface;lat=46.408270,lon=-112.738680,size=400` in place of `landscape`.
Its frame is this landscape's - X east, Y north, the house's middle at the origin - so the house's
`location` holds; stand it at the height `pc info` measures for the surface there.

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


## Scenes

### estate
<table><tr>
<td valign=top><a href="estate.assy"><img src="./images/estate.png" alt="estate" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Grant-Kohrs Ranch, Ranch House where it stands: the landscape, graded under the house, and the house.</td>
</tr></table>

### house
<table><tr>
<td valign=top><a href="house.assy"><img src="./images/house.png" alt="house" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Grant-Kohrs Ranch, Ranch House: its outside, one solid painted face by face, and its furnished inside within it.</td>
</tr></table>

### storey-1-main
<table><tr>
<td valign=top><a href="storey-1-main.assy"><img src="./images/storey-1-main.png" alt="storey-1-main" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor (main block), furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-1-main-above
<table><tr>
<td valign=top><a href="storey-1-main-above.assy"><img src="./images/storey-1-main-above.png" alt="storey-1-main-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor (main block) from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

### storey-1-wing
<table><tr>
<td valign=top><a href="storey-1-wing.assy"><img src="./images/storey-1-wing.png" alt="storey-1-wing" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor (rear wing), furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-1-wing-above
<table><tr>
<td valign=top><a href="storey-1-wing-above.assy"><img src="./images/storey-1-wing-above.png" alt="storey-1-wing-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor (rear wing) from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

### storey-1-wings
<table><tr>
<td valign=top><a href="storey-1-wings.assy"><img src="./images/storey-1-wings.png" alt="storey-1-wings" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor (other wings), furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-1-wings-above
<table><tr>
<td valign=top><a href="storey-1-wings-above.assy"><img src="./images/storey-1-wings-above.png" alt="storey-1-wings-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor (other wings) from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

### storey-2
<table><tr>
<td valign=top><a href="storey-2.assy"><img src="./images/storey-2.png" alt="storey-2" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, front block (half storey), furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-2-above
<table><tr>
<td valign=top><a href="storey-2-above.assy"><img src="./images/storey-2-above.png" alt="storey-2-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, front block (half storey) from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

### storey-3
<table><tr>
<td valign=top><a href="storey-3.assy"><img src="./images/storey-3.png" alt="storey-3" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, rear wing, furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-3-above
<table><tr>
<td valign=top><a href="storey-3-above.assy"><img src="./images/storey-3-above.png" alt="storey-3-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, rear wing from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

## Sketches

### plan-1
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-1.svg" alt="plan-1" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor, its plan: the outlines of its rooms, which their walls stand on - 1-1 Parlor (19'-4" x 18'-0"); 1-2 Music Room (19'-4" x 10'-3"); 1-3 Front Hall with stair; 1-4 Office (13'-6" x 14'-9"); 1-5 Store Room; 1-6 Master Bedroom (19'-4" x 13'-6"); 1-7 Bedroom, rear left (11'-0" x 16'-7"); 1-8 Sitting Room (22'-6" x 21'-2"); 1-9 Bath (11'-3" x 10'-0"); 1-10 Bedroom, rear right (11'-3" x 14'-7"); 1-11 Vestibule (11'-3" x 7'-9"); 1-12 Flower House (22'-6" x 8'-0"); 1-13 Kitchen (13'-6" x 21'-3"); 1-14 Pantry (6'-11" x 14'-11"); 1-15 Dining Room (24'-2" x 19'-3"); 1-16 Back Hall with service stair.</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 1</li>
<li>room: </li>
</ul>
</td>
</tr></table>

### plan-2
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-2.svg" alt="plan-2" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, front block (half storey), its plan: the outlines of its rooms, which their walls stand on - 2-1 Bedroom (19'-2" x 17'-8"); 2-2 Bedroom (19'-6" x 10'-6"); 2-3 Stair (down); 2-4 Trunk Room (12'-3" x 9'-4"); 2-5 Bedroom (12'-7" x 10'-7"); 2-6 Bedroom (17'-3" x 11'-3"); 2-7 Front Hall (upper).</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 2</li>
<li>room: </li>
</ul>
</td>
</tr></table>

### plan-3
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-3.svg" alt="plan-3" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, rear wing, its plan: the outlines of its rooms, which their walls stand on - 3-1 Apartment Kitchen (10'-3" x 11'-9"); 3-2 Bath; 3-3 Apartment Living Room (11'-6" x 14'-8"); 3-4 Apartment Bedroom (13'-2" x 14'-8"); 3-5 Bedroom (12'-4" x 14'-8"); 3-6 Bedroom (12'-3" x 14'-8"); 3-7 Back Hall (upper) with stair.</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 3</li>
<li>room: </li>
</ul>
</td>
</tr></table>

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
