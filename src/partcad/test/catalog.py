#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What each check `pc test` runs is, when it applies, and what to do when it fails.

Written once, here, and read in two places that must not disagree: the IDE's
Test tab, which shows the entry of the check selected beside its verdict (see
'partcad.test.report'), and the documentation, whose list of checks
('docs/source/digital_thread/testing.rst') is generated from this module. A
test keeps the two in step ('tests/partcad/unit/test_test_catalog.py'): every
check in 'partcad.test.all' has an entry and nothing else does, and the page
says what 'rst()' writes.

    poetry run python -m partcad.test.catalog --write    # after editing an entry

An entry is a title -- what the check asks, in a few words -- what it applies to,
and a text in a small markup both readers render the same way:

- blocks are separated by blank lines;
- a block starting with '### ' is a heading;
- a block of lines starting with '- ' is a list, an item continuing on lines
  indented by two spaces;
- a block between two lines of three backticks is code, in the language named
  after the first;
- anything else is a paragraph, its lines joined;
- inside a paragraph or an item, text between backticks is code.

Nothing else is interpreted, by either reader.
"""

import re
import sys
import typing

# The headings every entry is written with, so that the same question is found
# in the same place in each of them.
APPLIES = "When it does not apply"
FAILS = "When it fails"
SETTINGS = "Settings"


class Entry:
    def __init__(self, title: str, applies: str, text: str):
        self.title = title
        self.applies = applies
        self.text = text


TESTS: typing.Dict[str, Entry] = {
    "cad": Entry(
        "Builds",
        "every part, assembly, scene and sketch",
        """
Whether the object builds: its script runs, its file reads, its assembly puts
together, and something comes out. It is the first question, and every other
check that looks at geometry takes it as answered - a check that finds no shape
to measure passes and leaves the failure here, so that one broken object is one
failure and not a dozen.

### When it does not apply

Never: everything PartCAD tests is built first.

### When it fails

- `Failed to get the shape`: building it produced nothing. The reason is in the
  log above the verdict - the error the script raised, the file that could not
  be read or fetched, the link of an assembly that names an object nobody
  declares. Build it on its own to see it again: `pc --no-ansi info <object>`
  or `pc --no-ansi render -t png <object>`.
- A verdict remembered from an earlier run is said again with "remembered from
  an earlier run": once the cause is fixed, `pc --cache-bypass test` asks again
  rather than reading the cache.
""",
    ),
    "manufacturability": Entry(
        "Can be made or bought",
        "every object that does not say `manufacturable: false`",
        """
Whether the object can be had: bought from somebody who sells it, or made by a
method it declares. It asks for exactly what `pc supply` would order and what
`pc instructions` would tell somebody to do.

- Every object has to be reproducible: one read from a file the package fetches
  (`fileFrom:`) has to pin the file with `fileHash:`, or name a vendor and SKU to
  order it by, so that it is known which bytes it is made from.
- A part is bought (`vendor:` and `sku:`, and a supplier that carries it) or made
  (`manufacturing:` with a `method:`). A part that is made needs a manufacturing
  tolerance, and the stock it is made from (`manufacturing: source:`) has to pass
  these checks itself. The `software:` it declares has to resolve, to the file
  that was meant.
- An assembly is either sold assembled (bought, and nothing inside it is looked
  at), or assembled: then every step has to be one somebody can follow - each
  item after the first says what it is joined to and how - and everything it is
  procured from has to pass these checks on its own.

### When it does not apply

An object that says `manufacturable: false` - a model of something somebody else
makes, an import kept as it arrived, a scene (which is not manufacturable unless
it says so). A sketch is checked for being reproducible and for nothing else.

### When it fails

- `It is not reproducible: ...`: pin the file with `fileHash:` (`pc add` writes
  one for an object it adds from a URL), carry the file in the package, or name
  a `vendor:` and `sku:`.
- `Cannot be purchased or manufactured`: add a `manufacturing:` section with a
  `method:` (see the `manufacturability-*` checks for each method), or a
  `vendor:` and `sku:` - or say `manufacturable: false` if nobody is going to
  make it.
- `No suppliers found` / `No suppliers provide the part`: name a supplier that
  carries it, or make it instead.
- `No manufacturing tolerance is specified`: give the part a `tolerance`, which
  a part that is made needs to be made to anything.
