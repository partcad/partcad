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
```

**One of the two is a live check.** The cantilever declares `fea:` and is
analysed; the pipe is here with its ports and its arithmetic but declares no
`cfd:`, because CalculiX's CFD solver diverges on it. Section 2 is that
measurement, and the declaration to paste back in once a solver converges is in
`partcad.yaml` beside the part.

What the analysis needs is a **container runtime**, and nothing else. The
default implementation declares an image that carries `ccx`, the mesher and
everything else it imports, so there is no solver to install and no platform
where the mesher cannot be had — including 64-bit ARM Linux, where it once could
not be. A machine with no container runtime runs no analysis, and that one
absence is what `pc test` passes over rather than failing the part; anything
else that stops the analysis is the implementation failing, and is reported as a
failure. See "What it needs" in
[`partcad-cae-calculix`](https://github.com/partcad/partcad-cae-calculix)'s
README.

> **A temporary arrangement, and why it is here.** `//pub/feature/cae/calculix`
> is registered on the public index's `devel` branch and has not reached `main`,
> which is what `examples/partcad.yaml` and every `pc init` project pin — so the
> default `caeFeaImplementation` resolves to nothing. Rather than repin the whole
> examples tree at the index's `devel`, which would drag in unrelated changes,
> this package depends on
> [`partcad-cae-calculix`](https://github.com/partcad/partcad-cae-calculix)
> directly and the cantilever names it (the block written out beside the pipe
> names it too, for whoever pastes it back):
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

### This one does not run, and here is exactly how far it gets

**There is no measurement to compare: the CFD solve does not converge.** Three
things were wrong with it, two of them since fixed, and the third is the one
that matters.

That third one is why the part above declares no `cfd:` section. A part that
declares one has asked the question, and `pc test` reads an analysis that cannot
answer as a failure — correctly. Shipping the declaration anyway would ship a
check that is red in every run of this repository and that nothing in this
repository can turn green, which is a check people learn to scroll past. The
four lines are written out in `partcad.yaml` beside the part instead, so that
restoring them is a paste rather than a reconstruction. Everything below was
measured with them in place.

**1. No outlet — fixed.** An incompressible flow is posed by *differences* in
pressure, and `cfd:` could name only walls (`fix:`) and an inlet (`load:`). With
nothing saying where the flow goes, the problem has no downstream reference and
CalculiX answers with a field that never moves: peak speed of order 1e-16 m/s
against an expected 0.03979 m/s, and a "pressure drop" that is just the
reference level. `cfd:` now takes an `outlet:` — the block in `partcad.yaml`
names one — and a `cfd:` without one is refused with a sentence saying why rather
than solved into a dead field.

**2. No temperature anywhere — fixed.** An isothermal run still solves the
energy equation, and that equation had no Dirichlet condition on it: the
temperature field drifted off its initial value over a few increments and the
run ended in

```
 *ERROR in initialcfd: absolute temperature is nearly zero; maybe absolute zero
        was wrongly defined or not defined at all (*PHYSICAL CONSTANTS card)
```

which reads as a mistake on a card that is in fact correct. The deck now holds
the walls and the inlet at the reference temperature.

**3. CalculiX's CFD solver diverges anyway — not fixed.** With both of those
right the run reaches the solver and ends in

```
 *ERROR in compdt; strongly decreasing time increment; the solution diverged
```

and it is not the port model that does it. A deck built by hand for this same
pipe — *true* end faces as the inlet and outlet, the *whole* lateral surface as
the no-slip wall, 808 nodes rather than 178 — diverges identically, driven by
pressure or by a prescribed inlet velocity, at reference pressures from 1 Pa to
1e5 Pa. The first time increment CalculiX computes for it is 8.1e-7 s, which is
an *acoustic* step for a flow moving at 0.02 m/s: `*CFD` demands
`*SPECIFIC GAS CONSTANT` even under `COMPRESSIBLE=NO` (leave it out and
`initialcfd` refuses the deck), and the step it derives from the resulting speed
of sound collapses to 6.7e-9 s within one iteration.

So this is a property of CalculiX's `*CFD` solver as driven here, not of the
mesh, the boundary model or the schema. Fixing it is solver work — a different
formulation, or a different solver — and until it is done, pasting the block back
in gets `pc cae cfd :pipe` as far as reporting that it did not converge, which is
the honest answer and not a useful check.

**The neighbourhood model is a separate problem, and it is also real.** At the
configured `mesh_size` the bore meshes to 178 nodes — about 2 elements across —
the 20 wall balls catch 23 distinct nodes between them, and the inlet and outlet
balls catch exactly **one node each**. A CFD boundary condition is a *surface*;
a PartCAD port is a coordinate frame, and a ball around one is not a face. Even
with a converging solver this part would need the implementation to find the
face a port lies on rather than the nodes near it.

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

# a particular implementation, this run only (outranks the part's own)
pc cae fea -i calculix:fea :cantilever

# as a check that fails on any finding
pc test -f fea

# where the boundary conditions actually landed, which is the first thing
# to look at when a number is wrong
pc render -t svg --with-ports cantilever
pc render -t svg --with-ports pipe
```

`pc cae cfd :pipe` and `pc test -f cfd` need the block from `partcad.yaml` pasted
back in first, and then report divergence — see section 2.

The measurements land in the log, as a warning naming the peak stress and the
peak displacement. `--json` prints the **findings** — the things the
implementation wants you to act on — so a clean run prints `[]` rather than the
numbers:

```shell
pc --no-ansi cae fea --json :cantilever   # [] when the part is fine
```

The model itself is written beside the package as `cantilever.fea.glb` — and as
`pipe.cfd.glb` for whoever restores the `cfd:` block — and the PartCAD Viewer's
FEA and CFD tabs show the same thing with the findings under it.

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
