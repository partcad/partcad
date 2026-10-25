---
name: validate
description: Validate a PartCAD part, assembly, scene or sketch against the requirements its `requirements:` section declares - run `pc test` for the ports, interfaces and physics PartCAD measures, run every simulation and every engineering analysis scenario, render it from every angle that matters with its ports and interfaces drawn, read the bill of materials and the assembly instructions of an assembly, and reason about whether each feature is met. Use for /pc:validate, when the user asks whether a design meets its requirements, or when the IDE's Requirements tab points here ("Validate using /pc-validate").
---

# pc:validate

Decide whether an object is what it was required to be. `$ARGUMENTS` names the
object (a part by default; an assembly, a scene or a sketch when the user says
so, or when the package declares it as one).

An object's `requirements:` has two halves, and they are validated two ways:

- **What PartCAD measures** — `ports:`, `interfaces:` and `physics:`. These are
  checked by `pc test` (its `requirements` check), and its verdict is the
  verdict. You report it; you do not second-guess it.
- **`features:`** — a name and a sentence each: "takes an M3 screw from either
  side", "does not tip over on a 10° slope". Some are demonstrated by a
  simulation that names them (`feature:` on a `simulate:` entry), or by an
  engineering analysis scenario that does (`feature:` on a scenario of a part's
  `fea:`, `dynamic:`, `thermal:` or `cfd:`). Every one of them is for *you* to
  judge, from evidence you gathered and can point at.

The verdict on a feature is never a guess. If nothing you gathered shows it,
the verdict is "cannot tell" and you say what evidence would settle it — not
"met".

Pass `--no-ansi` on every run (it is global and goes before the subcommand): the
output is then plain text, logged to stderr, so capture both streams (`2>&1`).
Make sure PartCAD is available as `/pc:init` describes.

## 1. Read what is required

Find the object in `partcad.yaml` and read its `requirements:`, its
`simulate:` section and, for a part, its analysis sections (`fea:`, `dynamic:`,
`thermal:`, `cfd:`). `pc --no-ansi info <object>` (whatever kind of object it
is) prints the declaration too, through whatever an alias or an enrich points
at.

```yaml
requirements:
  features:
    <name>: <what it has to have or do>
  ports:
    <port>: [<position>, <direction>, <angle>]   # any part null: no requirement
  interfaces:
    <interface>: null                            # implemented, anywhere
  physics:
    mass: "<0.5"                                 # kg
simulate:
  <simulation>:
    feature: <name>                              # this simulation demonstrates that feature
    ...
fea:                                             # and dynamic:, thermal:, cfd:
  <scenario>:
    feature: <name>                              # this analysis scenario demonstrates that feature
    ...
```

A paragraph, a list, or headings mapped to paragraphs under `requirements:` are
the older free-form spelling, and are features too.

If the object declares no requirements at all, say so and stop: there is nothing
to validate against. Offer to write them down — `/pc:gen-part` and
`/pc:gen-assembly` say how — rather than inventing what the object was for.

Make a list: every feature, and every port, interface and physical property
required. Each gets a verdict in §6.

## 2. Run `pc test`

```sh
pc --no-ansi test <object> 2>&1                     # whatever kind of object it is
pc --no-ansi -v test -f requirements <object> 2>&1  # every requirement, met or not
```

The first is the whole suite: whether the object builds, and everything else
PartCAD asks of it. Every check, what it asks and what to do when it fails, is
listed in PartCAD's documentation (Digital Thread → Validation → Testing), and
the IDE's Validation → Test tab shows the same verdicts check by check. A failure there that is not a requirement still matters to
the features — a part that is a surface rather than a solid (`shell`) is not
going to "carry a load", whatever the renders look like.

The second lists each port, interface and physical property: a met one at
`DEBUG` (hence `-v`) and one that is not as `Test failed: ...: requirements:
<section>: <name>: <required>: <found>`. A requirement on something PartCAD
cannot find out — a mass with no density to work it out from, an assembly one of
whose parts weighs nothing known — fails as "not known". Report it that way; it is not met as
far as anybody can show.

## 3. Run the simulations

