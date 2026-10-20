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
| `interface-m3.png` | The interface `m3`: a port drawn as its axes and its boundary sketch | `docs/source/config_geometry.rst` | `shoot.mjs interface-m3` |
| `interface-orientation.png` | `example-motor` seen from above, its four NEMA-17 mounting ports each pointing its X axis at the next one | `docs/source/config_geometry.rst` | `shoot.mjs interface-orientation` |
| `interface-orientation-2.png` | The same view with the motor faded out, so only the ports are left | `docs/source/config_geometry.rst` | taken with the one above |
| `assy-autocompletion.png` | `- pa` typed in an ASSY file, and the completion offering the part selected in the Explorer | `docs/source/tutorial.rst` | `shoot.mjs assy-autocompletion` |
| `assy-autocompletion-done.png` | The link that completion inserts | `docs/source/tutorial.rst` | taken with the one above |
| `vs-code-behave.png` | VS Code's terminal running `behave` in the dev container | `docs/source/contributing.rst` | `shoot.mjs vs-code-behave` |
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
* **A still 3D view.** The Digital Thread turns the model on its own until its "Animate" box is cleared, and that
  box is not there until something has been shown. So each object is shown, the box cleared, another object shown,
  and the object shown again: a show of a new object puts the camera back where every show starts it, which makes
  the framing the same on every run.
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
