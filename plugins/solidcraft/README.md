# SolidCraft for PartCAD

A PartCAD plugin package for [SolidCraft](https://github.com/bherbruck/solidcraft), the open-source parametric
CAD application written in Rust. It adds what SolidCraft reads and PartCAD does not:

| What | Declared as | Reads / writes |
|---|---|---|
| A SolidCraft design (`.solidcraft`, or its plain JSON form) | `type: solidcraft:solidcraft` | read, with the part's parameters set on the design |
| A Rhino file (`.3dm`), its solids | `type: solidcraft:rhino` | read |
| An IGES file (`.igs`, `.iges`), its solids and sewn surfaces | `type: solidcraft:iges` | read |
| A SolidCraft design holding any PartCAD object | `pc export -t solidcraft:solidcraft` | write |
| SolidCraft itself, to view and edit an object in | `pc ide open --with solidcraft` | — |

`solidcraft:` is the name the workspace imports this package under; use whatever name the dependency is given.

## Using it

```yaml
dependencies:
  solidcraft:
    type: git
    url: https://github.com/partcad/partcad-plugin-solidcraft.git
    track: main

parts:
  plate:
    type: solidcraft:solidcraft   # reads plate.solidcraft
    parameters:
      height:                     # the design's user parameter of the same name
        type: float
        default: 20
  slab:
    type: solidcraft:rhino        # reads slab.3dm
  bracket:
    type: solidcraft:iges
    path: vendor/bracket.iges     # relative to this package, as for any file-backed part
```

Each part is one file, declared exactly like a STEP or an STL part: `path` relative to the package declaring the
part, `<name>.<extension>` when it is left out, and `fileFrom`/`fileUrl` to fetch it. The file is what the part's
cache entry depends on, so editing it rebuilds the part.

A SolidCraft design is parametric. Every parameter the part declares is set on the design's user parameter of the
same name before it is rebuilt, so `plate;height=35` is the plate at 35 mm.

What PartCAD gets from any of the three is the solid SolidCraft writes out as STEP: a design's history stays in the
design.

## Where SolidCraft comes from

Everything here runs SolidCraft's command line tool, `solidcraft-cli`. Whichever comes first is used:

1. **A `solidcraft-cli` on the `PATH`.** A machine that installed SolidCraft, or this package's image.
2. **This package's image**, `ghcr.io/partcad/partcad-plugin-solidcraft:<version>` (built from [`Dockerfile`](Dockerfile)),
   named as the package's `dockerImage`. PartCAD runs the scripts in it where its `docker` sandbox is in use and the
   image can be pulled, and falls back to its own sandbox, with a note, where it cannot.
3. **A download on first use.** The release pinned in [`solidcraft_tool.py`](solidcraft_tool.py), verified against
   its published SHA-256 before it is unpacked, kept in this package's cache directory (`request["cache_dir"]`, which
   is `.cache/` beside this file) and reused from then on. A new release of the package is a new directory and a new
   download.

`pc ide open --with solidcraft` finds an installed SolidCraft (the `PATH`, `SolidCraft.app`, Windows' program
directories, the `ai.storyteller.solidcraft` Flatpak) and otherwise runs the same image, pulled on demand, with the
display forwarded into it.

Editing in SolidCraft: SolidCraft is offered a SolidCraft design first, then STEP and IGES, then meshes; anything
else is converted to STEP on the way. glTF is deliberately not on the list, because SolidCraft cannot write it back.

## Updating SolidCraft

Change `VERSION` and every checksum in `solidcraft_tool.py` (from the release's `SHA256SUMS.txt`), the
`SOLIDCRAFT_*` defaults in `Dockerfile`, and the image tag in `partcad.yaml`, and raise `CACHE_VERSION` in
`read_part.py` and `export_solidcraft.py` if what they produce changes. Then publish the image for both
architectures, with the tags the comment at the top of the `Dockerfile` shows.

## Licences

This package is Apache-2.0. SolidCraft is MIT OR Apache-2.0, and is downloaded from its own releases rather than
redistributed here.
