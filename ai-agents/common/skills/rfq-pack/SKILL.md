---
name: rfq-pack
description: Prepare a request-for-quotation package for the parts of a PartCAD part or assembly that a supplier is to make - a folder holding a cover sheet, one CSV line per item (quantity, method, material, finish, stock, tolerance, size, mass), a STEP file, a mesh where it is printed and a dimensioned drawing for each made part, the assembly instructions when the supplier is to assemble it, and a manifest tracing every file to the package, the commit and the command that wrote it. Use for /pc:rfq-pack, or when the user asks for an RFQ, a request for quote, a quote package, a drawing package, a technical data package, or anything to send to a machine shop, a print bureau or a contract manufacturer - including when a sourcing or quoting skill of another plugin, such as Claude for Manufacturing, needs the design files. It never sends anything or places an order.
---

# pc:rfq-pack

Turn a design into the package a supplier quotes from. `$ARGUMENTS` names the
object, and may say how many to build, which parts go out (all that are made,
or "the CNC parts", "only the sheet metal"), and where the package goes.

A supplier quotes what is in front of them, so what goes into the package is
what they will make — and nothing in it may be a guess. Every number comes out
of PartCAD, from the package as it is committed, and anything PartCAD does not
know is written as *not stated* rather than filled in. Leaving a field empty is
how the person sending this finds out the design is incomplete; filling it in
is how the supplier finds out instead, after quoting the wrong thing.

The package is for a person to review and send. Do not email it, upload it,
or run `pc supply order`.

## 1. Settle what is asked

Before running anything, know:

- **The object** — a part or an assembly the package declares. Find it as
  `/pc:export` §1 does (`pc --no-ansi list`, `pc --no-ansi info <name>`).
- **The quantity** — how many of the object are to be built. Ask if it was not
  said: a supplier's price depends on it more than on anything else.
- **Which lines go out** — every made part by default (§3). A user who names a
  process ("the laser-cut parts") gets the lines whose `method` is that one.
- **The destination** — a directory. Where it was not given, ask; suggest the
  folder the user's other tools read, such as a synced SharePoint or OneDrive
  folder when Claude for Manufacturing is to work from it, and otherwise use
  `./out/rfq/<object>-<YYYY-MM-DD>/`. When only the `partcad` MCP server is
  available (no shell), the destination has to be inside the workspace it
  serves, since that is the only place its tools may write.

## 2. Make sure PartCAD is available, and pin the revision

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:setup executable` first. Pass `--no-ansi` on every run, before the
subcommand, and capture both streams (`2>&1`): with it the logs go to stderr.

Without a shell, the `partcad` MCP server (`pc mcp`) has a tool for each command
used here — `info`, `bom`, `export`, `render`, `instructions`, `qual_test` — and
`execute` for any daemon method; use those instead.

Record what the package is being made from:

```sh
pc --no-ansi version 2>&1                                  # the PartCAD that wrote it
git -C <package dir> rev-parse HEAD                        # the commit
git -C <package dir> status --porcelain -- .               # anything uncommitted
git -C <package dir> describe --tags --exact-match 2>/dev/null   # a tag, if HEAD has one
```

If anything is uncommitted, say so and ask whether to continue: a package sent
out from uncommitted work describes no revision anyone can go back to, and
`/pc:change-impact` cannot later say what changed since. Suggest committing, and
tagging the commit the package is sent from (`rfq/<object>/<date>`), but do not
commit or tag yourself.

## 3. Work out the lines

An assembly is a tree of what it is made of, and each line of it is **bought**
(it declares a `vendor:` and an `sku:`), **built** (a part with a
`manufacturing:` section, an assembly with links), both, or neither. What goes
to a supplier who makes things is what is built. A line that can be both is
built only where the user chose Build in the IDE's Build vs Buy tab; otherwise
it is bought (see the Build vs Buy page of the Digital Thread documentation).

**With the MCP server**, ask for the tree the Build vs Buy tab is drawn from:

```json
execute {"method": "manufacturing.tree", "params": {"package": "<package>", "object": "<name>"}}
```

Each node has `name`, `kind` (`part` or `assembly`), `link`, `desc`, `buy`,
`build`, `problems`, `vendor`, `sku`, `material`, `cmf` and its `children`. A
node is one placement, so an item placed four times is four nodes: count them.
Stop at a node that is bought — what is inside it comes with it — and include
the children of a part that is built, which are the stock it is made from.

**Without it**, the assembly instructions list the same thing, and follow the
user's Build vs Buy choices:

```sh
mkdir -p /tmp/pc-rfq/instructions
pc --no-ansi instructions -r -b -t html --ignore-manufacturability \
    -O /tmp/pc-rfq/instructions <assembly> 2>&1
