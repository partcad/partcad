# Scotty's Castle (Death Valley Ranch, Main House)

Scotty's Castle (Death Valley Ranch, Main House) (1778 acres), its house as the Historic American Buildings Survey measured it: the outside one solid, the inside its rooms' walls and furniture, on the ground where it stands.

## Usage
Scotty's Castle (Death Valley Ranch, Main House): 1778 acres, at 37.03226, -117.34146 (Wikipedia infobox for Scotty's Castle: historic district 719.57 ha).
Its house as the Historic American Buildings Survey measured it, everything worked out by
`../make_estate.py` from `estate.json` - what was read off the survey's drawings - and the ground
around it from the gen-landscape skill.

![The estate where it stands: the house on its graded pad, in the landscape around it.](./images/outside.png)

![The house: its outside, one solid painted face by face.](./images/shell.png)

![Second floor, furnished, drawn through the walls nearest the camera.](./images/storey-2.png)

![Second floor from above: its rooms' walls and furniture.](./images/plan-2.png)

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
  skill), less the house's own outline, with a level pad graded under the house at 11832.1 mm.
  The house stands a millimetre above it.

The scenes declare `timeout:`, so the examples' CI sweep (`--fast-only`) passes them over: render
them here, where nothing is left out: `./render_images.sh scottys_castle 2`, beside `make_estate.py`.

### The ground from Google Earth instead

With a Google Maps Platform key of your own (`pc login //pub/collection/google-earth:google_earth_repo`;
see [partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth)), the ground
can be what Google Earth shows here, fetched with your key whenever it is built and kept nowhere:
link
`//pub/collection/google-earth/places:surface;lat=37.032260,lon=-117.341460,size=400` in place of `landscape`.
Its frame is this landscape's - X east, Y north, the house's middle at the origin - so the house's
`location` holds; stand it at the height `pc info` measures for the surface there.

### What is approximate

- All dimensions from HABS CA-2257-A (Scotty's Castle Recording Project, 1988) at 3/16"=1'-0"; 15.42 mm per pixel of the 3840-px thumbnails, confirmed by three dimension strings (98'-2", 33'-5", 24'-8") to <1%.
- Room rectangles are inside faces read off the plan; labelled sizes agree within ~0.3 m except the Spanish Sitting Room (see its note).
- The house's walls are not all rectangular in reality (stepped and battered stucco, rounded corners, octagonal bays). Rooms here are simplified rectangles; the solarium and dining bay are given as octagons.
- First-floor height above grade varies: about 1.5 m at the front steps (used as the datum here, estimated from the south elevation), less to the west and north where the ground is higher.
- Opening heights are scaled from the south elevation; windows on the north and side facades are approximate (sill 650-900, head 2300-2400).
- Interior door positions marked 'approx.' were inferred from door swings that are hard to read at this scale.
- Tower Y position, chimney Y positions and eaves height (7000) are estimates; the ridge (8408) is from the section's dimension string.
- The annex (north, across the patio) is only given as an outline from OSM; HABS has separate sheets for it (CA-2257-B) which were not used.
- 4 rooms drawn edge to edge, or nearer each other than two thin walls, are moved in by up to a few centimetres, so that each has walls of its own.

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


## Sketches

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
