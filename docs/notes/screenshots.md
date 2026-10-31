# Screenshots

How the screenshots under `docs/source/images/` are made, so that the next person to retake them does not have
to work it out again. Most of them are taken by a script, `dev-tools/screenshots/shoot.mjs`; one is taken by hand.

The pictures PartCAD *renders* - every image and drawing under `examples/` - are not screenshots and are not
covered here: they are what `cd examples && pc render -r` writes, and the root `AGENTS.md` says how they are kept
up to date.

## What is a screenshot, and of what

| File | What it shows | Used in | Taken by |
| --- | --- | --- | --- |
| `vscode1.png` | VS Code with the extension: the PartCAD side bar, `examples/wormgear.assy` from `//pub/robotics/parts/gobilda` in the editor, the assembly in the Digital Thread, PartCAD's log in the terminal | `README.md`, `docs/source/index.rst`, `ide/vscode/README.md` (the Marketplace page) | `shoot.mjs vscode1` |
| `vscode2.png` | The same for `feature_interface:connect-mates`, an assembly with parameters, which the Inspector lists | `ide/vscode/README.md` | `shoot.mjs vscode2` |
| `interface-m3.png` | The interface `m3`: a port drawn as its axes and its boundary sketch | `docs/source/config_interfaces.rst` | `shoot.mjs interface-m3` |
| `interface-orientation.png` | `example-motor` seen from above, its four NEMA-17 mounting ports each pointing its X axis at the next one | `docs/source/config_interfaces.rst` | `shoot.mjs interface-orientation` |
| `interface-orientation-2.png` | The same view with the motor faded out, so only the ports are left | `docs/source/config_interfaces.rst` | taken with the one above |
| `assy-autocompletion.png` | `- pa` typed in an ASSY file, and the completion offering the part selected in the Explorer | `docs/source/tutorial.rst` | `shoot.mjs assy-autocompletion` |
| `assy-autocompletion-done.png` | The link that completion inserts | `docs/source/tutorial.rst` | taken with the one above |
| `vs-code-behave.png` | VS Code's terminal running `behave` in the dev container | `docs/source/contributing.rst` | `shoot.mjs vs-code-behave` |
| `dt-requirements.png` | The **Requirements** tab: the measured requirements with their marks, and the features with what validates each. Of a package this script writes, not of one in the repository - see below | `docs/source/digital_thread/lifecycle/requirements.rst` | `shoot.mjs dt-requirements` |
| `dt-design.png` | The Digital Thread's **Design** group for `feature_interface:connect-mates`: the object and the tree of what it is made of | `docs/source/digital_thread/lifecycle/design.rst` | `shoot.mjs dt-design` |
| `dt-design-3d.png` | The same object's **3D** tab with the **view panel** out: the gizmo, the axis views, the sections and the viewpoint | `docs/source/digital_thread/lifecycle/design_3d.rst` | `shoot.mjs dt-design-3d` |
| `dt-design-2d.png` | Its **Design > 2D** tab: the object rendered to a picture, with the format chooser and **Save…** | `docs/source/digital_thread/lifecycle/design_2d.rst` | `shoot.mjs dt-design-2d` |
| `dt-design-draft.png` | Its **Design > Draft** tab for `feature_interface:example-bracket`: a dimensioned drawing, with **Drawn by** above it | `docs/source/digital_thread/lifecycle/design_draft.rst` | `shoot.mjs dt-design-draft` |
| `dt-analysis.png` | Its **Analysis > FEA** tab for `feature_cae:cantilever`, which declares `fea:` scenarios | `docs/source/digital_thread/lifecycle/analysis.rst`, `analysis_fea.rst` | `shoot.mjs dt-analysis` |
| `dt-analysis-dynamic.png` | Its **Analysis > Dynamic FEA** tab for the same part's `clamped` scenario | `docs/source/digital_thread/lifecycle/analysis_dynamic.rst` | `shoot.mjs dt-analysis-dynamic` |
| `dt-analysis-thermal.png` | Its **Analysis > Heat Transfer** tab for the same part's `tip-heated` scenario | `docs/source/digital_thread/lifecycle/analysis_thermal.rst` | `shoot.mjs dt-analysis-thermal` |
| `dt-analysis-cfd.png` | Its **Analysis > CFD** tab for `feature_cae:pipe`, whose part is the fluid volume | `docs/source/digital_thread/lifecycle/analysis_cfd.rst` | `shoot.mjs dt-analysis-cfd` |
| `dt-manufacturing.png` | Its **Manufacturing > Build vs Buy** tab for `provider_manufacturer:assembly` | `docs/source/digital_thread/lifecycle/manufacturing.rst`, `manufacturing_bvb.rst` | `shoot.mjs dt-manufacturing` |
| `dt-manufacturing-build.png` | Its **Manufacturing > Build** tab for `provider_manufacturer:assembly`, whose lines are made by its provider | `docs/source/digital_thread/lifecycle/manufacturing_build.rst` | `shoot.mjs dt-manufacturing-build` |
| `dt-manufacturing-buy.png` | Its **Manufacturing > Buy** tab for `provider_store:nut`, a part with a vendor and an SKU in a package that lists a supplier carrying it | `docs/source/digital_thread/lifecycle/manufacturing_buy.rst` | `shoot.mjs dt-manufacturing-buy` |
| `dt-manufacturing-bom.png` | Its **Manufacturing > Bill of Materials** tab for `feature_interface:connect-mates`: a bracket, a motor and six screws of two sizes | `docs/source/digital_thread/lifecycle/manufacturing_bom.rst` | `shoot.mjs dt-manufacturing-bom` |
| `dt-manufacturing-assembly.png` | Its **Manufacturing > Assembly** tab for `feature_interface:connect-mates`: the instruction book | `docs/source/digital_thread/lifecycle/manufacturing_assembly.rst` | `shoot.mjs dt-manufacturing-assembly` |
| `dt-validation.png` | Its **Validation > Test** tab for `feature_interface:example-bracket`: every check `pc test` runs, with its verdict | `docs/source/digital_thread/lifecycle/validation.rst`, `testing.rst` | `shoot.mjs dt-validation` |
| `dt-validation-simulation.png` | Its **Validation > Simulation** tab for `feature_simulate:stable`: the run, and the criteria it is judged by | `docs/source/digital_thread/lifecycle/simulation.rst` (twice: "In the UI" and "Examples") | `shoot.mjs dt-validation-simulation` |
| `sim-example-pendulum.png` | The same tab for `feature_simulate_joints:pendulum`, a mechanism held to its closed form | `docs/source/digital_thread/lifecycle/simulation.rst` | `shoot.mjs sim-example-pendulum` |
| `sim-example-arm.png` | The same tab for `feature_simulate_fea:arm`, the run an FEA scenario is written from | `docs/source/digital_thread/lifecycle/simulation.rst` | `shoot.mjs sim-example-arm` |
| `plugin-part-type.png` | `produce_part_wrapper:demo`, a part built by a `partTypes:` plugin | `docs/source/plugins/part_types.rst` | `shoot.mjs plugin-part-type` |
| `plugin-repository.png` | `plugin_repository_basic`'s `example:bolt`, a part served by a `repositories:` plugin rather than by a file | `docs/source/plugins/repositories.rst` | `shoot.mjs plugin-repository` |
| `docker-for-desktop.png` | Docker Desktop's "Containers" page, with a dev container running | `docs/source/contributing.rst` | by hand, see below |

