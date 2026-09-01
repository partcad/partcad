# AI agent skills

Skills for AI coding agents that work on PartCAD projects. The skills themselves
are vendor-neutral [Agent Skills](https://code.claude.com/docs/en/skills)
(`SKILL.md` folders) so any `SKILL.md`-aware agent can consume them; the Claude
plugin is a thin wrapper that ships the same files to Claude Code.

## Install

```text
/plugin marketplace add partcad/partcad@plugin-dist
/plugin install pc@partcad
```

There is no hosted catalog to search: a marketplace is a git repository with a
`.claude-plugin/marketplace.json` in it, and this repository is one.
`plugin-dist` is a branch every PartCAD release republishes — the same plugin
with the `skills` symlink dereferenced into real files, so that it installs
identically where git does not create symlinks.

Two alternatives. `/plugin marketplace add partcad/partcad` reads the catalog
straight out of the source tree, which needs a checkout where that symlink
exists (see *Windows contributors* below). And every
[release](https://github.com/partcad/partcad/releases) carries a
`pc-<version>.zip` that `claude --plugin-url <url>` loads for one session, to
try a version without installing it.

## Layout

```
ai-agents/
├── common/
│   └── skills/                     # source of truth: one SKILL.md folder per skill
│       └── init/SKILL.md           #   → usable by any agent that reads SKILL.md
├── claude/                         # the Claude plugin (name: pc)
│   ├── .claude-plugin/plugin.json  # version: the repository's, bumped with it
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
  is missing it points the user at `/pc:setup` instead of hand-writing files.
- **`/pc:setup <mode>`** — makes `pc`/`partcad` available. `executable`
  installs the standalone PyInstaller build from the latest GitHub release via
  the official `install.sh`; `python-module` installs the `partcad` wheel
  into the active Python environment (run as `python -m partcad_cli.click.command`).
  Releases publish bundles for Linux (x86_64, arm64), macOS (Apple silicon) and
  Windows, and a `platforms.json` the installer reads to pick this machine's.
  The same release publishes this plugin, so the plugin's version names the
  PartCAD the skills were written against, and is what `--version` pins if the
  newest one ever behaves differently.

  It then installs the **PartCAD extension** too, but only when the session is
  running in an editor that can host it: `TERM_PROGRAM=vscode` and the editor's
  own command line tool on `PATH` are what say which one, since Visual Studio
  Code, VSCodium and the PartCAD IDE are indistinguishable otherwise. The IDE
  already carries the extension and is left alone. The other two both install
  `PartCAD.partcad` — the same command, each resolving it against its own
  gallery: the Visual Studio Marketplace, and Open VSX for VSCodium, which is
  not pointed at the Marketplace because its terms restrict it to Microsoft's
  own products (see *Licensing* in
  [`ide/standalone`](../ide/standalone/README.md)). The release's `.vsix` is the
  fallback when a gallery cannot be reached or a version has to be pinned.

  Not named `install`: `pc install` is PartCAD's `npm install`, which fetches a
  package's imports and needs PartCAD to already be here. This skill is what
  puts it here.
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

## Versioning

The plugin has no version of its own.
`ai-agents/claude/.claude-plugin/plugin.json` is listed in
[`dev-tools/bumpversion.toml`](../dev-tools/bumpversion.toml), so it moves with
the wheel, the VS Code extension, the FreeCAD addon and everything else the
moment a release is cut — `pc` the plugin and `pc` the command line tool it
drives state the same version when they came from the same release.

It used to carry a version of its own, and that is precisely why it sat at
`0.1.0` for twenty-three releases: publishing it meant remembering to push a
`pc--v<version>` tag, and nobody ever did.
`tests/partcad_cli/unit/test_versions.py` fails now if the manifest falls out of
step, or if it stops being declared.

## How it is published

Nothing to do by hand — the release publishes the plugin.

[`.github/workflows/plugin.yml`](../.github/workflows/plugin.yml) builds it:
materialize, validate both manifests, install the result and check that every
skill in the library is in the installed inventory, and then unpack the archive
on Windows to prove the files survived a filesystem with no symlinks.
`build.yml` calls it on every pull request. `deploy.yml` calls it for a release,
and then

- attaches `pc-<version>.zip` to the GitHub release, beside the wheels and the
  `.vsix`, and
- force-pushes the materialized marketplace to the `plugin-dist` branch — last,
  so that the "latest" pointer only moves once the release it names exists.

Installs on macOS and Linux dereference the `skills` symlink by themselves, but
**Windows git checkouts may not preserve symlinks**, which would ship an empty
plugin. That is what the materialized artifact is for, and why both published
forms are symlink-free.

To rebuild the artifacts without cutting a release, run the `Plugin` workflow
from the Actions tab. To republish `plugin-dist` alone, re-run the `Deployment`
run of the release it should carry.

The publish is a force-push, so it is guarded twice against moving the branch
backwards. Concurrent releases are serialized by a concurrency group on that job
alone, and — because a re-run of an older release is not concurrent with
anything — the job reads the version `plugin-dist` currently carries and refuses
to publish an older one over it. Republishing an *earlier* release therefore
fails on purpose, with the version it found; delete the branch if that is really
what you want.

### Build the artifact locally

```bash
ai-agents/scripts/materialize.sh          # writes ai-agents/.build/marketplace
```

Produces a self-contained `pc/` plugin (real `skills/` files), a
`marketplace.json` pointing at it, and `pc-<version>.zip`. Two prerequisites,
both of which the script checks rather than working around: the Claude Code CLI
on `PATH`, because it validates both manifests, and `zip`, because the archive
is what the release attaches — it is a required output, so a machine without
`zip` gets an error here rather than a partial artifact and a puzzling failure
later.

Note: because the `skills` symlink escapes the plugin directory into `common/`, a
lightweight `git-subdir` marketplace source will **not** work (the sparse clone
misses `common/`); use the materialized artifact or a full-repo `github` source.

## CI

`plugin.yml` is the whole of it, and it uses **no credentials**:
`claude plugin validate`, the materialization and the install smoke test all run
offline against a directory on the runner. It must never reference
`ANTHROPIC_API_KEY`, a login, or any repository secret.

`tests/partcad_cli/unit/test_ai_agent_skills.py` covers what validation cannot
see. Run against `ai-agents/claude`, `claude plugin validate` warns that `skills`
is a symlink, reads nothing through it, and passes — so a `SKILL.md` with no
front matter, or with a `name` that does not match its directory, would get as
far as whoever installed the plugin. The pytest run reads every one of them for
real, on commit.

## Windows contributors

If local discovery or a build produces a `skills` file containing the text
`../common/skills` instead of a directory, git did not materialize the symlink.
Enable symlinks and re-checkout:

```bash
git config core.symlinks true
```
