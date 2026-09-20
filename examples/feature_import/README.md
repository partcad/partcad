# //pub/examples/partcad/feature_import

PartCAD example project that takes one imported STEP assembly from a record of a file to something that can be built, in three stages - and defines a part from an STL file.

## One STEP file, three stages

`AeroAssembly.step` is a STEP assembly read by `pc import assembly`. The
eight solids it holds are committed as parts, and the tree they came in is
committed three times. The three share every part file - not one differs -
and what separates them is what each is able to say:

| | | establishes | does not establish |
|---|---|---|---|
| 1 | `AeroAssembly` | what the file contains | whether any of it is right |
| 2 | `AeroAssembly_corrected` | that the geometry is consistent | what holds any of it |
| 3 | `AeroAssembly_connected` | how it goes together, and that it can | |

### 1. Import

`pc import assembly` writes one `location:` per solid, at five decimals.
That file is committed unedited and is never adjusted to make a check pass:
its value is that it is evidence. `partcad.test.interference` reports three
overlaps in it, and each is a different kind of mistake:

* **90.231 mm^3** - the cap's two front feet are modelled 0.751923 mm too
  long for the faces they land on. A defect in a part: no rigid motion of
  it seats all four feet.
* **12.997 mm^3** - the mirrored frame half sits (7.728713, -3.380867,
  2.583602) mm off its own footprint, because the exporter folded the
  plate's origin offset into the mirrored branch instead of reflecting it.
  A misplaced instance.
* **0.161 mm^3** - not in the STEP file at all. It is the importer's own
  five-decimal rounding of a rotation axis, 0.56 um thick on a face 257 mm
  from the axis it turns about.

None of the three is an overlap a joint means to have, so none is something
`selfScrew`, `snapIn` or `interferes` could state. Stage 1 says
`manufacturable: false`, which is what it is.

### 2. Correct

`AeroAssembly_corrected` changes three placements and nothing else; the
arithmetic behind each is beside it in `AeroAssembly_corrected.assy`.
Afterwards no two of the eight parts share any volume - the worst of the 28
pairs is 0.000000000 mm^3.

That is worth having and it is not the same as being buildable. Every item
is still placed by `location:`, and a coordinate says where a part ends up
without saying what keeps it there. Nothing here knows that the front foot
is bolted to the flange rather than resting on it, nothing says which part
goes on before which, and nothing would notice if the plate moved and the
other seven did not.

### 3. Connect

`AeroAssembly_connected` carries no `location:` at all. The plate is placed
by being first; each of the other seven names what it is joined to, the
interface it is joined by, and - in `how:` - what somebody has to do to make
that joint. `partcad.test.connectivity` holds a manufacturable assembly to
exactly that.

