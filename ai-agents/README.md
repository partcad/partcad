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
  the official `install.sh`; `python-module` installs the `partcad-cli` module
  into the active Python environment (run as `python -m partcad_cli.click.command`).
  Until a standalone release is published, `executable` reports that no published
  installer is available and stops.
- **`/pc:gen <description>`** — decides whether the request is a part or an
  assembly and follows the matching flow below.
- **`/pc:gen-part <description>`** — generates a single part: the agent picks a
  representation (build123d / cadquery / openscad / sdf), authors the CAD script
  itself, and validates it by rendering with `pc render`. Supersedes the legacy
  `pc add part --ai` pipeline (the agent is the model; no provider/API key).
- **`/pc:gen-assembly <description>`** — generates an assembly: reuses or
  generates the component parts, authors the `.assy` (explicit placement or
  interface mates), and validates by rendering. New capability — PartCAD had no
  AI assembly path.

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