- `The stock '...' it is made from is not found` / `cannot be had`: fix the name
  under `manufacturing: source:`, or make the stock obtainable.
- `Step '...' can't be followed: ...`: give that link a `connect:` and say how it
  goes on - a `how:`, or a mating or an interface that says it.
- `Missing part or assembly '...' is referenced` / `Non-manufacturable ... is
  referenced`: what the assembly is made of has to exist and be manufacturable.

### Settings

`manufacturable:` on the object or its package; `vendor:`, `sku:`, `fileFrom:`,
`fileHash:`, `software:`, `manufacturing:` and the part's `tolerance`.
""",
    ),
    "manufacturability-additive": Entry(
        "Additive: a closed solid",
        "a part with `manufacturing: method: additive`",
        """
Whether a part to be printed is a closed solid: a body with no open edges, which
is what a slicer needs to know what is inside it.

### When it does not apply

Anything but a part, and a part made by any other method.

### When it fails

- `The shape is not solid`: the part has open edges - faces that do not meet.
  Close the model in the tool it comes from, or export it as a solid rather than
  as a surface.
- `Failed to get the shape`: it did not build; see `cad`.
""",
    ),
    "manufacturability-subtractive": Entry(
        "Subtractive: cut from its stock",
        "a part with `manufacturing: method: subtractive`",
        """
Whether a part to be cut out of stock can be: the stock is named, the machine
sections can be read, the part is a closed solid, and it lies inside its stock
with material to take away. Cutting removes material and never adds it, so a
part that sticks out of its stock cannot be cut from it.

### When it does not apply

Anything but a part, and a part made by any other method.

### When it fails

- `The subtractive declaration states no 'source'`: name the stock the part is
  cut from under `manufacturing: source:`.
- `The subtractive declaration says ...`: a `cnc:`, `laser:`, `drill:` or `cut:`
  section has a key it does not take, or a value it cannot read; the sentence
  names it.
- `It does not fit the stock '...': ... mm3 of it is outside`: make the stock
  larger, or place it so that it encloses the part.
- `The stock '...' is the same solid as the part, so nothing is cut from it`:
  `source:` names the part itself, or a copy of it; name the blank instead.
- `The shape is not solid`: close the model, as for `manufacturability-additive`.
""",
    ),
    "manufacturability-forming": Entry(
        "Forming: a closed solid",
        "a part with `manufacturing: method: forming`",
        """
Whether a part to be formed - moulded, cast, pressed - is a closed solid.

### When it does not apply

Anything but a part, and a part made by any other method.

### When it fails

- `The shape is not solid`: the part has open edges; close the model.
- `Failed to get the shape`: it did not build; see `cad`.
""",
    ),
    "manufacturability-sheet-metal": Entry(
        "Sheet metal: a flat blank and bends",
        "a part with `manufacturing: method: sheet_metal`",
        """
Whether a sheet metal part can be bent out of what it names: a blank that is
flat on both faces (`source:`), and a sketch of the bend lines (`instructions:`)
in which every line says its angle, its inner radius and which way it goes.
Both questions are asked every time, so one run says everything that is wrong.

### When it does not apply

Anything but a part, and a part made by any other method.

### When it fails

- `The sheet metal declaration states no 'source'` (or `'instructions'`): name
  the flat blank and the sketch of the bend lines.
- `... is not flat on the bottom` (or `top`): `source:` has to be the flat blank,
  not the bent part.
- `... draws no bend lines`: the sketch has to draw each bend as a line; a layer
  can be picked with parameters (`bends;include=BEND_UP,BEND_DOWN`).
- `The bend drawn by the ... cannot be made: ...`: annotate the line with an
  `angle` above 0 and below 360 degrees, a `radius` above 0 (a bend, not a fold),
  and a `direction` of `up` or `down`.
""",
    ),
    "manufacturability-laser": Entry(
        "Laser: faces along or across the beam",
        "a part made by `method: subtractive` that names a `laser:` machine",
        """
Whether a laser cutting along the tool axis can make the part: every face has to
be either a wall along the axis or a face across it, and there has to be a wall
to cut. A laser cuts straight through, so a chamfer, a taper or a fillet that is
neither is not something it can make. Thickness, material and power are not
checked.

### When it does not apply

