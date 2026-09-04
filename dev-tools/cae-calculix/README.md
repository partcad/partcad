# partcad-cae-calculix

The [CalculiX](https://www.calculix.de/) implementations of PartCAD's two engineering analyses: what
`pc cae fea` and `pc cae cfd` run by default.

**This directory is staged, not published from here.** It is the seed of the `partcad/partcad-cae-calculix`
repository, which does not exist yet — the package is a PartCAD package rather than part of the `partcad`
wheel, and the public index reaches it as a git dependency the way it reaches
[`partcad-render-draftwright`](https://github.com/partcad/partcad-render-draftwright). Nothing in this
repository builds, tests or ships it; it sits under `dev-tools/` for the same reason `dev-tools/shim/` does,
which is that it is a distributable thing that is not the wheel.

## Publishing it

1. Create `partcad/partcad-cae-calculix`.
2. Copy this directory's contents to its root and push.
3. Register it in [`partcad-index`](https://github.com/partcad/partcad-index), in
   `feature/cae/partcad.yaml`:

   ```yaml
   import:
     calculix:
       desc: Finite element and fluid dynamics analysis, by CalculiX.
       type: git
       url: https://github.com/partcad/partcad-cae-calculix
       web: https://www.calculix.de/
   ```

   That is what makes `//pub/feature/cae/calculix:fea` resolve, which is the default
   `caeFeaImplementation` in PartCAD's user configuration. Until it does, `pc cae fea` reports that the
   package implementing `fea` is not found.

## What it is

Two file types in a `cae:` section, which is the same shape as an `export:` or a `render:` one — `path` names
the script, `pythonRequirements` describes its sandbox, `extension` says what it writes, and everything else
is a parameter handed to the script:

| File type | What it does | Writes |
| --- | --- | --- |
| `fea` | A linear static stress analysis of the part | a glTF coloured by von Mises stress |
| `cfd` | Incompressible flow through the part, read as the fluid volume | a glTF coloured by speed |

Both are handed the part's own boundary conditions — `fix:` and `load:` from its `fea:`/`cfd:` section, with
every load already in newtons — and both answer with **findings**: the JSON array of what the analysis has to
say about the part. An empty one is a pass, which is what `pc test`'s `fea` and `cfd` checks require.

### The pipeline

    the part  →  gmsh  →  a tetrahedral mesh
    a port    →  the nodes within `port_radius` of it  →  a CalculiX node set
    a deck    →  ccx  →  a .frd
    a field   →  a colour per node  →  a binary glTF

`calculix_common.py` is all of that except the deck and the field, which are the only two things the two
analyses actually differ in.

### A port is a neighbourhood, not a face

This is the one modelling decision worth arguing with. A PartCAD port is a coordinate frame: it says where a
bolt goes, not which surface it clamps. So a fixed port becomes the mesh nodes within `port_radius` (a
fraction of the part's largest dimension) of where the port is, and a loaded port spreads its force over the
same neighbourhood. Get that radius wrong and the answer is wrong in a way that looks plausible — too small
and the load is a point load with an artificial stress concentration under it, too large and a bolt hole
clamps half the bracket. It is a parameter of the file type for exactly that reason, and a port that reaches
no material at all is reported as a finding rather than passed over.

### What `cfd:` reads the part as

The **fluid volume** — the space the fluid is in, not the wall around it. A duct is analysed by declaring the
bore as a part, not the casting. `fix:` names the walls (no slip) and `load:` names where the flow is driven:
a force on a boundary divided by the area of that boundary is a pressure, and pressure is what an
incompressible solver is driven by. That is why `cfd:` takes a force rather than a velocity — it is the same
declaration the part already makes for FEA, in the same units, meaning the same physical thing.

## What it needs

`gmsh`, `numpy` and `trimesh` are `pythonRequirements` and PartCAD installs them into the sandbox itself.

**`ccx` is not one of them.** It is a native executable, pip cannot install it, and PartCAD does not ship
solvers. Install it the way the platform does:

```shell
apt install calculix-ccx                     # Debian, Ubuntu
brew install calculix-ccx                    # macOS
conda install -c conda-forge calculix        # anywhere conda is
```

It is looked up on `PATH` and then in the usual places; `PARTCAD_CCX` names it outright on a machine where it
lives somewhere else. A machine with no solver is told so as a sentence saying what to install — that is a
finding about the machine, not about the part.

## Status

**Untested.** The pipeline is written against CalculiX 2.20+ and gmsh 4.x, and it has not been run: the
machine it was written on has neither. The deck-writing, the `.frd` parsing and the port-to-node-set mapping
are the parts most likely to need correcting against a real solver. Treat the numbers with suspicion until
somebody has checked one against a case with a known answer — a cantilever beam under a tip load is the usual
one, and its closed form is in every strength-of-materials text.
