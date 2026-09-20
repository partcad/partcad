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

### What makes the third one manufacturable

`manufacturable: true` is a set of checks rather than a label:
`connectivity`, `interference` as a failure instead of a note, `connect`,
and `manufacturability`. The last is why the eight parts carry
`manufacturing: {method: subtractive}`, a `tolerance:` their STEP files
never stated, and a shop to cut them. And it earns a document:

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

# who cuts the eight milled parts, and for how much
pc supply quote AeroAssembly_assy_example/AeroFrame_Plate#1
```


<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
