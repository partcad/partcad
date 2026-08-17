---
name: gen-assembly
description: Generate a PartCAD assembly (an ASSY that composes parts with placement and/or mates) from a description, generating or reusing the component parts and validating the result with the PartCAD CLI. Use for /pc:gen-assembly or when the user asks to generate or create an assembly, mechanism, or multi-part product.
---

# pc:gen-assembly

Generate a PartCAD **assembly**: an `.assy` file that composes parts (and
sub-assemblies) into one product. The text after the command (`$ARGUMENTS`) is
the assembly description. *You* author both the ASSY and its component parts and
prove the whole thing **passes `pc test`**. There is no legacy `ai` assembly
pipeline — this capability is new.

## 1. Decompose

`$ARGUMENTS` is the description. Break it into components and the
spatial/mechanical relationships between them: which parts, how many of each, and
how they attach to or move relative to one another. Clarify only load-bearing
ambiguities.

## 2. Inventory or generate the parts

```sh
pc list parts          # what already exists to reuse
```

Reuse existing parts; generate any missing component with the `/pc:gen-part`
flow. Each part must pass `pc test` on its own before you compose it.

## 3. Author the ASSY

Scaffold (this creates the empty file and the `assemblies:` entry), then write
`<name>.assy`:

```sh
pc add assembly assy <name>.assy
```

An ASSY file is a tree of nodes under `links:` (reference: PartCAD "Assembly YAML"
docs, `docs/source/assy.rst`).

**Container — the top level, and any grouping node:**

```yaml
name: <optional>
description: <the description>
location: <optional [[x,y,z], [ax,ay,az], angle_deg]>
links:
  - <node>
  - <node>
```

**Part node** — places a part; use **exactly one** placement method:

```yaml
# explicit placement (translation, then rotation of angle_deg about the axis):
- part: <part-in-this-package  or  //package:part>
  name: <optional instance name>
  location: [[x, y, z], [ax, ay, az], angle_deg]
```

```yaml
# OR connect by ports (no interface mating):
- part: <...>
  connectPorts:
    with: <this part's port, if it has more than one>
    name: <target instance already in the assembly>
    to: <target port, if the target has more than one>
```

```yaml
# OR connect by interfaces (universal mating):
- part: <...>
  connect:
    with: <this part's interface, if more than one>
    name: <target instance already in the assembly>
    to: <target interface, if more than one compatible>
    # optional disambiguation: withInstance / withPort / toInstance / toPort
```

`location`, `connectPorts`, and `connect` are **mutually exclusive** — pick one
per node. `with` names the interface/port on the part being added; `to` names it
on the part already in the assembly.

Both `connectPorts` and `connect` also take two optional sections that describe
the connection rather than place it:

```yaml
- part: <...>
  connect:
    name: <target instance already in the assembly>
    comment: <free form context for a human or an LLM; never parsed>
    how:
      pushTorqueMax: <N, default 5>
      turnDirection: <cw (default) or ccw>
      turnTorqueMax: <N, default 0>
      threadStep: <mm per full turn, default 0.00>
      holdWith: <interface(s) to hold the part being added by>
      holdWithInstance: <instance(s) of holdWith>
      holdTo: <interface(s) to hold the target by>
      holdToInstance: <instance(s) of holdTo>
```

Everything that is **required** to perform the assembly must be codified in
`how` and the other fields — never only in `comment`, which no tool reads. The
`hold*` fields default to the `hold`/`holdInstance` fields of the part or
assembly definition in `partcad.yaml`.

**Sub-assembly node** — identical to a part node but with `assembly:` instead of
`part:`, and it may carry its own nested `links:`.

Prefer `connect`/`connectPorts` when the parts define interfaces/ports; otherwise
use explicit `location`. Work in millimeters and degrees.

Then mark the assembly **not manufacturable** in `partcad.yaml` (it is generated,
not a catalog item) so `pc test` passes:

```yaml
assemblies:
  <name>:
    type: assy
    path: <name>.assy
    manufacturable: false
```

## 4. Validate, render, iterate

```sh
pc test -a <name>                               # build gate: geometry instantiates
mkdir -p /tmp/pc-render                         # the -O directory must already exist
pc render -a -t png -O /tmp/pc-render <name>    # writes /tmp/pc-render/<name>.png
```

View `/tmp/pc-render/<name>.png`: check that components are positioned and
oriented correctly and that nothing interpenetrates unintentionally, then adjust
placements/mates. Iterate until it matches. `pc inspect -a <name>` gives an
interactive view.

## 5. Finalize

Summarize the structure — parts, sub-assemblies, key placements — and how to view
it (`pc inspect -a <name>`).