Anything but a part, a part made by another method, and a subtractive part that
names no `laser:` machine - a part that names no machine at all is taken to be
milled.

### When it fails

- `A laser cutting along ... cannot make it: N of its faces are neither along
  ... nor across it`: remove the faces at an angle (the worst is named), or set
  `toolAxis:` to the direction the beam really goes.
- `It has no wall along ... for a laser to cut`: the axis is wrong, or the part
  is not something a laser makes.

### Settings

`manufacturing: laser:` - `toolAxis:` (or `along:`, default `-Z`) and the job
keys (`kerf`, `power`, `feed`, `direction`, `implementation`).
""",
    ),
    "manufacturability-drill": Entry(
        "Drill: round holes along the axis",
        "a part made by `method: subtractive` that names a `drill:` machine",
        """
Whether a drill working along the tool axis can make what is taken away: every
wall has to be along the axis and round. Measured on the material removed from
the stock when `source:` names one, and on the part itself otherwise.

### When it does not apply

Anything but a part, a part made by another method, and a subtractive part that
names no `drill:` machine.

### When it fails

- `There is no hole along ... for a drill to make`: the axis is wrong, or there
  is nothing to drill.
- `A drill only makes round holes, and N of the M walls along ... are not
  round`: make the holes round, or cut the other shapes another way. When the
  stock is not named, the part's own outline counts as drilled: name it with
  `source:`.
- `A drill working along ... cannot make it`: some walls are not along the axis;
  check `toolAxis:`.

### Settings

`manufacturing: drill:` - `toolAxis:` (or `along:`), and the job keys
(`diameter`, `peck`, `plunge`, `speed`, `safe_z`); `manufacturing: source:`.
""",
    ),
    "manufacturability-cut": Entry(
        "Cut: the cuts make the part",
        "a part made by `method: subtractive` that names a `cut:` machine",
        """
Whether cutting the stock where the part says gives the part: each declared cut
is a plane, the stock is cut at every one, and what is left has to be the part.
No cut may take nothing off.

### When it does not apply

Anything but a part, a part made by another method, and a subtractive part that
names no `cut:` machine. A part that names no stock passes here, since
`manufacturability-subtractive` already says so.

### When it fails

- `Cut #N (...) takes nothing off the stock`: the length is longer than the
  stock, or the axis points away from it.
- `Cutting the stock '...' at ... does not make it: ...`: the cuts leave too much
  or too little; correct the lengths or the axes.

### Settings

`manufacturing: cut:` - `toolAxis:` (or `along:`) and `cuts:`, each a `length`
and an optional axis of its own.
""",
    ),
    "connect": Entry(
        "Connection instructions",
        "assemblies and scenes",
        """
Whether the assembly's connection instructions can be followed as written:
whether anything had to be bent to put it together - a `how:` whose minimum is
above its maximum, two interfaces that disagree about the thread they share and
neither cuts its own, a motion or a physics the joined ends contradict, a joint
named twice, a chain that closes on itself. An assembly that says nothing about
how its items go on has nothing to contradict, and passes.

### When it does not apply

Anything but an assembly or a scene.

### When it fails

Each failure is `<link>: <what had to be repaired>`. Fix the declaration it
names: the `how:` of that link, the interfaces or the mating it joins, or the
joint. The list of what is reported is in "Testing the instructions" of the
assembly documentation.
""",
    ),
    "connectivity": Entry(
        "Everything is held in place",
        "assemblies and scenes",
        """
Whether everything an assembly places is placed once, on a port that takes it,
and held there. Three mistakes that render perfectly:

- the same part twice in the same place;
- two items connected to one port, when its interface does not say
  `multiConnect: true`;
- an item placed by coordinates (`location:`) among items that connect, which
  says where it ends up but not what holds it there.

An assembly that is to be made (`manufacturable`) is held to more: no item may
be placed by coordinates, and every item after the first has to connect to
something.

### When it does not apply

Anything but an assembly or a scene.

### When it fails

- `'a' and 'b' are the same part in the same place`: remove one, or move it.
- `'a' and 'b' are both connected to '...' of '...'`: connect one of them
  elsewhere, or say `multiConnect: true` on the interface if the port does take
  several.
- `'...' is placed by coordinates ...`: replace its `location:` with a `connect:`
  to what holds it.

