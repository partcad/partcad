# Scotty's Castle (Death Valley Ranch, Main House)

Scotty's Castle (Death Valley Ranch, Main House) (1778 acres), its house as the Historic American Buildings Survey measured it: the outside one solid, the inside its rooms' walls and furniture, on the ground where it stands.

Scotty's Castle (Death Valley Ranch, Main House): 1778 acres, at 37.03226, -117.34146 (Wikipedia infobox for Scotty's Castle: historic district 719.57 ha).
Its house as the Historic American Buildings Survey measured it, everything worked out by
`../make_estate.py` from `estate.json` - what was read off the survey's drawings - and the ground
around it from the gen-landscape skill.

Its scenes nest, and each is pictured below: `estate`, the whole of it where it stands, then the house,
then each storey furnished and the same storey from above (`storey-<n>`, `storey-<n>-above`);
each storey's plan is a sketch, `plan-<n>`.

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
  skill), less the house's own outline, with a level pad graded under the house at 11832.1 mm.
  The house stands a millimetre above it.

### What is approximate

- All dimensions from HABS CA-2257-A (Scotty's Castle Recording Project, 1988) at 3/16"=1'-0"; 15.42 mm per pixel of the 3840-px thumbnails, confirmed by three dimension strings (98'-2", 33'-5", 24'-8") to <1%.
- Room rectangles are inside faces read off the plan; labelled sizes agree within ~0.3 m except the Spanish Sitting Room (see its note).
- The house's walls are not all rectangular in reality (stepped and battered stucco, rounded corners, octagonal bays). Rooms here are simplified rectangles; the solarium and dining bay are given as octagons.
- First-floor height above grade varies: about 1.5 m at the front steps (used as the datum here, estimated from the south elevation), less to the west and north where the ground is higher.
- Opening heights are scaled from the south elevation; windows on the north and side facades are approximate (sill 650-900, head 2300-2400).
- Interior door positions marked 'approx.' were inferred from door swings that are hard to read at this scale.
- Tower Y position, chimney Y positions and eaves height (7000) are estimates; the ridge (8408) is from the section's dimension string.
- The annex (north, across the patio) is only given as an outline from OSM; HABS has separate sheets for it (CA-2257-B) which were not used.
- 4 rooms drawn edge to edge, nearer each other than two thin walls, or out to the house's own outline, are moved in by up to a few centimetres, so that each has walls of its own and the outside stays whole.
- The rooms' walls are whole: a `walls` scene stands a wall on every edge of its outline and has no doorways yet, so a room's doors are measured - its furniture keeps clear of them - but not cut through its walls.


## Usage
```shell
pc render -t png --style shaded -S estate     # the house where it stands
pc render -t png --style shaded -S interior   # its rooms, furnished
pc qual test -S house                         # nothing inside it shares space with anything else
```

The scenes declare `timeout:`, so the examples' CI sweep (`--fast-only`) passes over them and their
pictures: render them here, where nothing is left out, with `./render_images.sh scottys_castle`, beside
`make_estate.py`. Each picture is a `render:` on the object it is of: `house` and `estate` leave
the inside out of theirs (`filter:`), which nobody outside sees.

### The ground from Google Earth instead

With a Google Maps Platform key of your own (`pc login //pub/collection/google-earth:google_earth_repo`;
see [partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth)), the ground
can be what Google Earth shows here, fetched with your key whenever it is built and kept nowhere:
link
`//pub/collection/google-earth/places:surface;lat=37.032260,lon=-117.341460,size=400` in place of `landscape`.
Its frame is this landscape's - X east, Y north, the house's middle at the origin - so the house's
`location` holds; stand it at the height `pc info` measures for the surface there.

### Sources

- [First floor plan with room sizes and 98'-2"/33'-5" dimensions](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_2_of_17).png): Public domain (HABS CA-2257-A, US government work)
- [Second floor plan, 97'-6"](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_4_of_17).png): Public domain (HABS)
- [Basement plan](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_1_of_17).png): Public domain (HABS)
- [South (entrance) elevation](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_6_of_17).png): Public domain (HABS)
- [West elevation](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_7_of_17).png): Public domain (HABS)
- [North (patio) elevation](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_8_of_17).png): Public domain (HABS)
- [East elevation](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_9_of_17).png): Public domain (HABS)
- [Section A-A with level datums: basement 0, first floor +10'-3 1/2", ceiling ridge +11'-3 3/8", second floor +1'-2 1/2", ceiling ridge +9'-4 1/8", roof ridge +5'-9"](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Main_House,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-A-_(sheet_10_of_17).png): Public domain (HABS)
- [Site plan, NW quadrant, 1"=20'](https://commons.wikimedia.org/wiki/File:Death_Valley_Ranch,_Death_Valley_Junction,_Inyo_County,_CA_HABS_CAL,14-DVNM,1-_(sheet_3_of_6).png): Public domain (HABS)
- [Outline used for location, orientation and the annex footprint](https://www.openstreetmap.org/way/123526241): ODbL (OpenStreetMap contributors)
- [Coordinates, area, ownership and status](https://en.wikipedia.org/wiki/Scotty%27s_Castle): CC BY-SA
- [Terrain samples](https://epqs.nationalmap.gov/v1/json): Public domain (USGS 3DEP)


## Scenes

### estate
<table><tr>
<td valign=top><a href="estate.assy"><img src="./images/estate.png" alt="estate" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Scotty's Castle (Death Valley Ranch, Main House) where it stands: the landscape, graded under the house, and the house.</td>
</tr></table>

### house
<table><tr>
<td valign=top><a href="house.assy"><img src="./images/house.png" alt="house" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Scotty's Castle (Death Valley Ranch, Main House): its outside, one solid painted face by face, and its furnished inside within it.</td>
</tr></table>

### storey-1
<table><tr>
<td valign=top><a href="storey-1.assy"><img src="./images/storey-1.png" alt="storey-1" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor, furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-1-above
<table><tr>
<td valign=top><a href="storey-1-above.assy"><img src="./images/storey-1-above.png" alt="storey-1-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

### storey-2
<table><tr>
<td valign=top><a href="storey-2.assy"><img src="./images/storey-2.png" alt="storey-2" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-2-above
<table><tr>
<td valign=top><a href="storey-2-above.assy"><img src="./images/storey-2-above.png" alt="storey-2-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

## Sketches

### plan-1
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-1.svg" alt="plan-1" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor, its plan: the outlines of its rooms, which their walls stand on - 1-1 Scotty's Bedroom (14'-10" x 25'-9"); 1-2 Lower Music Room (15'-2" x 25'-2"); 1-3 West passage (north); 1-4 Scotty's Bath; 1-5 West passage (south); 1-6 Living Hall (31'-1" x 31'-8"); 1-7 Stair hall (main stair, fountain alcove); 1-8 Service passage / telephone; 1-9 Kitchen (15'-3" x 25'-7"); 1-10 Dining Room (15'-1" x 25'-10"); 1-11 Solarium (17'-3" x 17'-3", octagonal).</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 1</li>
<li>room: </li>
</ul>
</td>
</tr></table>

### plan-2
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-2.svg" alt="plan-2" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor, its plan: the outlines of its rooms, which their walls stand on - 2-1 Spanish Bedroom (15'-2" x 15'-4"); 2-2 Bath (6'-4" x 10'-0"); 2-3 Closets; 2-4 Spanish Sitting Room (15'-4" x 25'-0" per label); 2-5 Gallery, west leg; 2-6 Gallery, north; 2-7 Gallery, south; 2-8 Gallery, east leg with stair; 2-9 Bath (6'-4" x 10'-0"); 2-10 Closet (8'-0" x 10'-0"); 2-11 Mr. Johnson's Room (15'-4" x 15'-4"); 2-12 Mrs. Johnson's Room (15'-2" x 25'-10").</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 2</li>
<li>room: </li>
</ul>
</td>
</tr></table>

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
