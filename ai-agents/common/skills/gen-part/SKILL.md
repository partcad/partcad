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
`/pc:install executable` first.

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
pc add part --desc "<the description>" <kind> <name>.<ext>   # e.g. build123d bracket.py
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
pc test <name>
```

## 7. Render, compare, and iterate

Produce an image and compare it against the description and any reference images
— overall shape and every stated dimension:

```sh
mkdir -p /tmp/pc-render                       # the -O directory must already exist
pc render -t png -O /tmp/pc-render <name>     # writes /tmp/pc-render/<name>.png
```

Fix any error or mismatch, then re-test and re-render. Iterate until it is right —
no fixed retry count.

## 8. Finalize

Summarize what you built — key dimensions and assumptions — and how to view it:
`pc inspect <name>`.
