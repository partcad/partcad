---
name: render
description: Render a PartCAD object or a CAD file to a 2D image - PNG, JPEG, SVG or DXF - from one or many viewing angles (front, back, left, right, top, bottom, iso, or an arbitrary direction), with `pc render` for an object a package declares or `pc adhoc render` for a file that belongs to no package. Use for /pc:render or when the user asks to render, draw, screenshot, preview, or produce an image or projection of a part, sketch, assembly or CAD file, or to see it from a particular view, or to draw an object's ports and interfaces on it (--with-ports / --with-interfaces / --with-all). For geometry another CAD tool can open use /pc:export or /pc:convert.
---

# pc:render

Produce a picture of a shape: a 2D projection, in `png`, `jpeg`, `svg` or `dxf`.
`$ARGUMENTS` says what to render and, often, from where.

A render is not a conversion. It writes something to look at, not geometry
another CAD tool can go on working with — that is `/pc:export` (or `/pc:convert`
when the object should *become* the new format). The viewing angle only means
anything here.

Two commands do it:

- **`pc render`** — an object a package declares. Reads the package's `render:`
  configuration, so the object is drawn the way the package publishes it.
- **`pc adhoc render`** — a file that belongs to no package. PartCAD wraps it in
  a throwaway package, writes the picture, and deletes the package again.

## 1. Work out which case you are in

Do this before running anything. It is the same first step in `/pc:convert` and
`/pc:export`.

1. **Is there a package?** PartCAD searches upward for `partcad.yaml`, so look in
   the current directory and above. `pc --no-ansi list` lists what the package
   holds; if there is no package it says so.
2. **Does the reference name an object?** Check it against
   `pc --no-ansi list parts` / `list sketches` / `list assemblies`.
   `pc --no-ansi info <name>` succeeds only for an object that resolves.
3. **Does a file the user named belong to an object?** Someone who says "render
   `bracket.step`" inside a package usually means the part built from it. Read
   `partcad.yaml` and look for an object whose `path:` is that file — and note
   that a file-backed object *without* a `path:` is `<name>` plus the type's
   extension, so a part `bracket` of type `step` is `bracket.step` whether or not
   the path is written down.

**If 2 or 3 matched, it is an object: use `pc render` (§3).** That way the
package's own `render:` options apply — its pixel size, its prefix, the viewport
it publishes the object with — and the picture matches every other picture of
that package.

**If there is no package, or the file is not one an object is built from, it is
ad-hoc: use `pc adhoc render` (§4).**

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:install executable` first.

Pass `--no-ansi` on every run so the output is plain text. It is a global flag
and goes before the subcommand, and it routes the logs to **stderr** — so
capture both streams when reading them: `pc --no-ansi render ... 2>&1`.

## 3. An object in a package — `pc render`

```sh
mkdir -p ./out                                          # -O expects the directory to exist
pc --no-ansi render -t png -O ./out bracket             # a part
pc --no-ansi render -t png -O ./out -a gearbox          # an assembly (-a)
pc --no-ansi render -t svg -O ./out -s outline          # a sketch (-s; SVG suits one better than PNG)
pc --no-ansi render -t png -O ./out -P //pub/std bolt   # an object in another package
```

Formats: `png`, `jpeg`, `svg`, `dxf`, plus any a package implements itself.
`-t readme`, `-t pdf` and `-t html` are documents rather than projections (a
package README, or an assembly's bill of materials and instruction book) — they
take no viewing angle.

The file is written into `-O` and named after the object. Nothing about the
package changes.

## 4. A file with no package — `pc adhoc render`

```sh
pc --no-ansi adhoc render part bracket.step bracket.png
pc --no-ansi adhoc render part --output svg bracket.step        # names the output after the input
pc --no-ansi adhoc render part --input step bracket.dat out.png
pc --no-ansi adhoc render sketch outline.svg outline.png
```

Both types are inferred from the file names; `--input` and `--output` say them
outright. The input may be any type PartCAD reads — including the scripted ones
it cannot write back out (`sdf`, `scad`, `chili3d`), since reading is all a
picture needs. The output is one of the four projections.

`urdf` and `assy` are refused here: both only mean anything inside a package. Put
the file in one (`pc import assembly`) and render it with `pc render`.

## 5. Choosing the angle

Both commands take the same three options.

`--view` names a direction — `front`, `back`, `left`, `right`, `top`, `bottom`,
`iso`. `--viewport-origin X,Y,Z` says where to look from and `--viewport-up
X,Y,Z` which way is up in the picture; each replaces the vector `--view`
resolved to, so a named view can be tilted by giving one of them alone:

```sh
pc --no-ansi render -t png --view front -O ./out bracket
pc --no-ansi render -t png --view top --viewport-up 0,1,0.5 -O ./out bracket
pc --no-ansi adhoc render part --viewport-origin 120,-40,60 bracket.step bracket.png
```

PartCAD is Z-up, with `+Y` pointing away from the front view — so `+X` is to the
right of it and `+Z` is up. Left unset, a part is drawn from the front-right-top
corner (`iso`), which is what makes it read as 3D, and a sketch head-on.

These are the same `viewport_origin` and `viewport_up` a `render:` file type is
configured with in `partcad.yaml`, passed for one command instead of written
down. If the user wants an object drawn that way *every* time, put it in the
configuration instead — and note this is only possible for an object in a
package, which is one more reason to prefer §3 over §4 when both would work:

```yaml
parts:
  bracket:
    type: step
    path: bracket.step
    render:
      png:
        viewport_origin: [0, -100, 0]
        viewport_up: [0, 0, 1]
