# qual-lockwire

A PartCAD **qualification plugin** for [Lockwire](https://lockwirerobotics.com/)
([source](https://github.com/Shivansh2703/lockwire)), Lockwire Robotics' preflight
checker for robot designs. Lockwire pins every part's power, weight, bus and torque
figures in one lockfile, with a source and a witness for each, and says when they do
not add up. This package hands that check to PartCAD as a qualification test of the
`other` subtype.

## Using it

Import this package, then declare the test on the object the lockfile is about:

```yaml
dependencies:
  lockwire:
    type: git
    url: https://github.com/<owner>/partcad-qual-lockwire.git   # once it has a repository of its own

assemblies:
  rover:
    type: assy
    qual:
      other:
        budgets:
          path: lockwire:lockwire        # this package's 'qual: lockwire:'
          lockfile: rover.lockwire.yaml  # relative to the rover's package
          strict: true                   # 'GO with notes' fails, as 'lockwire check --strict' does
```

or have PartCAD write the declaration:

```sh
pc qual add --other --path lockwire:lockwire --set lockfile=rover.lockwire.yaml rover budgets
```

Then:

```sh
pc --no-ansi qual test --other rover
```

runs Lockwire's checks in a PartCAD sandbox (with `lockwire` installed from PyPI;
it needs Python 3.12) and reports the verdict: **GO** passes, **GO with notes**
passes unless `strict: true`, **NO-GO** and a refused lockfile fail, and **NOT
SCORED** -- nothing could be compared -- is a skip. Every violation is an error,
every warning a warning, in the sentence `lockwire check` prints. In the IDE, the
**Qualification → Other** tab lists the test with the full report as a table.

Lockwire reads its lockfile and nothing PartCAD hashes, so the verdict is never
cached: every run asks Lockwire again.

## What is here

| File | What it is |
|------|------------|
| `partcad.yaml` | The package, and its `qual: lockwire:` declaration: the script, the subtype, the sandbox's requirements, and the two parameters (`lockfile`, `strict`) with their defaults |
| `lockwire_qual.py` | The plugin: `lockwire.api.check()` over the lockfile, turned into what PartCAD reads of a qualification test |
| `example/` | An object that declares the test (`pc qual test --other -P //example`, run from this directory; make its lockfile with `lockwire start --example rover` first) |

## Moving it to a repository of its own

Nothing here refers to the PartCAD repository it ships in: copy this directory to the
root of a new repository and import it by URL as above. The protocol it implements is
PartCAD's `wrappers/wrapper_qual.py`; the declaration is documented in "Qualification
plugins" of the PartCAD documentation's Qualification chapter.