`architecture.png` and `logo.png` are drawings, not screenshots.

## Taking them

Run it **on the host, with a desktop**: it opens VS Code windows on your screen, one per screenshot, and closes them
again. It has been run on Linux under Wayland. What it assumes of the host beyond that is little: `bash` for the
terminal's prompt and `which` to find `partcad-json-rpc`.

What it needs:

1. **The extension built from this checkout**: `npm run vsce-package` in `ide/vscode`, which writes
   `ide/vscode/partcad.vsix`.
2. **A VS Code to drive.** The newest one `npm test` in `ide/vscode` has downloaded into `ide/vscode/.vscode-test/`
   is used, or `PC_SCREENSHOT_CODE` names another binary. Not your own VS Code: see "Isolation" below.
3. **PartCAD from this checkout, on the host.** The repository's `.venv` belongs to the dev container and does not
   run on the host, so install the checkout into a virtual environment of its own. It is quick: PartCAD's core
   needs no CAD kernel, which lives in the sandboxes.

   ```bash
   python3 -m venv /tmp/pc-host && /tmp/pc-host/bin/pip install -e .
   ```

   Point the script at its `partcad-json-rpc` with `PC_SCREENSHOT_SERVICE`, or put it first on the `PATH`. Docker
   on the host is what the shapes are rendered in.
