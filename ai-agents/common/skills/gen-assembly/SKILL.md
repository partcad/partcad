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
      stage: <label; consecutive nodes sharing it are connected at the same time>
      pushForceMax: <force in N, default 5>
      pushDistance: <staging distance in mm; default 1.5x the part's length along the interface Z>
      turnDirection: <cw (default) or ccw>
      turnTorqueMax: <torque in N*m, default 0>
      threadStep: <lead in mm per full turn, default 0.00>
      holdWith: <interface(s) to hold the part being added by>
      holdWithInstance: <instance(s) of holdWith>
      holdWithForceMin/Max: <force in N to hold it with, default 3/7; holdWithForce sets both>
      holdTo: <interface(s) to hold the target by>
      holdToInstance: <instance(s) of holdTo>
      holdToForceMin/Max: <force in N to hold the target with, default 3/7; holdToForce sets both>
```

`pushDirection` is not a field: it is deduced from the interfaces (an
interface's +Z points into the object it belongs to, which is the way an
incoming part travels) and reported with the rest.

Everything that is **required** to perform the assembly must be codified in
`how` and the other fields — never only in `comment`, which no tool reads. The
`hold*` fields default to the `connect:` section of the part or assembly
definition in `partcad.yaml`:

```yaml
parts:
  <name>:
    type: step
    connect: # (optional) what this part contributes to every connection
      hold: <interface(s) to hold it by>
      holdInstance: <instance(s) of hold>
      holdForceMin/Max: <force in N; holdForce sets both>
```

`threadStep` defaults to the thread of the interfaces being connected, declared
once on the interface that introduces it:

```yaml
interfaces:
  m3:
    threadStep: 0.5   # inherited by every interface that inherits m3
    selfScrew: false  # true when it cuts its own thread instead of matching one
```

Two connected interfaces must agree on `threadStep` unless one declares
`selfScrew`. Run `pc test -a <name>` to check that: it fails an assembly whose
instructions contradict themselves — a mismatched thread, or a `*Min` above its
`*Max` — and passes one that takes every default.

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