Every Ø3 hole in these parts is a clearance hole a bolt passes through, not
a tapped one and not a tapping drill, which in
[`//pub/std/metric/m`](https://github.com/partcad/partcad-standard-metric-m)
is `m-opening` - with the metal it goes through stated,
`m-thru-depth;size=3,depth=<t>`. `aero-plate-opening` (7 mm) and
`aero-foot-opening` (8 mm) are aliases of that and nothing more. Two things
the standard package has no interface for are local: `aero-strut-opening`,
which is the same hole in 6 mm of plate plus the 14 mm of `moveZ` by which
the strut's flange stands off the seat it rests on; and `aero-cap-seat`,
because a flat seat is not a feature anything passes through.

Naming the joints says what coordinates could not. The plate's rear flange
holes and the rear feet's **miss each other by 2.5 mm**, one half each way,
in the source file. Both patterns are declared on the parts and nothing
connects through them: the rear foot hangs from the strut and bears on the
flange. The cap is seated on the two front feet that touch, by name, which
leaves the other pair 0.751923 mm clear - where a fitter puts a shim.

### What the file never said

Everything above is about where the eight solids are. What they *are* is a
separate question, and `AeroAssembly.step` does not answer it. It is AP214
written by FreeCAD, and in 24540 lines it carries eight solids, the tree
they hang in, the names of the products, millimetres, and one colour used
for all eight. There is no `MATERIAL_DESIGNATION` in it, no
`PROPERTY_DEFINITION`, no `DESCRIPTIVE_REPRESENTATION_ITEM`, no GD&T - AP242
carries the whole of that and this is not AP242 - and nothing anywhere about
stock or process. The one colour it does carry is a FreeCAD default on all
eight solids, so even that says nothing about what they are made of.

So four things on every part below were supplied rather than imported:
`properties.material`, `tolerance:`, `manufacturing.method`, and - on the
seven that are cut - `manufacturing.source`. An import that ended at
geometry would leave a bill of materials with nothing in it but shapes.

### Cut, or formed

`method:` is a claim about a part, and the part's own geometry is the
evidence for it. Seven of the eight are `subtractive`; the cap is not, and
the reason is measurable:

| | cut away | reading |
|---|---|---|
| the plate, the four feet, the two struts | 76 - 89% of the billet | a machined part |
| `AeroFrame_Cap` | 97.2% of a 215 x 75 x 67 billet | nobody mills this |

Every curved face of the cap is one of a concentric pair 3 mm apart about a
single axis - r17 inside r20, r22 inside r25. That is a 3 mm strip bent, and
it is why the cap says `method: forming`. It does not say `sheet_metal`,
which would name the flat piece that goes into the brake and a sketch of
where the bends are: the file holds the bent shape and nothing about how it
got there, which is the same gap as the missing material said about a
process.

No part names a machine, and that is measured too. A `laser:` or a `drill:`
claims every face is a wall along the tool axis or a face across it, and no
axis of any of these solids gets past 94.5% of the surface area - the feet
and the struts do not get past 62%, because a third of their area is ruled
spline flank. Naming no machine means CNC, the one that can make what the
other two can.

### The stock

`source:` is the other half of `subtractive`: cutting only ever removes
material, so a part that names no stock has not said what the method means.
An import has no stock to name - the STEP file is the finished shape - so
`stock.py` derives one per part: the smallest rectangular billet that holds
the solid, **in the solid's own orientation**, plus 2 mm of machining
allowance a face, rounded up to 1 mm of plate thickness and 5 mm of sawn
length.

The orientation is the whole of why it is derived rather than typed out. An
imported solid sits where the STEP file put it, at an angle to all three
axes, so the box that is square with the coordinate system is not the box
anybody saws: across these seven it is 2.4 times the metal, and 3.5 times
for the mirrored strut. `pc test` then checks both halves of the relation -
nothing of the part outside the stock, and the stock bigger than the part
somewhere - so a `source:` that points back at the part is caught rather
than believed.

### What makes the third one manufacturable

`manufacturable: true` is a set of checks rather than a label:
`connectivity`, `interference` as a failure instead of a note, `connect`,
and `manufacturability`. The last is why the three sections above exist -
a method, a stock, a material, a tolerance and a shop that will take the
job. And it earns a document:

```shell
pc render -t pdf -a AeroAssembly_assy_example/AeroAssembly_connected
```

`assembly_guide.py` refuses to write one for an assembly that is not
manufacturable, and has nothing to write for one placed by coordinates: the
steps, their order, the two items each joins and the direction they come
apart all come from `connect:`. The result is checked in as
[`AeroAssembly_connected.pdf`](./AeroAssembly_assy_example/AeroAssembly_connected.pdf).


## Usage
```shell
# the three stages
pc inspect -a AeroAssembly_assy_example/AeroAssembly
pc inspect -a AeroAssembly_assy_example/AeroAssembly_corrected
pc inspect -a AeroAssembly_assy_example/AeroAssembly_connected

# what each stage is held to
pc test -a AeroAssembly_assy_example/AeroAssembly_connected

# where the ports are, and which interface each belongs to
pc render -t svg --with-all AeroAssembly_assy_example/AeroFrame_Plate

# the assembly instructions, which only stage 3 has
pc render -t pdf -a AeroAssembly_assy_example/AeroAssembly_connected

# the billet a part is cut out of, and the part beside it
pc inspect AeroAssembly_assy_example/AeroFrame_Plate_stock
pc inspect AeroAssembly_assy_example/AeroFrame_Plate

# that each part is what is left of the stock it names
pc test -f manufacturability AeroAssembly_assy_example/AeroFrame_Plate

# who makes the eight parts, and for how much
pc supply quote AeroAssembly_assy_example/AeroFrame_Plate#1
```


<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