### Settings

On the assembly: `connectivity: allowDuplicates: true` to allow the same part
twice in one place, and `connectivity: requireAnchored: false` to allow items
placed by coordinates.
""",
    ),
    "requirements": Entry(
        "Meets its requirements",
        "objects whose `requirements:` require ports, interfaces or physical properties",
        """
Whether the model is what its `requirements:` say it has to be, as far as that
can be measured: each required port is there, facing where it has to; each
required interface is implemented, its instances where they have to be; and each
required physical property - its mass, its centre of mass, its inertia, its
friction - has a value that meets the requirement. Asked again every time, never
read from the cache.

The `features:` are sentences rather than measurements, and are judged by the
`/pc:validate` agent skill. What this check asks of them is only that a
`simulate:` entry or an analysis scenario naming one (`feature:`) names one that
is declared.

### When it does not apply

An object that requires no port, interface or physical property, and whose
simulations and analysis scenarios name no feature.

### When it fails

Each failure is `<section>: <name>: <required>: <found>` - what was asked for and
what is there instead.

- A port or an interface instance that is missing, or faces the wrong way: move
  it in the model, or correct the requirement if the requirement is what is
  wrong.
- `not known: ...`: PartCAD could not find out the value - a mass with no
  density to work it out from. State the value in a `physics:` section, or give
  the part a `material:` with a density. "Not known" is not "met".
- `unreadable`: the requirement itself cannot be read; the detail says why.
""",
    ),
    "degenerate": Entry(
        "Has size in every direction",
        "parts",
        """
Whether a part has size in every direction. A part that built as a flat disc or
an empty box - a brick whose subfile could not be fetched, a script that
returned the wrong thing - renders, exports and measures, and is not the part
that was meant. Read from the box measured when the part was built, so it costs
next to nothing.

### When it does not apply

A sketch, which is flat by definition, and an assembly or a scene, which is
checked through its parts.

### When it fails

- `The shape built but occupies no space at all`: nothing came out of the build
  but an empty shape; find the geometry that went missing.
- `The shape is flat in ...`: it is less than a thousandth of a millimetre thick
  in one direction - a missing extrusion, a missing file, a surface where a solid
  was meant.
""",
    ),
    "shell": Entry(
        "A body, not a skin",
        "parts",
        """
Whether a part is a body rather than a skin: a set of faces with nothing said
about which side of them is material renders and exports like the part that was
meant, while every boolean against it comes back with no solid in it - so
interference, CAM, FEA and any mass computed from it are wrong. Read straight
out of the geometry the part has already produced, so it costs nothing.

### When it does not apply

A sketch, which is not a body, and an assembly or a scene, which is checked
through its parts.

### When it fails

`The shape is a skin rather than a body: N shell(s) that no solid bounds itself
with`. A shell a script returns is closed into a solid automatically, so either
those faces enclose nothing - close them - or they come from a file that states
the part as a surface: export it from its tool as a solid instead.
""",
    ),
    "solidity": Entry(
        "Not inside out",
        "parts",
        """
Whether every solid of a part has a positive volume. A solid whose faces are
oriented inward measures the right size and a negative volume: it renders
correctly, and every boolean against it is wrong. Asked before `interference`,
deliberately, since an inside-out part overlaps things it is nowhere near.

### When it does not apply

A sketch, which has no solid, and an assembly or a scene, which is checked
through its parts.

### When it fails

`... a constituent solid measures ... mm^3`: negative means the faces are
oriented inward - fix their winding in the source (an LDraw part, for one, has to
state it); zero means the solid encloses nothing.
""",
    ),
    "validity": Entry(
        "A well-formed solid",
        "parts",
        """
Whether the geometry kernel certifies a part's solid as well formed. It reports
and never fails: the parts it has the most to say about are often ones nothing
is functionally wrong with. A part it reports on is one to expect trouble from
in anything exacting - booleans, meshing for print, CAM - so treat a strange
result from those as this rather than as the tool.

### When it does not apply

A sketch, which is not a body, and an assembly or a scene, which is checked
through its parts.

### When it fails

It does not fail. When it says `the geometry is a solid but not a well formed
one`, rebuild the part more simply where it can be - fewer tiny faces, no
self-intersections - or re-export it from its source.
""",
    ),
    "interference": Entry(
        "Parts do not overlap",
        "assemblies and scenes",
        """
