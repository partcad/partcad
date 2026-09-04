---
name: export
description: Write a CAD file out of an object a PartCAD package declares - STEP, BREP, STL, 3MF, OBJ, IGES, glTF, three.js, URDF for 3D, SVG or DXF for a sketch, or a file type the package implements itself - using `pc export`, which changes nothing in `partcad.yaml`. Use for /pc:export or when the user asks to export, save out, dump, hand off, or produce a CAD file of a part, sketch, assembly or whole package - for a printer, a supplier, a simulator, or another CAD tool. For a bare file with no package use /pc:convert; for a 2D picture use /pc:render.
---

# pc:export

Write geometry out of a package, leaving the package exactly as it was.
`$ARGUMENTS` says what to export and to what.

`pc export` is the close sibling of `pc convert`, and the difference is the whole
reason to know both:

|  | writes a file | changes `partcad.yaml` | formats |
| --- | --- | --- | --- |
| `pc export` | yes | **no** | more — `urdf`, plus any a package implements itself |
| `pc convert` | yes | **yes** — the object *becomes* the new format | a fixed list per kind |

So this is what to use whenever someone wants a file *out* of a package — to
print, to quote, to import somewhere else — which is nearly always what "export
it as STEP" means. `/pc:convert` is for the rarer case where the object itself
should stop being what it is.

## 1. Work out which case you are in

Do this before running anything. It is the same first step in `/pc:convert` and
`/pc:render`.

1. **Is there a package?** PartCAD searches upward for `partcad.yaml`, so look in
   the current directory and above. `pc --no-ansi list` lists what the package
   holds; if there is no package it says so.
2. **Does the reference name an object?** Check it against
   `pc --no-ansi list parts` / `list sketches` / `list assemblies`.
   `pc --no-ansi info <name>` succeeds only for an object that resolves.
3. **Does a file the user named belong to an object?** Someone who says "export
   `bracket.step` as STL" inside a package usually means the part built from it.
   Read `partcad.yaml` and look for an object whose `path:` is that file — and
   note that a file-backed object *without* a `path:` is `<name>` plus the type's
   extension, so a part `bracket` of type `step` is `bracket.step` whether or not
   the path is written down.

**If 2 or 3 matched, it is an object: use `pc export` (§3).**

**If there is no package, or the file is not one an object is built from, there
is nothing to export from.** A bare file is converted, not exported: hand it to
`pc adhoc convert` — that is `/pc:convert` §4, and it is the ad-hoc equivalent of
this skill, since it too writes a file and changes no package.

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:setup executable` first.

Pass `--no-ansi` on every run so the output is plain text. It is a global flag
and goes before the subcommand, and it routes the logs to **stderr** — so
capture both streams when reading them: `pc --no-ansi export ... 2>&1`.

## 3. Export

```sh
mkdir -p ./out                                       # -O expects the directory to exist
pc --no-ansi export -t stl -O ./out bracket          # a part
pc --no-ansi export -t step -O ./out -a gearbox      # an assembly (-a)
pc --no-ansi export -t dxf -O ./out -s outline       # a sketch (-s)
pc --no-ansi export -t stl -O ./out -P //pub/std bolt  # an object in another package
```

Formats: `step`, `brep`, `stl`, `3mf`, `threejs`, `obj`, `gltf`, `iges`, `urdf`,
`svg`, `dxf`, plus any file type a package implements itself. `-t urdf` writes a
`.urdf` plus the directory of mesh files it references — it is the one that
produces more than one file.

`svg` and `dxf` are the flat pair, and are what a **sketch** exports to: a sketch
is already 2D, so this is its geometry and not a picture of it. A part or an
assembly accepts them as well, but what comes back is a projection — if that is
what is wanted, `/pc:render` is the command that says so, and the viewing-angle
options exist only there.

Useful options:

- `-O <dir>` — where the files go. The directory must exist; add `-p` to create
  the structure a configured output path needs.
- **No object name** exports everything the package declares; `-r` walks the
  imported packages too. Say what that will produce before running it on a
  package that imports the public index.
- `-e <package>` — read another package's `export:` options and implementations,
  which is how one package's exporter is applied to another's objects.

Each file is named after the object, so exporting several objects into one
directory is safe — unlike several *views* of one object, which is `/pc:render`.

If the format the user asked for is not in the list, check whether the package
implements it: read the `export:` and `render:` sections of `partcad.yaml`. A
package can declare a file type of its own, and it is then nameable with `-t`
like any other.

## 4. Report what happened

Name the files that were written, with their paths — all of them for `-t urdf`
or a whole-package export, or a count plus the directory when there are many.
State that `partcad.yaml` is unchanged, since that is the property that makes
this command the right one. If PartCAD printed an error, surface it verbatim.
