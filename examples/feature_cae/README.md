# Engineering analysis with a known answer

PartCAD ships no solver. `pc cae fea`, `pc cae dynamic`, `pc cae thermal` and
`pc cae cfd` run whatever implementation the part or the user configuration
names, and are only ever as right as that implementation is. These two parts are
how you find out which.

Each analysis of them is a textbook case whose answer is a formula, so what the
solver returns can be compared against arithmetic instead of against
expectations. That is the whole point: a unit test can show the code does what
its author meant, and cannot show that what the author meant is what the solver
expects.

It has earned itself already. The first run of these cases against a real
CalculiX found four defects stacked in front of the solver, one of which
answered `0.0000 mm` rather than failing — an answer a reader could have
believed. The next found that CalculiX's own CFD solver cannot answer the pipe at
all, and that a port that is only a coordinate frame makes every implementation
guess at the surface it stands for. Ports drawn with sketches, and five more
implementations, came out of that.

```shell
pc cae fea :cantilever       # does it hold up                  section 1
pc cae dynamic :cantilever   # at which frequencies does it ring section 2
pc cae thermal :cantilever   # how hot does it get              section 3
pc cae cfd :pipe             # how does oil flow through it     section 4
```

| analysis | the part names | also implemented by |
| --- | --- | --- |
| `fea` | [`calculix`](https://github.com/partcad/partcad-cae-calculix) | [`elmer`](https://github.com/partcad/partcad-cae-elmer), [`code_aster`](https://github.com/partcad/partcad-cae-code-aster), [`moose`](https://github.com/partcad/partcad-cae-moose) |
| `dynamic` | [`elmer`](https://github.com/partcad/partcad-cae-elmer) | `code_aster`, `moose` |
| `thermal` | [`elmer`](https://github.com/partcad/partcad-cae-elmer) | `code_aster`, `moose` |
| `cfd` | [`openfoam`](https://github.com/partcad/partcad-cae-openfoam) | `elmer`, `moose`, [`code_saturne`](https://github.com/partcad/partcad-cae-code-saturne) |

Any of them answers for one run with `-i`: `pc cae fea -i //pub/feature/cae/elmer:fea :cantilever`.

What an analysis needs is a **container runtime**, or the solver installed on
this machine. Every implementation names an image carrying its solver and
mesher, so with a container runtime there is nothing to install; without one,
PartCAD runs it in an ordinary sandbox and it finds a solver installed here (each
package's README says where it looks). On a machine with no container runtime
`pc test` **skips** a part whose implementation names an image rather than
failing it: a container is the only way PartCAD has of supplying what pip cannot
install, so on such a machine the question was never really put. The skip is a
`WARNING` carrying the whole report. Where a container runtime *is* running,
everything that stops the analysis is the implementation failing and fails the
part, including an image that cannot be pulled.

> **Not on 64-bit ARM Linux yet.** The cantilever carries `unless: [aarch64]`,
> so on such a machine the part is not declared at all. gmsh publishes no wheel
> for that platform and no source distribution, so an implementation cannot be
> installed in a Python sandbox there — and the images that carry it, built for
> arm64 where the solver allows, are not published yet. The line comes out when
> they are.

## Where a condition lands

A port is a coordinate frame, and a frame is a point: it can say where a bolt
goes and not which surface it clamps. A port whose interface draws it with a
**sketch** can — the sketch, placed by the port's frame with Z out of the
surface, *is* the surface. PartCAD imprints each port's sketch on the part before
the implementation runs and hands it the faces each port covers; a force or a
power is spread over exactly their area.

The pipe's ends are drawn with the bore's own cross-section, a `basic` circle of
its 5 mm radius:

```yaml
sketches:
  bore:
    type: basic
    circle: 5

interfaces:
  pipe-inlet:
    ports:
      inlet:
        sketch: bore
```

<a href="./pipe.ports.svg"><img src="./pipe.ports.svg" alt="The pipe with its two ports, each drawn with the bore's circle" style="max-height: 360px;"></a>

That drawing is `pc render pipe` — the `svg-with-ports` file type the part
declares, with its ports and interfaces drawn. Each port is its frame, with Z out
of the end face, and its circle lies exactly on that face.

A port with no sketch covers the face it lies on. The cantilever's ports sit in
the middle of its end faces, so `fix: [beam-root]` clamps the whole 10 × 10 mm
root face and `load: {beam-tip: 100 N}` spreads 100 N over the whole tip face —
with no sketch to declare, because there is nothing to choose.

## 1. Static stress — `cantilever`, `fea:`

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

### What each implementation reads

| implementation | tip deflection | peak von Mises | how the clamp is applied |
| --- | --- | --- | --- |
| Elmer | **0.2005 mm** | 60.43 MPa | the root face |
| Code_Aster | **0.2005 mm** | 60.62 MPa | the root face |
| MOOSE | **0.2005 mm** | 59.33 MPa | the root face |
| CalculiX | 0.1655 mm | 58.28 MPa | every node within 7.5 mm of the port |

The same quadratic mesh (2,370 tetrahedra at `mesh_size: 0.03`), the same
material. The three that clamp the face agree with each other to every printed
digit and land 0.5 % under the Timoshenko figure, which is a clamp that also
stops the root face's Poisson contraction: a slightly stiffer beam than the
textbook's, as a real clamp is.

CalculiX reads 17.9 % low, and that is the model rather than the solver. Its
implementation turns a port into "every mesh node within `port_radius` of this
point" — here a 7.5 mm ball, the smallest that covers the whole end face (whose
half-diagonal is 7.07 mm) — and the ball clamps part of the bar's *length* along
with it. Measured from the mesh, the clamp reaches 6.8 mm in from each end,
leaving a free span of 86.4 mm; and deflection goes as the cube of the span. It is
mesh-converged (0.1650, 0.1655 and 0.1631 mm across a 15× range of element
counts), so it is a property of the neighbourhood model. Getting within a few
percent needs `fix:` to clamp a face — which is what the faces each port now
carries are for.

**Peak stress is not the number to compare.** It sits wherever the constraint
bites, and a clamp is a stress concentration. 60 MPa is what the *bending* is;
the implementations report 58–61 MPa, and one reporting rather more at the clamp
would not be wrong.

Readings that would mean something else:

| reading | likely cause |
| --- | --- |
| exactly 0.0000 mm | the clamp is holding the loaded end too |
| off by ~1000× | millimetres against metres somewhere in the input |
| ~2× low | only half the load applied, or the load spread over both end faces |
| ~0.0006 mm too much | `self_weight` crept back on |
| a finding that the port covers no surface | the port's frame is not on a face — `pc render -t svg --with-ports cantilever` |

## 2. Natural frequencies — `cantilever`, `dynamic:`

The same bar, clamped at the root and left to ring. `dynamic:` takes `fix:` alone:
a natural frequency is a property of the part and how it is held, not of what it
carries.

For a clamped–free beam the n-th bending frequency is
`fₙ = (βₙL)² / (2πL²) · √(EI/ρA)`, with `β₁L = 1.8751` and `β₂L = 4.6941`:

- **First bending** = **815.4 Hz**
- **Second bending** = **5110 Hz**

and the first torsional mode of a square shaft, `f = (1/4L) √(GJ/ρIₚ)` with
`J = 0.1406 a⁴` and `Iₚ = a⁴/6`, is **7188 Hz**. The section is square, so every
bending mode comes twice — once in each plane, at the same frequency.

### What each implementation reads

| implementation | first pair | second pair | first torsion |
| --- | --- | --- | --- |
| Elmer | 813.25, 813.27 Hz | 4877.7, 4877.8 Hz | 7226.1 Hz |
| Code_Aster | 813.25, 813.27 Hz | 4877.7, 4877.8 Hz | 7226.1 Hz |
| MOOSE | 813.25, 813.27 Hz | 4877.7, 4877.8 Hz | 7226.1 Hz |

Three solvers, three eigensolvers, the same digits. The first pair is 0.26 %
under Euler–Bernoulli, which is the shear deformation and rotary inertia a solid
model has and a beam formula leaves out; both matter more the shorter the
wavelength, which is why the second pair is 4.5 % under. Torsion is 0.5 % over
the closed form, whose `J` is itself an approximation for a square.

With `min_frequency` set in a package's `cae: dynamic:` section, a first
frequency under it is a finding: the part would ring with whatever drives it
there.

## 3. Heat transfer — `cantilever`, `thermal:`

The same bar, its root held at 20 °C and 1 W put in through its tip face; every
other surface insulated. Steel conducts at `k` = 50 W/(m·K).

One-dimensional conduction: the temperature rises linearly from the root, by
`ΔT = PL/kA` = 1 × 0.1 / (50 × 1e-4) = **20 K** — so the tip reaches **40 °C**.

| implementation | coldest | hottest |
| --- | --- | --- |
| Elmer | 20 °C | **40 °C** |
| Code_Aster | 20 °C | **40 °C** |
| MOOSE | 20 °C | **40 °C** |

Exact, as it should be: quadratic elements represent a linear temperature field
without error, and the heat input is spread over exactly the tip face's area.
With `max_temperature` set in a package's `cae: thermal:` section, a part hotter
than that anywhere is a finding.

## 4. Pipe flow — `pipe`, `cfd:`

The **bore** of a 10 mm × 100 mm pipe (the fluid, not the tube), driven by 5 mN
at the inlet and leaving at the outlet; every other surface is the wall, held
no-slip.

| | |
| --- | --- |
| Diameter `d` | 0.010 m |
| Length `L` | 0.100 m |
| Density `ρ` | 900 kg/m³ |
| Dynamic viscosity `μ` | 0.1 Pa·s |
| Inlet force `F` | 0.005 N |

`Δp = F/A` = 63.66 Pa over the bore area `A` = 7.854e-5 m² — and since the inlet
is drawn with the bore's circle, the area the force is spread over *is* the bore
area. Hagen–Poiseuille gives

- **Mean velocity** `u_mean = d²Δp/32μL = F/8πμL` = **0.01989 m/s**
  (the radius cancels)
- **Centreline velocity** `u_max = 2u_mean` = **0.03979 m/s**
- **Flow rate** `Q = u_mean·A` = **1.5625 mL/s**
- Profile `u(r) = u_max(1 − r²/R²)` — a paraboloid

The regime is checked, not assumed: `Re = ρu_mean·d/μ` = **1.79**, far below the
2300 where laminar flow ends, and the entrance length `0.06·Re·d` = 1.07 mm is
**1.1 % of the pipe**, so the flow is fully developed over essentially all of it.

### What each implementation reads

| implementation | flow rate | peak speed | Reynolds number |
| --- | --- | --- | --- |
| OpenFOAM | **1.556 mL/s** (−0.4 %) | 0.03977 m/s | 1.78 |
| Elmer | **1.551 mL/s** (−0.7 %) | 0.04004 m/s | 1.78 |
| MOOSE | **1.544 mL/s** (−1.2 %) | 0.04002 m/s | 1.77 |
| code_saturne | **1.572 mL/s** (+0.6 %) | 0.03991 m/s | 1.80 |
| CalculiX | does not converge | | |

All at `mesh_size: 0.008`, about six cells across the radius. OpenFOAM solves on
the dual polyhedra of gmsh's tetrahedra; on the raw tetrahedra its cell-centred
scheme reads 13 % low, which is why its implementation converts them. Elmer and
MOOSE are finite elements, stabilized, on the tetrahedra themselves.
code_saturne is the one reading high, and by design: an inflow at a pressure is
posed in it as a reservoir, whose pressure is the inlet's *total* pressure where
the others hold its static one, so it is driven by the 0.18 Pa of dynamic
pressure more. The peak speeds are a cell or a node's value, so within a few
tenths of a percent of the centreline is the most they can say.

CalculiX's `*CFD` solver diverges on this problem — and on a deck built by hand
for it, driven by pressure or by velocity, at every mesh tried: it demands a gas
constant even for an incompressible flow and derives an acoustic time step from
it, which collapses within one iteration. That is a property of the solver as
driven here, and why the pipe names OpenFOAM.

## Running them

```shell
# the implementation the part names
pc cae fea :cantilever
pc cae dynamic :cantilever
pc cae thermal :cantilever
pc cae cfd :pipe

# a particular implementation, this run only (outranks the part's own)
pc cae fea -i //pub/feature/cae/elmer:fea :cantilever
pc cae cfd -i //pub/feature/cae/moose:cfd :pipe

# all of them as checks that fail on any finding
pc test

# where the boundary conditions actually landed, which is the first thing
# to look at when a number is wrong
pc render -t svg --with-ports cantilever
pc render pipe
```

The measurements land in the log, as a warning naming what was measured.
`--json` prints the **findings** — the things the implementation wants you to
act on — so a clean run prints `[]` rather than the numbers:

```shell
pc --no-ansi cae fea --json :cantilever   # [] when the part is fine
```

The model itself is written beside the package as `cantilever.fea.glb`,
`cantilever.dynamic.glb`, `cantilever.thermal.glb` and `pipe.cfd.glb`, and the
Digital Thread's FEA, Dynamic FEA, Heat Transfer and CFD tabs show the same thing
with the findings under it.

### Two things that will waste your time

**The solver runs in the daemon's environment, not your shell's.** With a daemon
already running, `PARTCAD_ELMER_BIN=... pc cae dynamic :cantilever` is silently
ignored and the analysis uses whatever Elmer the daemon can see. `pc daemon stop`
first. The same applies to anything else you set in the environment to steer a
run.

**`pc test` caches its verdicts.** A second `pc test -f fea` returns the previous
answer in hundredths of a second without going near a solver, which is the point
of the cache and is confusing when you are trying to observe a change in
behaviour. The cache key covers the boundary conditions, the implementation and
its options — but not, for instance, whether a solver is on `PATH` this time.