Whether the parts of an assembly share space. Boxes are used only to pick the
pairs worth asking about; the answer comes from intersecting the two solids and
measuring what they share. Each sub-assembly declared in the package answers
for its own inside with its own verdict, so only what crosses its boundary is
looked at here. It is the most expensive of the geometry checks.

An overlap that is meant to be there is read from the joint between the two:
an interface or a mating that says `selfScrew` (a screw cutting its own thread)
or `snapIn` (a pin pushed past a feature), a connection whose `how:` says either,
and a connection's `interferes:`, naming the further items the same act of
joining drives through. Nothing is ever excused for a pair of parts by name.

### When it does not apply

Anything but an assembly or a scene.

### When it fails

- `'a' and 'b' share N mm^3`: the two are in each other. Each such failure
  leaves an assembly to look at: the two parts where the assembly places them,
  and a sub-assembly named `interference` holding what they share, one part per
  volume. Open it from the IDE's Test tab, or with `pc ide view -a` and its name
  (`<assembly>/interference/<a>+<b>`), and switch the two parts off to see the
  overlap alone. Then move one of them - or, if the overlap is the joint, say so
  on the joint.
- `'...' does not pass on its own`: a sub-assembly has overlaps of its own; test
  it.
- `'...' names '...' in 'interferes:', which is not a link`: correct the name; it
  is a link of the same `links:` list as the connection.
- An object marked `manufacturable: false` (a scene, unless it says otherwise) is
  told what overlaps rather than failed for it.

### Settings

On the assembly: `interference: minVolume:` (in mm^3, default 0.05), below which
an overlap is taken for the arithmetic of two surfaces that touch, and
`interference: minFraction:`, the same floor as a share of the smaller part.
""",
    ),
    "cam": Entry(
        "A machine route can be produced",
        "parts and sketches that name a machine to be cut on",
        """
Whether the program a machine cuts the object with can be produced: for every
`cnc:`, `laser:` or `drill:` machine it names, the post-processor that machine
uses writes a route, and the route is thrown away. The same code as `pc cam`.

### When it does not apply

An object that names no machine to be routed on - nothing under
`manufacturing:` asks for one, or only a `cut:` machine, which needs no program.

### When it fails

- A sentence about the section: a job key it cannot read; fix it.
- `the 'cam' implementation could not be resolved`: the implementation the
  machine names is not a dependency of the package, or does not declare the file
  type.
- `no route was produced by ...`: the post-processor's error follows; fix the
  tool or the outline it names, or run `pc cam` to see the whole report.

It is skipped, with a warning, where the implementation cannot run on this
machine: start a container runtime, or install what it needs.
""",
    ),
    "fea": Entry(
        "Structural analysis (FEA)",
        "parts that declare an `fea:` section",
        """
Whether a part holds up under the loads each scenario of its `fea:` section
declares: every scenario is run by the implementation configured, and the part
passes when each of them ran and found nothing - the same analyses as `pc cae
fea`, which runs one of them with `-f <scenario>`.

### When it does not apply

Anything but a part, and a part that declares no `fea:` section.

### When it fails

- A sentence about a scenario (`'fea: loaded:' declares neither 'fix:' nor
  'load:'`, a key it does not take): fix the scenario it names.
- `FEA 'loaded' could not be run by ...`: the solver or the mesher is not
  installed, or failed; the report says which. Install it, or name another
  implementation.
- `FEA 'loaded' findings: ...`: the analysis ran and found a problem - a stress,
  a deflection - at the place named. Change the design, or the load if the load
  is what is wrong.

It is skipped, with a warning, only where the implementation runs in a container
and there is no container runtime here.

### Settings

`fea: <scenario>: fix:`, `load:` (a force; a bare number is kilograms),
`gravity:`, `implementation:` and `params:`; the user setting
`caeFeaImplementation`.
""",
    ),
    "dynamic": Entry(
        "Vibration analysis (Dynamic FEA)",
        "parts that declare a `dynamic:` section",
        """
Whether a part, held as each scenario of its `dynamic:` section says, rings only
where it may: the modal analysis of every scenario is run by the implementation
configured, and the part passes when each ran and found nothing - the same
analyses as `pc cae dynamic`. A natural
frequency is a property of the part and how it is held, not of what it carries,
so a scenario says only where it is held.

