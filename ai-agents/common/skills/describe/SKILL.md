---
name: describe
description: Write a narratable, accessibility-oriented text description of an existing PartCAD part, assembly, or sketch from its measured bounding box and volume, from renders taken at several viewing angles, and - where it is available - from a dimensioned technical drawing. Use for /pc:describe or when the user asks to describe, summarize, or caption a PartCAD object. Reproduces the retired built-in AI shape-summary.
---

# pc:describe

Produce a text description of an existing PartCAD shape by rendering it and
looking at the result — the replacement for PartCAD's retired built-in AI
summary. The text after the command (`$ARGUMENTS`) names the object to describe
(optionally with its kind).

One picture is not enough to describe a shape. A single projection hides
everything behind it, and a description written from one is a description of a
silhouette. Render **three views** (§3), and where a dimensioned drawing can be
had, read the numbers off that rather than estimating them (§4).

Nor is any picture enough to give a size. A projection is rendered to fit its
frame, so nothing in it says whether the part is 20 mm across or 200 — which is
why this starts by asking PartCAD what it measured (§2) and never estimates a
dimension a number was available for.

## 1. Resolve the object

`$ARGUMENTS` is the object name (a part by default; an assembly or sketch if the
user says so). Read its `desc:`/`requirements:` from `partcad.yaml` for context.
Make sure PartCAD is available as `/pc:init` describes.

Pass `--no-ansi` on every run so the output is plain text; it is a global flag,
goes before the subcommand, and routes the logs to stderr.

This skill describes an object a package declares, because §6 stores the result
back into that package. To describe a bare CAD file that is in no package, render
it with `/pc:render` (`pc adhoc render`) and write the description for the user
instead of storing it.

## 2. Measure it

`pc info` reports what PartCAD measured when it built the object, and those are
the numbers this description is anchored on:

```sh
pc --no-ansi info <name> 2>&1 | grep -A 3 -E 'BoundingBox|Volume|Solids'   # add -a / -s for an assembly or a sketch
```

- **`BoundingBox`** — `min`, `max` and `size` in millimetres. `size` is the
  overall envelope of the design: state it, and give every other dimension in
  proportion to it rather than in pixels.
- **`Volume`** — how much material is in it, in cubic millimetres, with
  `Solids` saying how many solids that is the volume of. More than one solid in
  a part is worth saying out loud: it is usually either deliberate (a part that
  is two pieces) or a mistake nobody has noticed. A *negative* volume means the
  faces are oriented inward — report that as a defect rather than dropping the
  sign.
- A **sketch**, a shell or a wire has no volume, and `pc info` says so by
  leaving `Volume` out. It is flat, so its bounding box is its size.

The rest of what `pc info` prints is worth a look too, and for an object read
from a file it is where the design's own words are: a STEP file's `File`,
`Products`, `Layers` and `Properties`, a DXF sketch's `Drawing`, `Layers` and
`Annotations` — including the `angle`, `radius` and `direction` of a sheet metal
bend. Anything stated there is the design's own and beats a reading off a
picture.

The first run builds and measures the object, so it is slow; every run after it
is a cache hit. If it fails — no sandbox, a part that does not build — say so in
the report and describe the shape from the views alone, without inventing a
size.

## 3. Render three views

`front`, `top` and `iso`: two orthographic views to read proportion and features
from, and one pictorial view that shows how they go together. A rendered file is
named after the object, so give each view a directory of its own or they
overwrite each other:

```sh
for view in front top iso; do
  mkdir -p /tmp/pc-render/$view
  pc --no-ansi render -t png --view $view -O /tmp/pc-render/$view <name>   # add -a for an assembly
done
```

View all three — `/tmp/pc-render/<view>/<name>.png`.

Add `right` (or `back`, `left`, `bottom`) when the three leave a face
unaccounted for: a part that is not symmetric about an axis has a side you have
not seen, and guessing at it is exactly what this skill must not do.

A **sketch** is flat, so it has only one view worth rendering, and SVG suits it
better than PNG:

```sh
mkdir -p /tmp/pc-render
pc --no-ansi render -s -t svg -O /tmp/pc-render <name>
```

## 4. Render a dimensioned drawing (parts, when it is available)

The projections above show shape but no numbers. `draftwright`, a render
implementation published in the public PartCAD index, draws a **fully dimensioned
technical drawing** instead — orthographic views with dimension lines, hole
callouts, radii, an ISO view, and a title block carrying the material and scale.
Reading a description off that beats estimating from pixels:

```sh
mkdir -p /tmp/pc-render/drawing
pc --no-ansi render -t pdf -e //pub/feature/render/draftwright \
    -O /tmp/pc-render/drawing <name>
```

`-e` names the package to read the output configuration from, so this works on
any object without that object's package knowing about draftwright. Then read
`/tmp/pc-render/drawing/<name>.pdf` — ask for **`pdf`**, whose pages can be
looked at directly. Its `svg` draws every character as paths, so no text can be
read out of that markup.

This is a best-effort extra, not a requirement. It needs the public index among
the package's `dependencies:` (which `pc init` writes) and a network connection,
and the first run is slow while PartCAD installs draftwright into a sandbox. It
is also a *part* drawing — do not expect it of an assembly or a sketch.

draftwright reports what it could not do. When a part has features it cannot
dimension at the chosen scale it says so and draws the rest, and the command may
exit non-zero having still written a usable file — so check whether the file
appeared before giving up on it. If it did not, or anything above failed,
describe the object from the three views and say in your report that no
dimensioned drawing was available.

## 5. Write the description

From the measurements, the images and the configured `desc`/`requirements`,
write a description for a reader who has a mechanical-engineering / CAD
background but cannot see it:

- **State every measurement §2 produced, and say so when it produced none.**
  The overall envelope in millimetres, and for a part how much material is in
  it: those are measurements rather than impressions, and they are what tells a
  reader whether this is a bracket or a building. Where `pc info` gave no such
  number — a sketch, which has no volume; a part that would not build; a machine
  with no sandbox — write that the measurement was unavailable. Saying so costs
  a clause; the alternative is a figure you made up, which is the one thing this
  skill exists to prevent.
- Describe both the overall shape and the dimensions; make no assumptions and
  add as much concrete detail as the renders and config support.
- Prefer a measured or stated dimension over one you judged from a projection:
  `pc info` first, then the dimensioned drawing, then the picture. Where you are
  reading a proportion off a picture rather than a stated number, say it is
  approximate rather than inventing a figure.
- Work through the views: overall form and bounding size first, then the
  features each view reveals, then how they relate.
- Refer to it as "this design", not "the image" — and never as "the three
  images", which is an artifact of how you looked at it.
- Produce prose that is ready to be narrated as-is (no markdown, no lists).

## 6. Persist it (so `pc inspect` shows it)

`pc inspect` reads a shape's `summary:` from its configuration. Write your
description there so the tool and other agents can reuse it:

```yaml
parts:            # or sketches: / assemblies:
  <name>:
    ...
    summary: >-
      <your description>
```

Report the description to the user, say which views (and whether a dimensioned
drawing) it was written from and which numbers were measured rather than judged,
and confirm where you stored it.
