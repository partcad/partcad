# Engineering analysis with a known answer

PartCAD ships no solver. `pc cae fea` and `pc cae cfd` run whatever
`caeFeaImplementation` / `caeCfdImplementation` name, and are only ever as right
as that implementation is. These two parts are how you find out which.

Each is a textbook case whose answer is a formula, so what the solver returns can
be compared against arithmetic instead of against expectations. That is the whole
point: a unit test can show the code does what its author meant, and cannot show
that what the author meant is what the solver expects.

```shell
pc cae fea :cantilever
pc cae cfd :pipe
```

Both need a solver installed. For the default implementation
([`partcad-cae-calculix`](https://github.com/partcad/partcad-cae-calculix)) that
means `ccx` on `PATH` — `apt install calculix-ccx`, `brew install calculix-ccx`,
or `conda install -c conda-forge calculix`. Without one the analysis does not
run, and `pc test` says so and moves on rather than failing the part.

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
model should land at **0.2016 mm**, +0.8 %. The bar is slender enough (`L/h` = 10)
that this is the only correction worth carrying.

### What to expect, and what it means

**Deflection is the number to compare.** Peak stress is not: the reported peak
sits wherever the constraint bites, and an artificial constraint makes an
artificial stress concentration. 60 MPa is what the *bending* is; a solver
reporting rather more at the clamp is not necessarily wrong.

Do not expect 0.2016 mm. `fix:` names a port, a port is a coordinate frame, and
the implementation turns it into "every mesh node within `port_radius` of this
point". Here that is a 7.5 mm ball at the root — the smallest that covers the
whole 10 × 10 end face, whose half-diagonal is 7.07 mm — and it clamps 7.5 mm of
the bar's *length* along with it. The load ball does the same at the tip. Between
them the beam is effectively shorter than 100 mm, and deflection goes as the cube
of the span:

| effective span | expected `δ` |
| --- | --- |
| 100 mm (ideal) | 0.2016 mm |
| 96 mm | 0.177 mm |
| 92 mm | 0.156 mm |

So **0.16–0.18 mm is the honest expectation**, and reading low by 10–20 % is the
neighbourhood model rather than the solver. Which is the finding worth having:
getting inside a few percent needs `fix:` to clamp a *face*, not a ball. That is
the concrete improvement this case argues for.

Readings that mean something else:

| reading | likely cause |
| --- | --- |
| ~0.2 mm | the model is better than expected — check the clamp really is a ball |
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

`Δp = F/A` = 63.66 Pa over `A` = 7.854e-5 m², and Hagen–Poiseuille gives

- **Mean velocity** `u_mean = d²Δp/32μL = F/8πμL` = **0.01989 m/s**
  (the radius cancels)
- **Centreline velocity** `u_max = 2u_mean` = **0.03979 m/s**
- **Flow rate** `Q = u_mean·A` = **1.5625 mL/s**
- Profile `u(r) = u_max(1 − r²/R²)` — a paraboloid

The regime is checked, not assumed: `Re = ρu_mean·d/μ` = **1.79**, far below the
2300 where laminar flow ends, and the entrance length `0.06·Re·d` = 1.07 mm is
**1.1 % of the pipe**, so the flow is fully developed over essentially all of it.

### This one is expected to disagree, and that is the point

`fix:` cannot currently say "the lateral surface". It names ports, and ports
become balls, so the no-slip wall here is 20 patches — four azimuths at five
stations — with gaps between them. Covering a 100 mm bore properly at a radius
that stays clear of the axis would take on the order of a hundred ports, which is
its own argument that the model is wrong for this.

Two errors run in opposite directions and neither is small:

- the **gaps** leave the fluid unconstrained between patches, which under-drags
  it and reads **fast**;
- each ball reaches `port_radius` (3 mm here) *inward* from a 5 mm wall, holding
  interior fluid still that should be moving, which reads **slow**.

So there is no honest prediction of the direction, and the magnitude is likely to
be large. **Treat a close match as suspicious rather than as validation.** What
this case is for is measuring the gap and giving the fix a target: a `fix:` that
names a surface would make 0.03979 m/s an achievable number, and until then this
is the case that says by how much it is missed.

## Running them

```shell
# whatever the user configuration names
pc cae fea :cantilever
pc cae cfd :pipe

# a particular implementation, this run only
pc cae fea -i //pub/feature/cae/calculix:fea :cantilever

# the findings as JSON, for a script to compare
pc --no-ansi cae fea --json :cantilever

# both, as a check that fails on any finding
pc test -f fea
pc test -f cfd

# where the boundary conditions actually landed, which is the first thing
# to look at when a number is wrong
pc render -t svg --with-ports cantilever
pc render -t svg --with-ports pipe
```

The model itself is written beside the package as `cantilever.fea.glb` and
`pipe.cfd.glb`, and the PartCAD Viewer's FEA and CFD tabs show the same thing
with the findings under it.