### When it does not apply

Anything but a part, and a part that declares no `dynamic:` section.

### When it fails

- A sentence about a scenario (`'dynamic: bolted:' declares none of 'fix:'`, a
  key it does not take, such as `load:`): fix the scenario it names.
- `DYNAMIC 'bolted' could not be run by ...`: the solver or the mesher is not
  installed, or failed; the report says which. Install it, or name another
  implementation.
- `DYNAMIC 'bolted' findings: ...`: the analysis ran and found a problem - a
  mode where the part must not ring. Change how it is held, or its stiffness or
  mass.

It is skipped, with a warning, only where the implementation runs in a container
and there is no container runtime here.

### Settings

`dynamic: <scenario>: fix:` (the interfaces it is held by), `implementation:`
and `params:`; the user setting `caeDynamicImplementation`.
""",
    ),
    "thermal": Entry(
        "Heat transfer",
        "parts that declare a `thermal:` section",
        """
Whether a part, heated and cooled as each scenario of its `thermal:` section
says, stays as cool as it has to: every scenario is run by the implementation
configured, and the part passes when each ran and found nothing - the same
analyses as `pc cae thermal`.

### When it does not apply

Anything but a part, and a part that declares no `thermal:` section.

### When it fails

- A sentence about a scenario (`'thermal: in-use:' declares none of
  'temperature:', 'heat:', 'convection:'`, a key it does not take): fix the
  scenario it names.
- `THERMAL 'in-use' could not be run by ...`: the solver or the mesher is not
  installed, or failed; the report says which. Install it, or name another
  implementation.
- `THERMAL 'in-use' findings: ...`: the analysis ran and found a problem - a temperature
  the part must not reach - at the place named. Change the design, how it is
  cooled, or the heat if the heat is what is wrong.

It is skipped, with a warning, only where the implementation runs in a container
and there is no container runtime here.

### Settings

`thermal: <scenario>: temperature:` (held at, in Celsius), `heat:` (put in, in
watts), `convection:` (a film coefficient, in W/(m^2*K)), `implementation:` and
`params:`; the user setting `caeThermalImplementation`.
""",
    ),
    "cfd": Entry(
        "Flow analysis (CFD)",
        "parts that declare a `cfd:` section",
        """
Whether a part behaves in the flow each scenario of its `cfd:` section declares:
every scenario is run by the implementation configured, and the part passes when
each ran and found nothing - the same analyses as `pc cae cfd`.

### When it does not apply

Anything but a part, and a part that declares no `cfd:` section.

### When it fails

- A sentence about a scenario: fix the scenario it names.
- `CFD '<scenario>' could not be run by ...`: the solver is not installed, or
  failed; the report says which.
- `CFD '<scenario>' findings: ...`: the analysis ran and found a problem at the
  place named.

It is skipped, with a warning, only where the implementation runs in a container
and there is no container runtime here.

### Settings

`cfd: <scenario>: fix:`, `load:`, `outlet:`, `implementation:` and `params:`;
the user setting `caeCfdImplementation`.
""",
    ),
    "sim": Entry(
        "Does what its simulations say",
        "parts, assemblies and scenes that declare `simulate:`",
        """
Whether the object does what its `simulate:` section says it does: each
simulation is run - the object placed in its scene and handed to the simulation
plugin - and its `validation:` condition has to hold over what came back. The
same runs as `pc sim`, which also prints everything the plugin reported
(`--json`). It is the most expensive question `pc test` asks, and is asked last.

### When it does not apply

Anything but a part, an assembly or a scene, and one that declares no
simulation.

### When it fails

- `... ran, and its 'validation' does not hold`: the object did not behave as
  claimed. Run `pc sim --json` to see `before` and `after`, then change the
  design, or the condition if the condition is what is wrong.
- `... could not be run`: the plugin or the scene the entry names is not found,
  or the simulator failed; the report says which.
- `... states no 'validation'`: asked about by name, an entry with no condition
  fails; add one over `before` and `after`. Walked to as part of a package, it is
  skipped instead.

It is skipped, with a warning, where the simulator runs in a container and there
is no container runtime here.

### Settings

