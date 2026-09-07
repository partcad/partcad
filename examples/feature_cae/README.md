# Engineering analysis with a known answer

PartCAD ships no solver. `pc cae fea` and `pc cae cfd` run whatever
`caeFeaImplementation` / `caeCfdImplementation` name, and are only ever as right
as that implementation is. These two parts are how you find out which.

Each is a textbook case whose answer is a formula, so what the solver returns can
be compared against arithmetic instead of against expectations. That is the whole
point: a unit test can show the code does what its author meant, and cannot show
that what the author meant is what the solver expects.

It has earned itself already. The first run of these two cases against a real
CalculiX found four defects stacked in front of the solver, one of which
answered `0.0000 mm` rather than failing — an answer a reader could have
believed. All four are fixed in
[`partcad-cae-calculix`](https://github.com/partcad/partcad-cae-calculix); the
numbers below are from after that.

```shell
pc cae fea :cantilever
pc cae cfd :pipe
```

Both need a solver installed. For the default implementation that means `ccx` on
`PATH` — `apt install calculix-ccx`, `brew install calculix-ccx`, or
`conda install -c conda-forge calculix`. Without one the analysis does not run,
and `pc test` says so and moves on rather than failing the part.

**Not on 64-bit ARM Linux.** The mesher the CalculiX implementation uses, `gmsh`,
publishes no linux aarch64 wheel and no source distribution — in any release —
so on an ARM Linux machine or CI runner there is nothing to install and nothing
to build. These two parts are reported as not analysable there, the same way
they are on a machine with no `ccx`. Apple silicon is fine: macOS reports
`arm64`, which gmsh does publish. See "Platforms" in
[`partcad-cae-calculix`](https://github.com/partcad/partcad-cae-calculix)'s
README.

> **A temporary arrangement, and why it is here.** `//pub/feature/cae/calculix`
> is registered on the public index's `devel` branch and has not reached `main`,
> which is what `examples/partcad.yaml` and every `pc init` project pin — so the
> default `caeFeaImplementation` resolves to nothing. Rather than repin the whole
> examples tree at the index's `devel`, which would drag in unrelated changes,
> this package depends on
> [`partcad-cae-calculix`](https://github.com/partcad/partcad-cae-calculix)
> directly and each part names it:
>
> ```yaml
> fea:
>   implementation: calculix:fea
> ```
>
> `implementation:` is a general thing — a part saying which solver it was
> written against, outranked only by `-i` — but the `dependencies:` entry and
> these two lines exist for this reason and go away once the index carries
> `feature/cae`. `partcad.yaml` says so where they are.
>
> `calculix` there is relative, and resolves against *this* package, so it means
> the same thing however deep in a tree the command is run — which is what makes
> `pc test -r` from the examples root work. A relative name a user types is not
> the same: `-i calculix:fea` below means the `calculix` beside the user, so it
> wants this directory.

## 1. Cantilever beam — `cantilever`

A 100 × 10 × 10 mm steel bar, held at one end, pulled down by 100 N at the other.

| | |
| --- | --- |
| Length `L` | 0.100 m |
| Section `b` × `h` | 0.010 × 0.010 m |
| Young's modulus `E` | 200 GPa |
| Tip load `P` | 100 N |
| Self weight | **off** — the closed form below has none |

Second moment of area `I = bh³/12 = 8.3333e-10 m⁴`, and:

- **Tip deflection** `δ = PL³/3EI` = **0.2000 mm**
- **Peak bending stress** `σ = PLc/I = 6PL/bh²` = **60.0 MPa**

Those are Euler–Bernoulli, which ignores shear. Adding the Timoshenko term
`PL/kGA` (k = 5/6, G = 76.9 GPa) gives 0.0016 mm more, so a 3D solid element
model of a *perfectly* clamped beam should land at **0.2016 mm**, +0.8 %.

### What it actually reads, and why that is right

**0.1655 mm**, with a peak von Mises stress of **58.28 MPa**. Measured with
CalculiX 2.23 on macOS arm64.

That is 17.9 % below the closed form, and it is the model rather than the solver.
`fix:` names a port, a port is a coordinate frame, and the implementation turns
it into "every mesh node within `port_radius` of this point". Here that is a
7.5 mm ball at the root — the smallest that covers the whole 10 × 10 end face,
whose half-diagonal is 7.07 mm — and it clamps part of the bar's *length* along
with it. The load ball does the same at the tip. Measured from the mesh, the
clamp reaches 6.8 mm in from each end, leaving a free span of 86.4 mm; and
deflection goes as the cube of the span.

The reading is mesh-converged, so it is a property of the model and not of
`mesh_size`:

| `mesh_size` | elements | tip deflection | peak von Mises |
| --- | --- | --- | --- |
| 0.05 | 434 | 0.1650 mm | 58.29 MPa |
| **0.03** (as configured) | **2375** | **0.1655 mm** | **58.28 MPa** |
| 0.02 | 6468 | 0.1631 mm | 59.13 MPa |

Stable to within 1.5 % across a 15× range of element counts.

**Peak stress is not the number to compare.** The reported peak sits wherever the
constraint bites, and an artificial constraint makes an artificial stress
concentration. 60 MPa is what the *bending* is; 58.28 MPa is close, and a solver
reporting rather more at the clamp would not be wrong.

Which leaves the finding worth having: **getting within a few percent needs
`fix:` to clamp a face, not a ball.** That is the concrete improvement this case
argues for, and it is now measured rather than predicted.

Readings that would mean something else:

| reading | likely cause |
| --- | --- |
| exactly 0.0000 mm | the `PORT0` node-set collision is back — the clamp is holding the loaded end too |
| ~0.2 mm | the clamp is reaching less material than a 7.5 mm ball should |
| off by ~1000× | millimetres against metres somewhere in the deck |
| ~2× low | only half the load applied, or the load spread over both end faces |
| ~0.0006 mm too much | `self_weight` crept back on |
| no convergence | the clamp reached no material — `pc render --with-ports cantilever` |

## 2. Pipe flow — `pipe`

The **bore** of a 10 mm × 100 mm pipe (the fluid, not the tube), driven by 5 mN
at the inlet, held no-slip along the wall.

| | |
| --- | --- |
| Diameter `d` | 0.010 m |
| Length `L` | 0.100 m |
| Density `ρ` | 900 kg/m³ |
| Dynamic viscosity `μ` | 0.1 Pa·s |
| Inlet force `F` | 0.005 N |

`Δp = F/A` = 63.66 Pa over the bore area `A` = 7.854e-5 m², and Hagen–Poiseuille
gives

- **Mean velocity** `u_mean = d²Δp/32μL = F/8πμL` = **0.01989 m/s**
  (the radius cancels)
- **Centreline velocity** `u_max = 2u_mean` = **0.03979 m/s**
- **Flow rate** `Q = u_mean·A` = **1.5625 mL/s**
- Profile `u(r) = u_max(1 − r²/R²)` — a paraboloid

The regime is checked, not assumed: `Re = ρu_mean·d/μ` = **1.79**, far below the
2300 where laminar flow ends, and the entrance length `0.06·Re·d` = 1.07 mm is
**1.1 % of the pipe**, so the flow is fully developed over essentially all of it.

### This one does not run at all, and not for the reason predicted

An earlier draft of this file predicted the pipe would *disagree*, because
`fix:` cannot say "the lateral surface" and the no-slip wall is therefore 20
port-balls with gaps between them. That prediction was not tested, and it turns
out not to be what happens. **There is no measurement to compare, because the
CFD solve does not converge.** Observed runs settle at a dead field — peak speed
of order 1e-16 m/s against an expected 0.03979 m/s — and end in

```
 *ERROR in compdt; strongly decreasing time increment; the solution diverged
```

At least one cause is structural rather than a mesh artefact: **`cfd:` has no way
to name an outlet.** It can name walls (`fix:`) and an inlet (`load:`), so the
incompressible problem is posed with no downstream pressure reference. That is a
gap in the schema, not a tuning problem, and it is the next thing this case
argues for.

The neighbourhood model is also thinner here than "20 patches with gaps"
suggests, and worth knowing about when the solve does converge. At the
configured `mesh_size` the bore meshes to 174 nodes — about 2 elements across —
the 20 wall balls catch 21 distinct nodes between them, and the inlet ball
catches exactly **one**. One of the 20 wall ports reaches no material and is
correctly reported as a finding.

Two errors would still run in opposite directions once it solves — gaps leave
the fluid unconstrained and read fast, while each ball reaches `port_radius`
inward from the wall and holds interior fluid still, which reads slow — so there
is no honest prediction of direction even then. **Treat a close match as
suspicious rather than as validation.**

Note also that this file's `Δp` is derived from the true bore area, while the
implementation spreads a port's force over the disc of its search radius. Those
are different numbers by construction (2.78× here), and the implementation's
choice is the documented one: a coordinate frame implies no area but that of its
own neighbourhood.

## Running them

```shell
# whatever the user configuration names
pc cae fea :cantilever
pc cae cfd :pipe

# a particular implementation, this run only (outranks the part's own)
pc cae fea -i calculix:fea :cantilever

# both, as a check that fails on any finding
pc test -f fea
pc test -f cfd

# where the boundary conditions actually landed, which is the first thing
# to look at when a number is wrong
pc render -t svg --with-ports cantilever
pc render -t svg --with-ports pipe
```

The measurements land in the log, as a warning naming the peak stress and the
peak displacement. `--json` prints the **findings** — the things the
implementation wants you to act on — so a clean run prints `[]` rather than the
numbers:

```shell
pc --no-ansi cae fea --json :cantilever   # [] when the part is fine
```

The model itself is written beside the package as `cantilever.fea.glb` and
`pipe.cfd.glb`, and the PartCAD Viewer's FEA and CFD tabs show the same thing
with the findings under it.

### Two things that will waste your time

**The solver runs in the daemon's environment, not your shell's.** With a daemon
already running, `PARTCAD_CCX=... pc cae fea :cantilever` is silently ignored and
the analysis uses whatever `ccx` the daemon can see. `pc daemon stop` first. The
same applies to anything else you set in the environment to steer a run.

**`pc test` caches its verdicts.** A second `pc test -f fea` returns the previous
answer in hundredths of a second without going near a solver, which is the point
of the cache and is confusing when you are trying to observe a change in
behaviour. The cache key covers the boundary conditions, the implementation and
its options — but not, for instance, whether `ccx` is on `PATH` this time.