```

Every **Make** page is a built part with how many are needed and how it is
made; the **Bill of Materials** table counts each item. `pc --no-ansi bom -j
<object>` lists what has to be bought — its `vendor`, `sku`, `count` and
`count_per_sku` — and, for a made part, the stock it is cut from, of kind
`stock`. A printed part needs nothing bought, so it is in the instructions and
not in the bill of materials.

A part, rather than an assembly, is one line: itself.

Multiply every count by the quantity being built.

**A line with `problems`, or that can be neither bought nor built, is not
dropped.** It goes into the cover sheet's *Open items* with the problem as
PartCAD stated it. So does any part that fails the manufacturability check:

```sh
pc --no-ansi qual test -f manufacturability <part> 2>&1
```

A check that passes prints nothing; a finding is logged as a warning or an
error naming the check, and an error is a failure.

## 4. Read each made part

For every line going out:

```sh
pc --no-ansi info <part> 2>&1
```

Take from it, as reported, and never from the description or a picture:

| Field | Where `pc info` says it |
| --- | --- |
| method | `manufacturing.method` in `CONFIGURATION` (`subtractive`, `additive`, `forming`, …) |
| stock | `manufacturing.source` — what it is cut from |
| material | `Material`: its formal and full names; the reference in `properties` if it resolved to nothing |
| finish, colour | `CMF` — a colour marked `displayOnly` is how it is drawn, not a requirement |
| tolerance | the `tolerance` parameter, in millimetres |
| size | `BoundingBox.size`, in millimetres |
| volume | `Volume`, in mm³ |
| mass | `MassProperties.mass` and its `source`; "unknown" when it says so |
| hash | `Hash` — the identity of this geometry, for the manifest |

A part with parameters is read, exported and drawn with the same values each
time: `-p <name>=<value>`, or the name `"<part>;<name>=<value>"` (quoted).

The part's `requirements:` say what it is held to. Read them with
`pc --no-ansi req list --json <part>` and carry the ones a maker has to honour —
a load it must take, a fit, a surface — into the cover sheet, quoted.

## 5. Write the files

The layout is fixed, so that whatever reads the package next — a person, or a
sourcing skill comparing bids — finds the same thing every time:

```
<destination>/
  cover.md          the request, for a person to read and send
  lines.csv         one row per line
  manifest.json     where everything came from
  parts/            <part>.step for every line, plus <part>.3mf for a printed one
  drawings/         <part>.pdf, a dimensioned drawing of every line
  views/            <part>.png, an isometric picture of every line
  assembly/         only when the supplier assembles it: the STEP and the instructions
```

```sh
pc --no-ansi export -t step -O <destination>/parts <part> 2>&1
pc --no-ansi export -t 3mf -O <destination>/parts <part> 2>&1        # additive only
pc --no-ansi render -t pdf -e //pub/feature/render/draftwright \
    -O <destination>/drawings <part> 2>&1
pc --no-ansi render -t png --view iso -O <destination>/views <part> 2>&1
```

`-O` expects the directory to exist: `mkdir -p` each one first.

The drawing is the one step allowed to fail. `draftwright` comes from the
public index, needs a network connection the first time, and draws parts only;
it may exit non-zero having written a usable file, so check whether the file
appeared. When it did not, say on that line that **the STEP file is the master
and no drawing was made**, and never substitute a drawing of your own.

A part cut from a sheet whose outline is a sketch is cut from the sketch: export
it too (`pc --no-ansi export -t dxf -O <destination>/parts <sketch>`), and say
which part it is the outline of. A machine program (`pc cam`) is the supplier's
business, not the request's, unless the user asks for one.

When the user says the supplier is also to put the assembly together, add:

```sh
pc --no-ansi export -t step -O <destination>/assembly <assembly> 2>&1
pc --no-ansi instructions -r -b -t pdf -O <destination>/assembly <assembly> 2>&1
```

and add the bought lines to `lines.csv` too, marked `buy`, with the vendor and
the SKU from `pc bom -j`, so the supplier can say whether they source them.

### `lines.csv`

One header row, then one row per line, in this order of columns:

```
line,part,description,make_or_buy,quantity_per_build,quantity,method,material,finish,colour,stock,tolerance_mm,size_x_mm,size_y_mm,size_z_mm,volume_mm3,mass_g,vendor,sku,step,drawing,mesh,hash
```

`part` is the full name PartCAD reports (`//package:part`), with its parameter
values when it has any. Paths are relative to the destination. An empty cell is
something PartCAD does not know; write `not stated` in the cover sheet for each
field that matters to the process (a tolerance for a machined part, a material
for anything).

### `cover.md`

A request a person can read and send. In this order:

1. What is requested: the object, its description, the quantity, and the
   revision (commit, and tag if any).
2. A table of the lines: part, quantity, method, material, finish, tolerance,
   drawing (or "STEP is the master").
3. The requirements each part is held to, quoted.
4. **Open items**: every line with a problem, every failed check, every field
   not stated, and any uncommitted change.
5. Left for the sender, as blanks rather than guesses: the due date for the
   quote, delivery address and date, inspection and certificates required,
   payment terms, contact.

### `manifest.json`

```json
{
  "kind": "rfq-pack",
  "created": "<UTC time, ISO 8601>",
  "partcad": "<pc version>",
  "package": "<//package>",
  "object": "<name, with parameter values>",
  "quantity": 10,
  "revision": {"commit": "<sha>", "tag": "<tag or null>", "uncommitted": false},
  "files": [
    {"path": "parts/bracket.step", "of": "//package:bracket", "hash": "<pc info Hash>",
     "command": "pc --no-ansi export -t step -O <destination>/parts bracket"}
  ],
  "open": ["<each open item, as in cover.md>"]
}
```

Every file in the package is listed, with the exact command that wrote it, so
anyone can produce it again from the same commit — and so that a skill reading
the package can cite where a figure came from.

## 6. Report

Say where the package is, how many lines it has and of what, and list the open
items first: those are what the user has to settle before it is sent. Name any
drawing that could not be made. Do not describe the package as ready to send
while anything is open.