`simulate: <name>:` - `simulation:` (the plugin), `scene:`, `validation:`, and
`feature:`, the feature of the requirements it demonstrates.
""",
    ),
}


def _blocks(text: str) -> list:
    """The blocks of an entry's text: headings, paragraphs, lists and code."""
    blocks = []
    lines = text.strip("\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip()
            body = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                body.append(lines[index])
                index += 1
            blocks.append({"type": "code", "language": language, "text": "\n".join(body)})
            index += 1
            continue
        chunk = []
        while index < len(lines) and lines[index].strip():
            chunk.append(lines[index])
            index += 1
        if chunk[0].startswith("### "):
            blocks.append({"type": "heading", "text": " ".join(part.strip() for part in chunk)[4:]})
        elif chunk[0].startswith("- "):
            items = []
            for part in chunk:
                if part.startswith("- "):
                    items.append(part[2:].strip())
                else:
                    items[-1] += " " + part.strip()
            blocks.append({"type": "list", "items": items})
        else:
            blocks.append({"type": "paragraph", "text": " ".join(part.strip() for part in chunk)})
    return blocks


def describe(name: str) -> typing.Optional[dict]:
    """The entry of the check named 'name', as the IDE draws it; None for a check with none."""
    entry = TESTS.get(name)
    if entry is None:
        return None
    return {"title": entry.title, "applies": entry.applies, "blocks": _blocks(entry.text)}


# Outside code, these mean something to reStructuredText that they do not mean
# in an entry, and are written escaped.
_RST_SPECIAL = re.compile(r"([*|\\])")
# A word ending in an underscore is a reference.
_RST_TRAILING_UNDERSCORE = re.compile(r"(\w)_(?=\W|$)")


def _rst_inline(text: str) -> str:
    parts = text.split("`")
    for index, part in enumerate(parts):
        if index % 2:
            parts[index] = "``%s``" % part
        else:
            part = _RST_SPECIAL.sub(r"\\\1", part)
            parts[index] = _RST_TRAILING_UNDERSCORE.sub(r"\1\\_", part)
    return "".join(parts)


def _underline(text: str, character: str) -> str:
    return "%s\n%s" % (text, character * len(text))


# Where the generated part of the page begins and ends.
BEGIN = ".. BEGIN GENERATED FROM partcad.test.catalog: run 'poetry run python -m partcad.test.catalog --write'"
END = ".. END GENERATED FROM partcad.test.catalog"


def rst(names: typing.Optional[list] = None) -> str:
    """Every entry as a section of the documentation, in the order 'names' gives (registry order)."""
    out = []
    for name in names if names is not None else list(TESTS):
        entry = TESTS[name]
        out.append(".. _test-%s:" % name)
        out.append("")
        out.append(_underline("``%s``: %s" % (name, entry.title), "-"))
        out.append("")
        out.append("**Applies to** %s. ``pc test -f %s <object>`` runs it alone." % (_rst_inline(entry.applies), name))
        out.append("")
        for block in _blocks(entry.text):
            if block["type"] == "heading":
                out.append(_underline(block["text"], "^"))
            elif block["type"] == "paragraph":
                out.append(_rst_inline(block["text"]))
            elif block["type"] == "list":
                for item in block["items"]:
                    out.append("* " + _rst_inline(item))
            elif block["type"] == "code":
                out.append(".. code-block:: %s" % (block["language"] or "text"))
                out.append("")
                out.extend(("   " + line) if line else "" for line in block["text"].split("\n"))
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def registered() -> list:
    """The names of the checks `pc test` runs, in the order it runs them."""
    from .all import tests
    from .test import Test

    # Whatever cap is already set, so that asking for the names changes nothing.
    return [test.name for test in tests(Test.MAX_CONCURRENT_TESTS)]


def page(text: str) -> str:
    """'text', a documentation page, with its generated part written afresh."""
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    return text[:start] + "\n\n" + rst(registered()) + "\n" + text[end:]


PAGE = "docs/source/digital_thread/testing.rst"


def main(argv: list) -> int:
    with open(PAGE, encoding="utf-8") as stream:
        current = stream.read()
    written = page(current)
    if "--write" in argv:
        if written != current:
            with open(PAGE, "w", encoding="utf-8") as stream:
                stream.write(written)
        return 0
    sys.stdout.write(rst(registered()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