4. **The dev container running**, for `vs-code-behave` only: `npx --yes @devcontainers/cli up --workspace-folder .`.
5. **Network access**, for `vscode1`: its assembly comes from `//pub`.

Then:

```bash
cd dev-tools/screenshots
npm install
PC_SCREENSHOT_SERVICE=/tmp/pc-host/bin/partcad-json-rpc node shoot.mjs                  # all of them
PC_SCREENSHOT_SERVICE=/tmp/pc-host/bin/partcad-json-rpc node shoot.mjs vscode1 vscode2  # some
```

They are written straight into `docs/source/images/`; `PC_SCREENSHOT_OUT` writes them somewhere else, and
`PC_SCREENSHOT_WORK` (default: `partcad-screenshots` in the temporary directory) is where VS Code's profile and
extensions go. All of them together take about six minutes once PartCAD's caches are warm - longer on a first
run, which fetches `//pub` and provisions the sandboxes.
When one fails, the script leaves `failed.png` in the work directory: what the window looked like at the time.

Look at every picture before committing it. They are PNGs, so they go through Git LFS: commit from a machine that
has `git lfs install`ed (see the root `AGENTS.md`).

### What the script does, and why

The point is that a retake differs from the last take only in what changed in PartCAD.

* **Isolation.** Every screenshot gets a VS Code of its own, on a fresh profile created from a fixed set of
  settings, with the extension installed from the `.vsix`. Nothing your own VS Code has - its theme, its other
  extensions, a panel you resized - gets into a picture, and nothing one screenshot leaves open gets into the
  next one. It is a VS Code downloaded for testing, started with `--no-sandbox` because such a download has no
  setuid sandbox helper (the extension's own test runner does the same).
* **Its own Digital Thread port.** PartCAD sends what it shows to TCP port 9137 on the loopback interface, and
  only one window on a machine can have it - with your own VS Code open, it is usually yours, and what the
  script shows would appear there. So the script sets `PARTCAD_IDE_PORT=9238` for its VS Code, and stops the
  workspace's PartCAD daemon before starting it: the daemon is what sends the shows, and the one the extension
  starts then inherits the variable.
* **The same window every time**: VS Code's "Default Dark Modern" theme, no welcome page, no AI features, a 1792 x
  1064 window at twice the pixels (the size of the screenshots these replaced, which came from a Retina display),
  and a terminal running `bash` with a prompt of only the directory name - not the prompt of whoever took the
  picture, with their branch and their git status in it.
* **A still 3D view.** The Digital Thread turns the model on its own until its "Animate" box is cleared. So each
  object is shown, the box cleared, another object shown, and the object shown again: a show of a new object puts
  the camera back where every show starts it, which makes the framing the same on every run. The box is in the view
  panel, which starts folded away and stays so in every picture, so the script sets it (`stopTurning`) rather than
  clicking it: Playwright clicks nothing that is not on screen.
* **Waiting for the right thing.** A show is finished when the Digital Thread's tree names the object and the
  loading overlay is gone; the terminal is finished when behave's summary line is in it.
* **Tidy before the shutter**: notifications cleared, the pointer moved where it hovers nothing.

### Things that went wrong, and are handled

Each of these cost a run to find. They are handled in `vscode.mjs`, and listed here so that the handling is not
undone as unnecessary:

* A window in which nothing moves stops producing frames, and a DevTools screenshot waits for the next frame: the
  first capture works and every later one times out. The Digital Thread redraws constantly and hides this; the
  terminal-only `vs-code-behave` did not. The script redraws one near-transparent pixel in the corner on every frame.
* Chromium stops drawing a window it thinks is covered, which a window on a busy desktop often is. The script
  starts VS Code with `--disable-backgrounding-occluded-windows` and its two relatives.
* A native dialog stops the window drawing until somebody answers it. The script makes VS Code draw its own
  (`window.dialogStyle: custom`), which is at least in the picture.
* Webviews (the Digital Thread, the Inspector) are frames of their own, and a second DevTools connection to a
  running VS Code does not see the ones that already exist. So each screenshot is one run, from start to capture.
* The Digital Thread's content security policy forbids evaluating strings, which Playwright's `waitForFunction`
  does; the script polls with `evaluate` instead.
* Clicking the PartCAD icon in the activity bar *hides* the side bar when PartCAD is already showing; the command
  palette's "View: Show PartCAD" only ever shows it.
* The PartCAD Explorer only has the rows on screen in its page, so a row further down is found by scrolling to it.
* `expand()` walks a *path*, one row per level -- it is not a list of siblings, so expanding two top-level
  packages is two calls. And `row()` finds a row by *scrolling to it*, so two packages far apart in a long
  tree are two searches of that tree, and one of them runs out of its 240-second deadline. Where a shot needs
  a second package -- `showStill()` needs a row to show in between, and `produce_part_wrapper` holds one
  object -- pick the package **next to** the subject's: `plugin-part-type` uses `produce_part_sweep`, which
  sorts immediately above it.
* The Inspector loses what it shows when its pane is resized, so the layout is set before the object is selected.
* Requests to the daemon while it is still loading `//pub` can fail with "dictionary changed size during
  iteration", which shows up as an error notification; the script waits for loading to settle before it asks for
  anything else.
* `bin/code`, not the binary itself, is VS Code's command line: the binary with `--install-extension` opens a window.
* VS Code's command line could not reach the running window to open a file (its socket path is too long under a
  temporary directory), so the scratch ASSY file is opened through VS Code's own open dialog
  (`files.simpleDialog.enable`).
