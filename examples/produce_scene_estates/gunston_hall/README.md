# Gunston Hall

Gunston Hall (555.7 acres), its house as the Historic American Buildings Survey measured it: the outside one solid, the inside its rooms' walls and furniture, on the ground where it stands.

Gunston Hall: 555.7 acres, at 38.66407, -77.16018 (NRHP area in the Wikipedia infobox for Gunston Hall).
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
  skill), with what the survey's site plan shows of the grounds, less the house's own outline, with a level pad graded under the house at 26815.2 mm.
  The house stands a millimetre above it.

### What is approximate

- Dimensions from HABS VA-141 (1981) at 1/4"=1'-0"; plan pixels were converted with the dimensioned overall sizes (60'-10" and 40'-11 1/2"), so the two axes are scaled 11.60 and 11.68 mm/px respectively (0.7% difference between them on the scan).
- Room polygons are inside faces read off the plan at ~12 mm/pixel; labelled room sizes agree within ~50 mm. Rooms with fireplaces stop at the chimney-breast/closet face, as HABS measures them.
- Openings on the land and river fronts use the plan's dimension-chain ticks; heights come from the elevations (1/4"=1'-0", 11.5 mm/px) and section B-B level datums.
- First-floor ceiling height (3630) and second-floor ceiling (2600) are scaled from section B-B; interior door heights (2300) and second-floor door heights (2000) are assumptions.
- Second-floor room depths were registered by assuming the second-floor plan is symmetric about the ridge (Y=6242), because its sheet position differs from the first-floor sheet.
- Right (SW) gable windows on the second floor and the SW chimneys are taken as symmetric with the NE gable; the west elevation confirms three gable windows and a round window.
- Narrow windows flanking both doors: the elevation shows sash over a low railing; sill/head (1906/2886 above ground) are approximate.
- Porch floor height (1100) comes from the elevation's top step; the HABS first-floor datum is 965 - treat the 135 mm difference as a threshold step.
- Stoop on the NE gable and the SW cellar bulkhead are approximate outlines.
- Landscape items come from the 1"=60' site plan (171 mm/px) and are +/- 2 m.
- The rooms' walls are whole: a `walls` scene stands a wall on every edge of its outline and has no doorways yet, so a room's doors are measured - its furniture keeps clear of them - but not cut through its walls.


## Usage
```shell
pc render -t png --style shaded -S estate     # the house where it stands
pc render -t png --style shaded -S interior   # its rooms, furnished
pc qual test -S house                         # nothing inside it shares space with anything else
```

The scenes declare `timeout:`, so the examples' CI sweep (`--fast-only`) passes over them and their
pictures: render them here, where nothing is left out, with `./render_images.sh gunston_hall`, beside
`make_estate.py`. Each picture is a `render:` on the object it is of: `house` and `estate` leave
the inside out of theirs (`filter:`), which nobody outside sees.

### The ground from Google Earth instead

With a Google Maps Platform key of your own (`pc login //pub/collection/google-earth:google_earth_repo`;
see [partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth)), the ground
can be what Google Earth shows here, fetched with your key whenever it is built and kept nowhere:
link
`//pub/collection/google-earth/places:surface;lat=38.664070,lon=-77.160180,size=400` in place of `landscape`.
Its frame is this landscape's - X east, Y north, the house's middle at the origin - so the house's
`location` holds; stand it at the height `pc info` measures for the surface there.

### Sources

- [First floor plan, dimensioned](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_5_of_30).png): Public domain (HABS, US government work)
- [Second floor plan with room sizes](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_6_of_30).png): Public domain (HABS)
- [Basement plan](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_4_of_30).png): Public domain (HABS)
- [North (land-front) elevation](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_7_of_30).png): Public domain (HABS)
- [East (NE gable) elevation](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_8_of_30).png): Public domain (HABS)
- [South (river-front) elevation](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_9_of_30).png): Public domain (HABS)
- [West (SW gable) elevation](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_10_of_30).png): Public domain (HABS)
- [Porch details](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_11_of_30).png): Public domain (HABS)
- [Section A-A](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_29_of_30).png): Public domain (HABS)
- [Section B-B with level datums: ridge 33'-1", attic 25'-3", 2nd floor 16'-4", 1st floor 3'-2", basement -4'-2"](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_30_of_30).png): Public domain (HABS)
- [Site plan 1"=60'](https://commons.wikimedia.org/wiki/File:Gunston_Hall,_10709_Gunston_Road,_Lorton,_Fairfax_County,_VA_HABS_VA,30-LORT,1-_(sheet_2_of_30).png): Public domain (HABS)
- [Building outline used for centre and orientation only](https://www.openstreetmap.org/way/180143812): ODbL (OpenStreetMap contributors)
- [Acreage (infobox), coordinates cross-check, ownership](https://en.wikipedia.org/wiki/Gunston_Hall): CC BY-SA
- [Terrain samples in 'landscape.terrain_grid'](https://epqs.nationalmap.gov/v1/json): Public domain (USGS 3DEP)


## Scenes

### estate
<table><tr>
<td valign=top><a href="estate.assy"><img src="./images/estate.png" alt="estate" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Gunston Hall where it stands: the landscape, graded under the house, and the house.</td>
</tr></table>

### house
<table><tr>
<td valign=top><a href="house.assy"><img src="./images/house.png" alt="house" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Gunston Hall: its outside, one solid painted face by face, and its furnished inside within it.</td>
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
<td valign=top>Second floor (half storey in the roof), furnished: its floor, its rooms' walls, its furniture.</td>
</tr></table>

### storey-2-above
<table><tr>
<td valign=top><a href="storey-2-above.assy"><img src="./images/storey-2-above.png" alt="storey-2-above" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor (half storey in the roof) from above: its rooms' walls and furniture, as a plan.</td>
</tr></table>

## Sketches

### plan-1
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-1.svg" alt="plan-1" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>First floor, its plan: the outlines of its rooms, which their walls stand on - 1-1 Chamber (front-left, 17'-8" x 15'-6"); 1-2 Little Parlor (back-left, 17'-10 5/8" x 15'-7"); 1-3 Side (cross) passage to NE door; 1-4 Central Passage (12'-8" x 37'-4 1/4"); 1-5 Palladian Room (back-right, 19'-9" x 18'-7 3/4"); 1-6 Dining Room (front-right, 19'-11" x 17'-9 5/8").</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 1</li>
<li>room: </li>
</ul>
</td>
</tr></table>

### plan-2
<table><tr>
<td valign=top><a href="rooms.py"><img src="./images/plan-2.svg" alt="plan-2" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Second floor (half storey in the roof), its plan: the outlines of its rooms, which their walls stand on - 2-1 Front-left chamber (14'-1" x 11'-2 3/4"); 2-2 Front chamber 2 (12'-6 1/2" x 11'-2 7/8"); 2-3 Front chamber 3 (12'-6 3/4" x 11'-3 3/8"); 2-4 Front-right chamber (12'-9 5/8" x 11'-4 3/4"); 2-5 Back-left chamber (18'-9 1/2" x 11'-8 7/8"); 2-6 Upper stair hall (back centre); 2-7 Back-right chamber (20'-10 7/8" x 11'-8"); 2-8 Transverse passage (full length).</td>
<td valign=top>Parameters:<br/><ul>
<li>storey: 2</li>
<li>room: </li>
</ul>
</td>
</tr></table>

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
