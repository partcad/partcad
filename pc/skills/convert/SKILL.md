---
name: convert
description: Convert a CAD file or a PartCAD object to another geometry format - STEP, BREP, STL, 3MF, OBJ, IGES, glTF, three.js, SVG, DXF, URDF, ASSY - with `pc convert` for an object a package declares (which changes what that object is) or `pc adhoc convert` for a file that belongs to no package. Use for /pc:convert or when the user asks to convert, translate, re-save, or change the format of a CAD file, part, sketch or assembly. For a 2D picture use /pc:render; to write a file without changing the package use /pc:export.
---

# pc:convert

Turn geometry into another geometry format. `$ARGUMENTS` says what to convert and
to what.

Two commands do this, and picking the right one is most of the job:

- **`pc convert`** — an object a package declares. It writes the file **and
  rewrites the object's definition** in `partcad.yaml` to point at it: the part
  *becomes* the new format.
- **`pc adhoc convert`** — a file that belongs to no package. File in, file out;
  no package is created, read, or changed.

If the user wants a file *without* changing what the object is, that is
`/pc:export`. If they want a picture, that is `/pc:render`.

## 1. Work out which case you are in

Do this before running anything. It is the same first step in `/pc:render` and
`/pc:export`.

1. **Is there a package?** PartCAD searches upward for `partcad.yaml`, so look in
   the current directory and above. `pc --no-ansi list` lists what the package
   holds; if there is no package it says so.
2. **Does the reference name an object?** Check it against
   `pc --no-ansi list parts` / `list sketches` / `list assemblies`.
   `pc --no-ansi info <name>` succeeds only for an object that resolves.
3. **Does a file the user named belong to an object?** Someone who says
   "convert `bracket.step`" inside a package usually means the part built from
   it. Read `partcad.yaml` and look for an object whose `path:` is that file —
   and note that a file-backed object *without* a `path:` is `<name>` plus the
   type's extension, so a part `bracket` of type `step` is `bracket.step`
   whether or not the path is written down.

**If 2 or 3 matched, it is an object: use `pc convert` (§3).** Converting its
file behind the package's back would leave `partcad.yaml` describing a format
that is no longer there.

**If there is no package, or the file is not one an object is built from, it is
ad-hoc: use `pc adhoc convert` (§4).**

When it is genuinely ambiguous — a package exists and the file sits inside it but
nothing declares it — say which you picked and why, rather than guessing
silently.

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:setup executable` first.

Pass `--no-ansi` on every run so the output is plain text. It is a global flag
and goes before the subcommand, and it routes the logs to **stderr** — so
capture both streams when reading them: `pc --no-ansi convert ... 2>&1`.

## 3. An object in a package — `pc convert`

```sh
pc --no-ansi convert part bracket -t step
pc --no-ansi convert sketch outline -t dxf
pc --no-ansi convert assembly gearbox -t urdf
```

Target formats, by kind:

| kind | `-t` |
| --- | --- |
| `part` | `step`, `brep`, `stl`, `3mf`, `threejs`, `obj`, `gltf`, `iges` |
| `sketch` | `svg`, `dxf` |
| `assembly` | `assy`, `urdf` |

Options: `-P <package>` for an object in another package, `-O <dir>` for where
the file goes (the directory must exist; it defaults to the package directory),
and `--dry-run`.

**This edits `partcad.yaml`. Say so before you run it, and prefer `--dry-run`
first** — show the user what would change, then run it for real. What is at stake
is not the file but the object: a `cadquery` part converted to `step` is no longer
a script, so its parameters and the code that produced it stop being part of the
package. If the user only wants a STEP file to send someone, they want
`/pc:export`, not this.

An assembly conversion is the largest of these. To URDF it writes the `.urdf` and
an STL per distinct shape; to ASSY it writes an `stl` part per URDF link, an
interface pair per joint, and an `.assy` that connects the parts through them.

## 4. A file with no package — `pc adhoc convert`

PartCAD wraps the file in a throwaway package, converts it, and deletes the
package again. Types are inferred from the file names; `--input` and `--output`
say them outright when an extension is missing or misleading:

```sh
pc --no-ansi adhoc convert part bracket.step bracket.stl
pc --no-ansi adhoc convert part --input step bracket.dat bracket.stl
pc --no-ansi adhoc convert part --output 3mf bracket.step      # names the output after the input
pc --no-ansi adhoc convert sketch outline.svg outline.dxf
```

- **part** reads `step`, `brep`, `stl`, `3mf`, `threejs`, `obj`, `iges`, `gltf`,
  `cadquery`, `build123d`, `chili3d`, `sdf`, `scad`, and writes all of those
  except `chili3d`, `sdf` and `scad` — PartCAD reads those three but has no
  exporter that writes them back.
- **sketch** reads and writes `svg`, `dxf`, `cadquery`, `build123d`.
- `urdf` and `assy` are refused: an ASSY file is a set of references to the parts
  of a package and a URDF becomes a part per link, so neither means anything
  without one. A user who has a URDF needs it in a package first
  (`pc import assembly`) and then `pc convert assembly`.

Nothing here writes a picture: `pc adhoc convert sketch a.svg b.png` is refused
on purpose. Rendering a bare file is `pc adhoc render`, which is `/pc:render`.

## 5. Report what happened

Name the files that were written, with their paths, and say plainly whether
`partcad.yaml` changed — it does for `pc convert` and never for
`pc adhoc convert`. If PartCAD printed an error, surface it verbatim rather than
working around it: a conversion that fails on the geometry is a fact about the
model, not something to retry with different flags.