* A `<select>`'s drop-down is drawn by the operating system, not by the page, and is not in a capture: the
  `vscode2` Inspector shows its parameters closed.

## Each screenshot

### `vscode1.png`

The examples package (`examples/`) opened as the workspace. In the PartCAD Explorer, `//pub` > `robotics` > `parts` >
`gobilda` expanded, and `examples/wormgear` opened with its "Edit" action, then selected, which shows it in the
Digital Thread beside the editor. The side bar is 330 pixels wide, the editor 520 and the panel 250 high, and the
Inspector pane 200. The terminal on the left is the extension's shell; the one on the right is PartCAD's log.

This is the picture people see first - the README and the Marketplace page - so it is of a real, many-part
assembly rather than an example made for the purpose.

### `vscode2.png`

The same layout - with the Inspector 260 pixels high rather than 200 - with `feature_interface` expanded and
`connect-mates` opened and selected instead. It is there for the Inspector: `connect-mates` takes two parameters, and the Inspector lists them with their values and the
Update button.

### `interface-m3.png`

`feature_interface:m3` - an interface with one port, `m3`, bounded by the sketch `m3-boundary` (a circle) - shown in the
Digital Thread from where a show starts the camera, cut to what is drawn. The port is its axes, X red, Y green and
Z blue, each fading towards its end as three.js draws them; the boundary is the port colour of the viewer.

### `interface-orientation.png` and `interface-orientation-2.png`

`feature_interface:example-motor`, a NEMA-17 stepper that implements `nema-17-motor` on its mounting face. The
camera is turned from where a show starts it to straight down onto that face (`orbit({ left: 36.87, up: 70 })` -
see `orbit()` for the arithmetic) and moved 1.9 times closer, and both pictures are cut to the same rectangle around
the motor. The second one is the first with the Digital Thread's opacity slider at zero: the shape goes, its ports
stay, and each corner port's X axis can be seen pointing at the next port clockwise - the point the text makes.

### `assy-autocompletion.png` and `assy-autocompletion-done.png`

`feature_interface:example-bracket` selected in the Explorer, and a scratch file `tutorial.assy` (in the work
directory, not in the repository) holding `links:`. On the line after it, `- pa` is typed and completion asked for
(`Ctrl+Space`); the first picture is the editor down to the bottom of the suggestion, the second is after Enter,
seven lines of it. What is inserted is whatever the selected Explorer item is - see `completionYaml` in
`ide/vscode/src/extension.ts`.

### `vs-code-behave.png`

The repository itself opened as the workspace, the side bar closed, a new terminal maximized, and in it

```bash
npx --yes @devcontainers/cli exec --workspace-folder . poetry run behave features/config.feature
```

which runs one short feature inside the dev container. `features/config.feature` because it is quick, renders
nothing, and passes. The picture is taken once behave has printed its summary.

### The Digital Thread tabs: `dt-*.png`