Run `pc sim` as well as `pc test`, every time, even though `pc test` already ran
the same simulations as its `sim` check: that check gives a verdict, and this
gives what happened.

```sh
pc --no-ansi sim <object> --json 2>&1               # a part, an assembly or a scene
```

`simulate:` is declared by a part, an assembly or a scene, and `pc sim` takes all
three. A sketch has nothing to simulate.

Every `simulate:` entry runs and its `validation:` is evaluated. A simulation
that names a feature is evidence for that feature, and `--json` gives what
happened (`before`, `after`) as well as the verdict — read it, because a
validation can pass for the wrong reason. A run that could not be made (no
simulator imported, no container runtime) is not evidence either way: say so.

A `simulate:` entry naming a feature the requirements do not declare is a
mistake `pc test` already reported; mention it.

For a part, run the scenarios of every analysis it declares the same way, for
the same reason -- `pc test`'s `fea`, `dynamic`, `thermal` and `cfd` checks give
the verdict, and this gives what each scenario found:

```sh
pc --no-ansi cae fea <part> --json 2>&1             # every scenario; -f <scenario> for one
```

A scenario that names a feature is evidence for it: no findings says the
implementation saw nothing wrong under exactly those conditions, and the log
carries what it measured (a peak stress, a first frequency, a temperature) --
read that against the feature's sentence, since "holds 2 kg" is only shown by a
scenario that loads it with 2 kg. One that could not run is not evidence either
way: say so.

## 4. Look at it

Render from every angle a feature needs, with the ports and interfaces drawn —
a requirement about where something connects is checked by seeing it:

```sh
for view in front back left right top bottom iso; do
  mkdir -p /tmp/pc-validate/$view                   # -O expects it to exist
  pc --no-ansi render -t png --view $view --with-all -O /tmp/pc-validate/$view <object>
done
```

(`-a` before `-t` for an assembly, `-S` for a scene, `-s` for a sketch.) View
every picture. Then look specifically
at what the features talk about: a feature about a face is checked from the view
that faces it, and a feature about a hole from along its axis
(`--viewport-origin X,Y,Z --viewport-up X,Y,Z`, see `/pc:render`). For an
assembly, `--with-internals` draws the ports of what is inside, which is how a
connection that came out wrong is found. Numbers are read off `pc info` (the
measured bounding box and volume) or a dimensioned drawing (`/pc:describe`),
never estimated from pixels.

## 5. For an assembly: how it is bought and how it is put together

```sh
pc --no-ansi bom <assembly> 2>&1
mkdir -p /tmp/pc-validate/instructions
pc --no-ansi instructions -t html --ignore-manufacturability -O /tmp/pc-validate/instructions <assembly> 2>&1
```

Read the bill of materials — what is in it, how many of each, what is bought and
from whom — and the instructions, step by step. Features about the product as
a whole ("uses only M3 fasteners", "assembled without glue", "fewer than ten
parts") are answered here rather than in a picture.

## 6. Judge, and report

One line per requirement:

| Requirement | Verdict | Evidence |
| --- | --- | --- |
| port `top` faces down | met | `pc test -f requirements` |
| `mass` < 0.5 kg | not met | 0.62 kg, worked out from the volume and PLA |
| feature `stands` | met | simulation `upright` validated; `after` shows a tilt of 0.3° |
| feature `m3-either-side` | met | top and bottom views show both counterbores |
| feature `survives-drop` | cannot tell | no simulation names it; needs an impact analysis |

- The measured requirements take `pc test`'s verdict, unchanged.
- A feature is **met** only when something you gathered shows it — a
  simulation that validated, a view in which it is visible, a line of the bill of
  materials, a step of the instructions — and the evidence column names which.
- **Not met** says what is wrong and where it shows.
- **Cannot tell** says what would settle it: a view, a simulation with a
  `feature:` naming it, an analysis.

End with the count (met, not met, cannot tell) and, for each requirement not
met, what in the design would have to change. Change nothing unless asked: this
skill reports. The same marks are on the IDE's Requirements tab, where the
"LLM" banner on every feature points here.
