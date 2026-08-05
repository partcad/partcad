---
name: describe
description: Write a narratable, accessibility-oriented text description of an existing PartCAD part, assembly, or sketch by rendering it and examining the result. Use for /pc:describe or when the user asks to describe, summarize, or caption a PartCAD object. Reproduces the retired built-in AI shape-summary.
---

# pc:describe

Produce a text description of an existing PartCAD shape by rendering it and
looking at the result — the replacement for PartCAD's retired built-in AI
summary. The text after the command (`$ARGUMENTS`) names the object to describe
(optionally with its kind).

## 1. Resolve the object

`$ARGUMENTS` is the object name (a part by default; an assembly or sketch if the
user says so). Read its `desc:`/`requirements:` from `partcad.yaml` for context.
Make sure PartCAD is available as `/pc:init` describes.

## 2. Render it

```sh
mkdir -p /tmp/pc-render
pc render -t png -O /tmp/pc-render <name>       # a part (default); add -a for an assembly
pc render -s -t svg -O /tmp/pc-render <name>    # a sketch renders to SVG, not PNG
```

View the produced file — `/tmp/pc-render/<name>.png` for a part or assembly,
`/tmp/pc-render/<name>.svg` for a sketch.

## 3. Write the description

From the image plus the configured `desc`/`requirements`, write a description
for a reader who has a mechanical-engineering / CAD background but cannot see it:

- Describe both the overall shape and the dimensions; make no assumptions and
  add as much concrete detail as the render and config support.
- Refer to it as "this design", not "the image".
- Produce prose that is ready to be narrated as-is (no markdown, no lists).

## 4. Persist it (so `pc inspect` shows it)

`pc inspect` reads a shape's `summary:` from its configuration. Write your
description there so the tool and other agents can reuse it:

```yaml
parts:            # or sketches: / assemblies:
  <name>:
    ...
    summary: >-
      <your description>
```

Report the description to the user and confirm where you stored it.