One per **tab**, for the "In the UI" section of the chapter about that tab: `dt-<phase>` for a lifecycle
phase and `dt-<phase>-<tab>` for a sub-tab of it. All of them are **the panel alone** rather than the whole
window (`panel()` cuts to the webview's frame, which is the tab strips as well as the 3D view): what is being
shown is the tab, and the editor beside it would be the same picture twenty times over.

Each one selects an object that has something in the tab -- a part with `fea:` scenarios for Analysis, an
assembly with a provider for Buy, a part that can only be *built* for Build -- opens the tab with `tab()`, and
waits for the pane to hold something other than a placeholder (`filled()`). `tab()` takes a group and then a
tab of that group, because the panel has two levels of strip; it refuses a disabled tab rather than
photographing whatever stayed open, which is what **Operations** and **Process Emulation** are.

**The first sub-tab of a group has no picture of its own**, because the group's own picture is taken on it:
`dt-analysis` *is* the FEA tab, `dt-manufacturing` is Build vs Buy, `dt-validation` is Test. Those three
chapters use that file, and nothing here takes the same picture twice. `dt-design` is the exception that
proves the rule: `dt-design-3d` is the same object on the same tab, with the **view panel** brought out, which
is what that chapter is about -- and it is the only picture here in which that panel is out, because it starts
folded and that is how a reader first meets it.

`dt-analysis` and its three siblings are the analysis tab as it opens, which **runs** the first scenario: these
are the shots that need a solver, and each of `feature_cae`'s scenarios names the implementation it was written
against, so the picture does not depend on the user configuration. They are the slowest shots here on a cold
machine -- a container image per solver -- and the same picture afterwards.

**`dt-requirements` has a package of its own.** The Requirements tab is only there for an object that declares
`requirements:`, and no package under `examples/` declares any -- the examples tree is what PartCAD renders and
tests, so a requirement written into one would be one more thing for its checks to be about. So that shot
writes a two-file package (a bracket and the requirements it was asked to meet) into the work directory and
opens VS Code on *that*, the way `assy-autocompletion` writes its scratch ASSY file. Nothing in the repository
changes, and the chapter's picture is still of a real object with real verdicts in it.

**Build and Buy each need an object whose lines are already one of the two**, because no shot here clicks a
switch in Build vs Buy first, and a tab with nothing in it is disabled - `tab()` then throws rather than
photographing whatever stayed open. `provider_manufacturer:assembly` is made by its provider, so both of its
lines say Build and the Build and Assembly tabs are filled (its Buy tab is the disabled one).
`provider_store:nut` is a gobilda part with a vendor and an SKU, in a package that lists a supplier carrying
it, so it is bought.

A part made *from stock* is not the example to reach for here, which cost a run to find:
`feature_cam:panel` declares a `manufacturing:` section and a `source:`, and its Build tab is **disabled** all
the same -- what is bought is the sheet it comes out of, so with nothing chosen the Buy tab is the filled one.
Neither is `feature_interface:connect-mates`, whose package is `manufacturable: false`: its instruction book is
written (that is `dt-manufacturing-assembly`) and its Build tab is disabled.

`dt-manufacturing-buy` is the one picture here with a **date** in it -- a quote has a delivery window and an
expiry, and the example's provider works them out from the clock. It dates the way a version number in a
terminal does, and is retaken with the rest.

### The simulation examples: `sim-example-*.png`

The "Examples" section of the Simulation chapter points at three packages under `examples/`, and shows each
one's run on the **Validation > Simulation** tab. The first of the three is `dt-validation-simulation` above,
which is that package's `stable`; the other two have a shot each.

Opening the tab runs the simulation, so these three need the engine the package names -- MuJoCo, from
`partcad-sim-mujoco`, installed into the sandbox PartCAD runs it in. `sim-example-arm` is the most expensive
picture in this file: it is a real robot arm, and the run is what the FEA chapter's load case comes from.

### The plugin results: `plugin-*.png`

Two of the seven plugin chapters have a result worth a picture rather than a code block: a part built by a
`partTypes:` script, and a part served by a `repositories:` script. The point of each is that the object looks
like any other object in the panel, which is the thing the prose claims.

The other five chapters keep copy-pasteable commands instead. A terminal screenshot of `pc export -t ...`
tells a reader nothing the command does not, cannot be copied, and goes stale on the next release -- and every
PNG here goes through Git LFS.

### `docker-for-desktop.png` (by hand)

Docker Desktop's "Containers" page with the PartCAD dev container running. It is a picture of somebody else's
program, so the script does not take it, and it has nothing PartCAD draws in it, so it does not go out of date
when PartCAD changes - retake it when Docker Desktop changes enough that the page in the guide no longer looks
like it.

1. Start the dev container (from VS Code, "Dev Containers: Reopen in Container", or with the command above).
2. Open Docker Desktop on its "Containers" page, with "Only show running containers" on, so that the dev container
   is the one row.
3. Size the window to 1920 x 1080, the size of the picture there now, and capture the window alone, without the
   desktop around it.
