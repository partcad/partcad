# AI agent skills

Skills for AI coding agents that work on PartCAD projects. The skills themselves
are vendor-neutral [Agent Skills](https://code.claude.com/docs/en/skills)
(`SKILL.md` folders) so any `SKILL.md`-aware agent can consume them; the Claude
plugin is a thin wrapper that ships the same files to the Claude marketplace.

## Layout

```
ai-agents/
├── common/
│   └── skills/                     # source of truth: one SKILL.md folder per skill
│       └── init/SKILL.md           #   → usable by any agent that reads SKILL.md
├── claude/                         # the Claude plugin (name: pc)
│   ├── .claude-plugin/plugin.json
│   └── skills -> ../common/skills  # symlink: no duplication
└── scripts/
    └── materialize.sh              # publish-time: deref the symlink into real files
```

Two more files outside this directory tie it together:

- `../.claude-plugin/marketplace.json` — top-level catalog (for discoverability),
  lists `pc` with `source: ./ai-agents/claude`.
- `../.claude/skills/pc -> ../../ai-agents/claude` — makes Claude auto-discover
  the plugin as `pc@skills-dir` when this repo is opened as the workspace, so
  `/pc:init` is available with no install step.

The plugin folder is named `claude`, but the command namespace comes from
`plugin.json`'s `name` field (`pc`), so skills invoke as `/pc:<skill>`.

## Skills

- **`/pc:init`** — initializes a PartCAD package by delegating to the installed
  CLI (`pc init` / `partcad init`). It resolves the command from `PATH` or the
  active Python environment (`python -m partcad_cli.click.command`); if PartCAD
  is missing it points the user at `/pc:install` instead of hand-writing files.
- **`/pc:install <mode>`** — makes `pc`/`partcad` available. `executable`
  installs the standalone PyInstaller build from the latest GitHub release via
  the official `install.sh`; `python-module` installs the `partcad` wheel
  into the active Python environment (run as `python -m partcad_cli.click.command`).
  Releases publish bundles for Linux (x86_64, arm64), macOS (Apple silicon) and
  Windows, and a `platforms.json` the installer reads to pick this machine's.
- **`/pc:gen <description>`** — decides whether the request is a part, an
  assembly, or a 2D sketch and follows the matching flow below.
- **`/pc:gen-part <description>`** — generates a single part: the agent picks a
  representation (build123d / cadquery / openscad / sdf), authors the CAD script
  itself, and validates it by rendering **four views** (`front`, `top`, `right`,
  `iso`) and checking each against the description — `pc test` only proves the
  geometry instantiates, and one projection hides whatever is behind it.
  Supersedes the legacy `pc add part --ai` pipeline (the agent is the model; no
  provider/API key).
- **`/pc:gen-assembly <description>`** — generates an assembly: reuses or
  generates the component parts, authors the `.assy` (explicit placement or
  interface mates), and validates the same four ways — a component offset along
  the viewing direction sits perfectly in the one view that hides the offset. New
  capability — PartCAD had no AI assembly path.
- **`/pc:gen-sketch <description>`** — generates a 2D sketch: the agent picks a
  representation (build123d / cadquery / dxf / svg), authors the sketch, and
  validates by rendering to SVG.
- **`/pc:export <object> <format>`** — writes a 3D/CAD file out of an object a
  package declares (`pc export`) and changes nothing in `partcad.yaml`. This is
  what "export it as STEP" almost always means. It reaches more formats than
  `pc convert` does — `urdf`, plus any file type a package implements itself.
- **`/pc:convert <what> <to what>`** — changes what something *is*. For an
  object in a package that is `pc convert`, which writes the file **and**
  rewrites the object's definition to point at it; for a file that belongs to no
  package it is `pc adhoc convert`, which touches no package at all.
- **`/pc:render <what> <from where>`** — writes a 2D projection to look at
  (`png`, `jpeg`, `svg`, `dxf`): `pc render` for an object in a package, so the
  package's own `render:` options apply, and `pc adhoc render` for a bare file.
  The viewing angle is `--view front|top|iso|…`, or `--viewport-origin` /
  `--viewport-up` for an arbitrary one — the same two keys a `render:` file type
  is configured with in `partcad.yaml`. `--with-ports` / `--with-interfaces` /
  `--with-all` draw the connection metadata on top of the projection, which is
  the only way any of it becomes visible.

  All three begin the same way, because the answer to "which command" is the
  same question in each: is there a package, and does what the user named
  resolve to an object in it (by name, or as the file an object is built from)?
  If so the package command is right; if not it is the `adhoc` one, and
  `pc export` has no `adhoc` form because `pc adhoc convert` already is it.
- **`/pc:describe <object>`** — writes a narratable description of an existing
  part, assembly, or sketch, and stores it in the object's `summary:`.
  Reproduces the retired built-in AI shape-summary. It renders **three views**
  (`front`, `top`, `iso`) rather than one, since a single projection hides
  everything behind it — and for a part it also asks
  `//pub/feature/render/draftwright` (through `pc render -e`) for a dimensioned
  technical drawing, so the numbers in the description are read off the drawing
  instead of estimated from pixels.
- **`/pc:add-interfaces <part>`** — adds `interfaces`, ports and `implements:`
  to an existing part so PartCAD can mate it by connection rather than by
  hand-placed coordinates. The agent works the port positions out of the
  geometry and then proves them twice: by drawing them on the part
  (`pc render --with-all`) and by mating two instances in a throwaway assembly
  and rendering that. The part has to pass `pc test` and the validation assembly
  has to come out correctly connected.
- **`/pc:search <query>`** — finds existing parts and assemblies in the catalog
  whose name, description, or source matches the query (`pc search parts` /
  `pc search assemblies`), lists the matches, and can inspect or render a chosen
  one. Searches the local package by default; `-r` widens to every imported
  package (the public registry and dependencies).

## Local use (Claude)

Open the repo root as the workspace and accept the trust prompt. Claude loads
`pc@skills-dir`; run `/pc:init`. Notes:

- Launch Claude from the **repo root** — project-scope skills-dir plugins do not
  walk up from a subdirectory.
- After editing a `SKILL.md`, changes are live; structural changes need
  `/reload-plugins`.

## Shipping to the Claude marketplace

Installs on macOS/Linux dereference the `skills` symlink automatically, but
**Windows git checkouts may not preserve symlinks**, which would ship an empty
plugin. The release automation publishes a materialized (symlink-free) artifact,
so what users install is safe everywhere.

### Cut a release

From a clean working tree, bump `version` in
`ai-agents/claude/.claude-plugin/plugin.json`, commit, then:

```bash
claude plugin tag ai-agents/claude --push   # creates & pushes pc--v<version>
```

`claude plugin tag` validates that the manifest and the marketplace entry agree,
then pushes a `pc--v<version>` tag. That fires
`.github/workflows/ai-agents-release.yml`, which re-validates, runs
`materialize.sh`, and publishes two ways:

- **`plugin-dist` branch** — the symlink-free marketplace at its root (rolling
  "latest"):
  ```
  /plugin marketplace add <owner>/<repo>@plugin-dist
  /plugin install pc@partcad
  ```
- **GitHub Release** — `pc.zip` attached to the `pc--v<version>` release
  (immutable, pin-able):
  ```
  claude --plugin-url https://github.com/<owner>/<repo>/releases/download/pc--v<version>/pc.zip
  ```

The release step needs no Anthropic credentials — it uses only the automatic
`GITHUB_TOKEN` (no PAT, no stored secret).

### Build the artifact locally

```bash
ai-agents/scripts/materialize.sh          # writes ai-agents/.build/marketplace
```

Produces a self-contained `pc/` plugin (real `skills/` files), a `marketplace.json`
pointing at it, and `pc.zip`.

Note: because the `skills` symlink escapes the plugin directory into `common/`, a
lightweight `git-subdir` marketplace source will **not** work (the sparse clone
misses `common/`); use the materialized artifact or a full-repo `github` source.

## CI

`.github/workflows/ai-agents.yml` validates the catalog and plugin with
`claude plugin validate`, runs the materialization, and asserts the artifact is
symlink-free. It uses **no credentials** — validation is fully offline.

## Windows contributors

If local discovery or a build produces a `skills` file containing the text
`../common/skills` instead of a directory, git did not materialize the symlink.
Enable symlinks and re-checkout:

```bash
git config core.symlinks true
```
