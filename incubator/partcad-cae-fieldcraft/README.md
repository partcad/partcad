# partcad-cae-fieldcraft

Static stress and buckling, modal, steady heat transfer and lattice Boltzmann flow analysis for
[PartCAD](https://github.com/partcad/partcad), by [FieldCraft](https://github.com/tangency-labs/fieldcraft).
It implements all four of PartCAD's analyses:

```shell
pc cae fea :bracket        # does it hold up under what it carries -- and, with `buckling`, does it buckle
pc cae dynamic :bracket    # at which frequencies does it ring, held as it is
pc cae thermal :heatsink   # how hot does it get, heated and cooled as it is
pc cae cfd :duct           # how does a fluid flow through it
pc qual test               # every analysis a part declares, as a check that fails on any finding
```

Name it for one run with `-i //pub/feature/cae/fieldcraft:<analysis>`, for a part with `implementation:` in
the part's analysis section, or for everything with the `cae<Analysis>Implementation` user configuration
option.

## Why FieldCraft

FieldCraft is a clean-room CAE application in Rust (MIT or Apache-2.0) with **solvers of its own** -- a
sparse direct linear solver, block Lanczos for modes, linear buckling, heat conduction, and a D3Q19 lattice
Boltzmann flow solver on the CPU or the GPU -- and it ships as **one self-contained executable per platform**
(Linux x86_64, macOS on Apple silicon, Windows x64) that links nothing but the C library.

That changes what an analysis costs a user. Every other solver PartCAD drives needs either a container
runtime (to pull an image carrying CalculiX, Elmer, OpenFOAM, ...) or a native installation. This package
needs neither: when no `fieldcraft-cli` is found, it fetches the release it pins from GitHub, checks the
archive against the SHA-256 the release publishes, and keeps it under `~/.partcad/tools/`. gmsh, the mesher,
is a pip wheel PartCAD installs into the analysis's sandbox like any other requirement. So on the three
platforms above, `pc cae fea` works on a machine with nothing but PartCAD.

It also answers one question no other PartCAD implementation does: **linear buckling** (`buckling: true` on
`fea`), reported as the factor on the load at which the part buckles.

## How it runs

```
 PartCAD                          this package                             FieldCraft (fieldcraft-cli mcp)
 ───────                          ────────────                             ───────────────────────────────
 ports → faces (cae_support)  ─▶  gmsh mesh, a physical group per   ─▶     mesh.import.orphan  (MSH 4.1)
                                  condition, written as MSH 4.1            model.material / section
                                                                           model.boundary_condition / load
                                  the engine commands, one batch    ─▶     model.step  →  solve.<analysis>
                                                                           results.export.vtu
 findings + model (.glb)      ◀─  peaks, thresholds, the surface    ◀─     replies + VTU
                                  coloured by the field
```

* **The mesh is PartCAD's.** `cae_support` imprints each port's sketch on the part and names the faces it
  covers; gmsh meshes the part with a physical group per condition; `fieldcraft_common.write_msh()` writes it
  as ASCII MSH 4.1, which FieldCraft imports with each physical group as a set of the same name (a surface
  group becomes a set of element faces, which a boundary condition resolves to their nodes). So a condition
  lands exactly where it does for every other implementation, and the conformance numbers compare.
* **FieldCraft is driven over its MCP interface** (`fieldcraft-cli mcp --headless`), confined to the case
  directory. Its `batch` tool runs a list of engine commands and answers with every reply -- what the solve
  found, the frequencies, the ports of a flow -- where `fieldcraft-cli run` would print only the model
  summary. The commands are the same ones FieldCraft's UI, scripts and agents run (`fieldcraft-cli
  commands` lists them).
* **The fields come back as VTK XML** (`results.export.vtu`), and the model is the outer surface of the mesh
  coloured by them, drawn by `cae_support.write_glb()` as every PartCAD implementation draws it.

Every model is `m-kg-s-N-Pa` with temperatures in Celsius, so the material constants PartCAD hands over (SI)
go in as they are.

## What each analysis reads

| analysis | section keys | what they mean here |
| --- | --- | --- |
| `fea` | `fix:`, `load:`, `gravity:` | held still in every direction; a force spread over the faces by area (`distribution: total`), along the direction the part states (`[x, y, z]` in its frame) or along -Z for a magnitude; the acceleration the part is weighed under, in its frame |
| `dynamic` | `fix:` | held still; the lowest `modes` natural frequencies and their shapes |
| `thermal` | `temperature:`, `heat:`, `convection:` | held at a temperature (C); a power put in (W) as a flux over the port's area; a film coefficient (W/(m^2*K)) towards `ambient_temperature`. Every other surface is insulated |
| `cfd` | `load:`, `outlet:` | an inlet held at the pressure that is its force over its area; an outlet at the reference pressure. Every other surface is a no-slip wall |

### The flow, posed as a box

FieldCraft's flow solver is lattice Boltzmann: a box of cubic cells with solid obstacles in it, and flow in
and out only through the faces of the box. PartCAD reads a part under `cfd:` as the fluid volume, so the
part is posed inside out: the box is the part's bounding box, rounded up to whole cells (away from the
ports, so a port stays on its face), and the obstacle is a block with the part cut out of it, imported as a
closed surface. Each inlet and outlet is the box face its port lies on.

That is exactly the part's problem, with one restriction: **an inlet or an outlet has to lie on a face of the
part's bounding box, flat, facing along X, Y or Z** -- the ends of a straight pipe or duct, the faces of a
manifold block. A port anywhere else is refused with the reason, rather than approximated. The cells are
`mesh_size` times the part's largest dimension, or finer so that the narrowest port is `cells_across` cells
wide; the run is on the CPU backend (double precision, the same digits on every machine) and stops when the
flow and the outlets' flow rate settle, or at `end_time` -- by default ten times the time the flow is
estimated to settle in. The model is the part's surface coloured by the pressure in the fluid just inside
it.

## Parameters

All of them can be set in a package's `cae:` section, a part's, or a scenario's `params:`.

| | `fea` | `dynamic` | `thermal` | `cfd` |
| --- | --- | --- | --- | --- |
| mesh | `mesh_size` 0.05, `mesh_order` 2 | `mesh_size` 0.05, `mesh_order` 2 | `mesh_size` 0.05, `mesh_order` 2 | `mesh_size` 0.02, `cells_across` 8, `max_cells` 4e6 |
| material | `youngs_modulus`, `poissons_ratio`, `yield_strength`, `density` (steel) | `youngs_modulus`, `poissons_ratio`, `density` | `conductivity` 50, `ambient_temperature` 20 | `density` 1.204, `viscosity` 1.82e-5 (air) |
| findings | `safety_factor` 1.5, `max_displacement` 1 mm, `min_buckling_factor` 3 | `min_frequency` | `max_temperature` | `max_velocity` 50, `min_flow_rate`, a Reynolds number past 2300 without `turbulence` |
| other | `self_weight`, `scale_to_allowable`, `buckling`, `buckling_modes` | `modes` 6, `max_frequency`, `mass` | | `walls` interpolated, `steady_tolerance`, `end_time`, `turbulence`, `collision`, `outflow` |
| all | `download` true, `solve_timeout` 3600 s | | | |

A part whose `material` PartCAD can resolve is analysed as that material: PartCAD fills `youngs_modulus`,
`poissons_ratio`, `yield_strength`, `density`, `conductivity` and, for `cfd`, the fluid's `density` and
`viscosity`, unless the package, the part or the run states them. FieldCraft judges no allowable stress
itself; the safety factor and every other threshold are this package's.

## Getting FieldCraft

`fieldcraft-cli` is looked for, in order:

1. what `PARTCAD_FIELDCRAFT_BIN` names -- the executable, or the directory holding it;
2. `PATH`;
3. where the release packages put it (`/usr/bin` for the `.deb` and `.rpm`, the app bundle on macOS);
4. `~/.partcad/tools/fieldcraft-<version>/` (or `PARTCAD_FIELDCRAFT_CACHE`), where a fetched release is kept;
5. fetched: the release `FIELDCRAFT_VERSION` in `fieldcraft_common.py` (0.8.1), from
   `github.com/tangency-labs/fieldcraft/releases`, checked against the SHA-256 pinned beside it. A release
   that does not match is refused and not run. `download: false` turns this off.

As with every solver, the analysis runs in PartCAD's **daemon**'s environment, not your shell's: after
setting `PARTCAD_FIELDCRAFT_BIN`, `pc daemon stop` first.

`Dockerfile` builds an image carrying the same release, for when this package is published with a
`dockerImage:` pin. Nothing needs it until then.

## Debugging a case

```shell
pc daemon stop
PARTCAD_FIELDCRAFT_CASE=/tmp/case pc cae fea :bracket
ls /tmp/case
#   part.msh         the mesh FieldCraft was handed, with a physical group per condition
#   case.json        every command it was sent: a script `fieldcraft-cli run` replays
#   result.vtu       what it wrote back; open it in ParaView
#   log.fieldcraft   what it said on stderr
fieldcraft-cli snapshot /tmp/case/case.json --out stress.png --field von_mises
```

## Tests

```shell
pip install partcad gmsh build123d pytest pyyaml
pytest -c /dev/null --rootdir . .                                # FieldCraft not needed
PARTCAD_FIELDCRAFT_TEST_DOWNLOAD=1 pytest -c /dev/null --rootdir . .   # the closed forms, for real
python verify_image.py path/to/fieldcraft-cli                     # FieldCraft's own oracle cantilever
```

Without FieldCraft, `fake_fieldcraft.py` stands in for it: it speaks FieldCraft's MCP protocol, reads the
mesh with the rules FieldCraft's MSH reader applies, refuses definitions that name what does not exist, and
writes the mesh back as a VTU with made-up fields -- so every analysis runs end to end, on a real part, with
PartCAD's own port imprint and gmsh, everything but the arithmetic. With FieldCraft, the cantilever and the
pipe of `examples/feature_cae` in the `partcad` repository are solved and compared with their closed forms
(0.2016 mm, 815.4 Hz, 40 C, 1.5625 mL/s).

## Status

Written against FieldCraft 0.8.1's sources and documentation (`docs/mcp.md`, the command catalogue in
`crates/engine/src/cmd`, the MSH reader in `crates/io/src/gmsh.rs`), and run end to end through PartCAD 0.10.37
(`pc cae fea|dynamic|thermal|cfd` on the conformance parts) against the stand-in. **It has not yet been run
against a real `fieldcraft-cli`**: the closed-form tests above are the first thing to run, and their numbers
belong in the table in `examples/feature_cae/README.md` beside the other implementations'. The flow analysis
is the least certain part -- how FieldCraft voxelises an obstacle that reaches past its box, and whether a
pressure face takes an inflow as readily as an outflow, are read from its documentation rather than seen.