```

## 6. Several angles at once

A rendered file is named after the object, so views written into one directory
overwrite each other. Give each its own directory (`pc render`) or its own file
name (`pc adhoc render`):

```sh
for view in front top right iso; do
  mkdir -p ./out/$view
  pc --no-ansi render -t png --view $view -O ./out/$view bracket
done
```

```sh
for view in front top right iso; do
  pc --no-ansi adhoc render part --view $view bracket.step bracket-$view.png
done
```

Then look at the images. Four views — `front`, `top`, `right`, `iso` — describe
most parts; add `back`, `left` or `bottom` only when the shape is not symmetric
about the axis in question.

## 7. Drawing the ports and interfaces

Ports and interfaces are not geometry — a port is a coordinate frame and an
interface is a named set of them — so nothing about them reaches a projection
unless it is asked for. `pc render` draws them (`pc adhoc render` does not: a
file with no package has none):

```sh
mkdir -p ./out/ports
pc --no-ansi render -t png --view iso -O ./out/ports --with-ports bracket
pc --no-ansi render -t png --view iso -O ./out/ports --with-interfaces bracket   # overwrites the above
pc --no-ansi render -t png --view iso -O ./out/ports --with-all bracket          # both at once
```

`--with-ports` marks and names every port, `--with-interfaces` names each
interface instance and joins it to the ports it owns, and `--with-all` draws
both. On an assembly or a scene all three walk everything inside it and place
each child's ports where it put the child, which is how a connection that went
wrong is found: two frames that should have met and did not. Every port drawn is
also named on stderr, which is where the exact string for an Assembly YAML file
comes from — so `--no-ansi`, and read both streams.

The overlays are subject to §6 twice over: each writes `<name>.png` like any
other render and so needs a directory or a name of its own, and a frame offset
along the line of sight is hidden exactly as a feature would be, so an ambiguous
port is worth the same several views the shape got.

A package can ask for this permanently instead, with `with_ports:` or
`with_interfaces:` on one of its `render:` file types. `/pc:add-interfaces`
covers reading these drawings when the ports themselves are what is being
worked on.

## 8. Report what happened

Name the files that were written, with their paths, and which view each one is.
Nothing in this skill changes `partcad.yaml` — say so if the user might have
expected otherwise. If PartCAD printed an error, surface it verbatim.

When the user wanted a description rather than the pictures themselves,
`/pc:describe` writes one from a render.
