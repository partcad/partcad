---
name: gen-sketch
description: Generate a PartCAD 2D sketch from a natural-language description by authoring the sketch (build123d / cadquery / dxf / svg / basic) and validating it with the PartCAD CLI. Use for /pc:gen-sketch or when the user asks to generate, create, or draw a 2D sketch, profile, outline, or blueprint.
---

# pc:gen-sketch

Generate one PartCAD **sketch** — a 2D profile — from a description. You author
the sketch yourself and prove it renders with the PartCAD CLI. There is no
built-in `ai-*` sketch type; *you* are the model. The hard requirement: the
sketch **renders without errors**.

The flow mirrors `/pc:gen-part`, adapted to 2D. Treat it as a strong default, not
a script — but always finish by rendering. (Sketches are not manufacturable, so
unlike parts they need no `manufacturable:` flag and skip the `cam` tests.)

## 1. Understand the request

`$ARGUMENTS` is the description. Read it and any `requirements`, and view
reference images directly. Ask the user to clarify only load-bearing
ambiguities. Work in millimeters unless told otherwise.

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:install executable` first.

## 3. Choose a representation

| Kind | Good for |
| --- | --- |
| `build123d` | parametric 2D sketches (recommended default) |
| `cadquery` | fluent 2D sketching |
| `dxf` | a DXF outline |
| `svg` | an SVG outline |
| `basic` | simple primitive-based sketches |

## 4. Author and register

Write the sketch file first, then register it:

```sh
pc add sketch <kind> <name>.<ext>       # e.g. pc add sketch build123d profile.py
```

- **build123d / cadquery (Python):** import everything you use (including `math`
  and the library itself); expose the 2D result with `show_object(<sketch>)`; do
  not export anything.
- **dxf / svg:** write the outline file directly.

Record the description in the sketch's `desc:` in `partcad.yaml`. If you started
the project with `pc init`, delete the empty null sections it leaves.

## 5. Render, compare, and iterate

Rendering is the build gate. Sketches render to SVG:

```sh
mkdir -p /tmp/pc-render                          # the -O directory must already exist
pc render -s -t svg -O /tmp/pc-render <name>     # writes /tmp/pc-render/<name>.svg
```

View `/tmp/pc-render/<name>.svg` and compare it against the description — the
outline and every stated dimension. Fix any error or mismatch, then re-render.
Iterate until it is right.

## 6. Finalize

Summarize what you drew — key dimensions and assumptions — and how to view it:
`pc inspect -s <name>`.
