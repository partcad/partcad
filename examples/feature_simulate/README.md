# //pub/examples/partcad/feature_simulate

PartCAD example project which demonstrates simulating a part or an assembly.

## Usage
A part says what it *is*. `simulate:` is where it says what it is supposed
to **do** -- or, as here, what it is supposed not to do:

```shell
pc sim -a stable      # the stack stands; the validation passes
pc sim -a unstable    # the top block falls off; that validation passes too
pc sim                # every simulation this package declares
```

`stable` and `unstable` are the same two blocks. In `stable` the upper one
sits squarely on the lower one; in `unstable` it is pushed 18 mm out of 20
off the edge, so its centre of mass is past the corner it rests on. Nothing
static distinguishes them -- both render, export and list the same way --
and neither does anything PartCAD can check by looking. What separates them
is what happens when the world is switched on.

Each `simulate:` states five things: the `scene:` the object is placed in
(here the default, `//builtin/scene:subject`, an empty world holding the
subject and nothing else), the `offset:` that puts it there -- the blocks
are drawn about their own centres, so the stack is lifted 10 mm to stand its
bottom face on the floor -- the `simulation:` plugin that runs it, the
`validation:` expression that says whether what happened is what was
supposed to happen, and a `desc:` for whoever reads the result.

### The simulator is somebody else's package

PartCAD implements no simulator. It ships the *concept* -- the `simulate:`
section, the `simulation:` section a plugin is declared in, the sandbox the
plugin runs in, and the MJCF export a scene reaches it through -- and a
package supplies the physics. This one imports
[partcad-sim-mujoco](https://github.com/partcad/partcad-sim-mujoco) below and
names it as `sim-mujoco:mujoco`. Nothing has to be installed by hand: PartCAD
installs that package's requirements into the sandbox it runs it in, so a
machine with no MuJoCo on it simulates just the same.

### `slippery` is `stable` in another material

`slippery.assy` is `stable.assy` with one word changed: the blocks are PTFE
instead of aluminium. Same geometry, same locations, same scene, same
simulation -- and the top block ends up on the floor.

```shell
pc sim -a stable      # nothing moves
pc sim -a slippery    # the top block slides off
```

That is not a quirk of the simulator; it is what the two materials are.
Aluminium on aluminium grips (`mu: 1.05` -- dry aluminium galls, which is why
the number is above one), PTFE on PTFE does not (`mu: 0.04`), and somewhere
between 0.4 and 0.5 a squarely stacked pair of these blocks stops standing
up. So "will this stack stand?" is a question about the material, and
`materials:` below is where the answer is written down. Every part that names
one gets its `mu` written into the simulation, in the same place SDFormat
calls `<mu>` and URDF calls `<mu1>`.

Without it the simulation would answer with **MuJoCo's** default friction of
1.0 -- a plausible number for metal, a badly wrong one for PTFE, and in
either case a number nobody chose.

### Looking at what happened

`--json` prints everything the plugin reported, which for MuJoCo is where
every body was before and after:

```shell
pc sim --json -a slippery
```

The scene reaches the simulator as the MJCF PartCAD writes. That is an
ordinary export, so the same file can be written out and looked at -- or
opened in MuJoCo:

```shell
pc export -a -t mjcf -O ./ unstable
pc open --with mujoco ./unstable.xml
```


## Sub-Packages

### [sim-mujoco](https://github.com/partcad/partcad-sim-mujoco.git)

## Assemblies

### slippery
<table><tr>
<td valign=top><a href="slippery.assy"><img src="././slippery.svg" alt="slippery" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The stable stack again, in PTFE, which does not stay stacked</td>
</tr></table>

### stable
<table><tr>
<td valign=top><a href="stable.assy"><img src="././stable.svg" alt="stable" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Two aluminium blocks, the upper one squarely on top of the lower one</td>
</tr></table>

### unstable
<table><tr>
<td valign=top><a href="unstable.assy"><img src="././unstable.svg" alt="unstable" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The same two blocks, with the upper one 18 mm out of 20 off the edge</td>
</tr></table>

## Parts

### block
<table><tr>
<td valign=top><a href="block.py"><img src="././block.svg" alt="block" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A 20 mm cube of aluminium, centred on its own origin</td>
<td valign=top>Parameters:<br/><ul>
<li>material: :aluminium</li>
</ul>
</td>
</tr></table>

### block_ptfe
<table><tr>
<td valign=top><a href="block.py"><img src="././block_ptfe.svg" alt="block_ptfe" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The same 20 mm cube, in PTFE</td>
<td valign=top>Parameters:<br/><ul>
<li>material: :ptfe</li>
</ul>
</td>
</tr></table>

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
