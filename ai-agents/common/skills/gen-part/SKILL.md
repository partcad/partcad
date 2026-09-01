---
name: gen-part
description: Generate a PartCAD part from a natural-language description (and optional reference images/requirements) by authoring a CAD script and validating it with the PartCAD CLI. Use for /pc:gen-part or when the user asks to generate, create, or model a single mechanical part.
---

# pc:gen-part

Generate one PartCAD **part**. The text after the command (`$ARGUMENTS`) is the
part description — what to build. *You* author the CAD script yourself and prove
it works with the PartCAD CLI; do not use any built-in `ai-*` part type or
generation pipeline. Hard requirement: the finished part **passes `pc test`** (its
geometry instantiates cleanly).

Steps 4–7 are the reference flow — the same shape the legacy `pc add part --ai`
pipeline used (plan geometry → write script → validate → compare → refine). Treat
it as a strong default, not a script: skip, reorder, or replace steps as the part
warrants, but always finish by validating.

## 1. Understand the request

- `$ARGUMENTS` is the description. Read it and any `requirements`, and view
  reference images directly. Ask the user to clarify only genuinely load-bearing
  ambiguities; otherwise proceed and state your assumptions.
- Work in millimeters and degrees unless told otherwise.

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:setup executable` first.

## 3. Choose a representation

Pick the script kind that best fits the part — you decide:

| Kind | Good for |
| --- | --- |
| `build123d` | general parametric solids (recommended default) |
| `cadquery` | fluent / CSG-style modeling |
| `scad` (OpenSCAD) | simple constructive geometry, no Python |
| `sdf` | organic / implicit shapes |

## 4. (Optional) Plan the geometry

For anything non-trivial, sketch the constructive-solid-geometry plan first —
coordinate system, primitives with dimensions/positions/orientations, then
unions/differences/intersections and fillets/chamfers. This mirrors the legacy
"CSG" step and usually cuts iterations. Skip it for simple parts.

## 5. Author, register, and mark it

Write the script file **first** from `$ARGUMENTS` (plain type — never `ai-*`),
then register it — `pc add part` requires the file to already exist:

```sh
pc --no-ansi add part --desc "<the description>" <kind> <name>.<ext>   # e.g. build123d bracket.py
```

Language conventions for the script:

- **build123d / cadquery / sdf (Python):** import everything you use (including
  `math` and the library itself); call `show_object(<result>)` to expose the
  part; do not export anything. For cadquery, avoid `tetrahedron` / `hexahedron`.
- **OpenSCAD:** a complete script defining all functions and constants; no
  external modules; no export.

Then mark the part **not manufacturable** in `partcad.yaml` — a generated part is
not a catalog/supplier item, and this is what lets `pc test` pass:

```yaml
parts:
  <name>:
    type: <kind>
    path: <name>.<ext>
    desc: <the description>
    manufacturable: false
```

If you started the project with `pc init`, also delete the empty `sketches:` and
`assemblies:` sections it leaves — a null section crashes `pc render` on older
PartCAD (fixed in partcad/partcad#470).

## 6. Validate

`pc test` is the build gate: with `manufacturable: false`, its CAD check passes
only if the geometry instantiates cleanly, and the manufacturability checks are
skipped.

```sh
pc --no-ansi test <name>
```

## 7. Render it from several angles, compare, and iterate

`pc test` proves the geometry instantiates. It says nothing about whether the
geometry is the part that was asked for — that is decided by looking at it.

One picture is not enough to decide it. A projection hides everything behind it,
so a hole in the wrong face, a feature on the wrong side, a chamfer that never
got cut, or a shape that is right in outline and wrong in depth all survive the
one view that happens to conceal them. Render **four**: `front`, `top` and
`right` to read proportions and dimensions off, and `iso` to see how the features
go together. A rendered file is named after the object, so give each view a
directory of its own or they overwrite each other:

```sh
for view in front top right iso; do
  mkdir -p /tmp/pc-render/$view                  # -O expects it to exist
  pc --no-ansi render -t png --view $view -O /tmp/pc-render/$view <name>
done
```

Then view all four — `/tmp/pc-render/<view>/<name>.png` — and compare them
against the description and any reference images:

- the overall form and the bounding size, in all three axes;
- every dimension the description states — each is measurable in one of the
  orthographic views, and a dimension no view confirms is one still assumed;
- every feature that was asked for, on the face it was asked for, and nothing
  present that was not.

Add `back`, `left` or `bottom` whenever the part is not symmetric about the axis
in question: an asymmetric part has a face you have not seen, and a face you have
not seen is a face you are guessing about. When no named view shows the feature
you need to check, `--viewport-origin X,Y,Z` and `--viewport-up X,Y,Z` look from
an arbitrary direction. `/pc:render` covers these options in full.

Fix any error or mismatch, then re-test and re-render. Iterate until every view
matches — no fixed retry count. If the part is right and the numbers are what
need checking, `/pc:describe` renders a dimensioned drawing of it.

## 8. Finalize

Summarize what you built — key dimensions and assumptions — and how to view it:
`pc inspect <name>`.

If the part is meant to connect to something — a bolt pattern, a plug, a rail —
say so and offer `/pc:add-interfaces`, which adds the ports and interfaces that
let PartCAD mate it automatically. Once it has them, `--with-all` draws them on
the very views you have been comparing against, so a port that is in the wrong
place or facing the wrong way is visible rather than inferred:

```sh
for view in front top right iso; do
  mkdir -p /tmp/pc-render/ports/$view
  pc --no-ansi render -t png --view $view -O /tmp/pc-render/ports/$view --with-all <name>
done
```

Four views again, and for the same reason: a port is a coordinate frame, and one
projection collapses the axis it is offset along just as it does for geometry.
`--no-ansi` because every port drawn is also named on stderr, which is where the
exact string to write in an ASSY file comes from. `/pc:add-interfaces` covers
reading these drawings in full.
