## Why

Coding AI agents (Claude Code, Cursor, and similar tools) are already operating in this repository, but the
instructions available to them are incomplete: the root `AGENTS.md` (symlinked from `CLAUDE.md`) links to
`partcad/AGENTS.md`, `partcad-cli/AGENTS.md`, and `partcad-ide-vscode/AGENTS.md`, none of which exist, and its
own "Development process" section is a placeholder (`...`). Agents are left to reverse-engineer build, test,
lint, and commit conventions from `docs/source/contributing.rst`, `pyproject.toml`, and CI workflows on every
task, which wastes turns and risks agents inventing commands (e.g. running `pytest` without the required
`poetry run` context, or skipping `pre-commit` hooks) that diverge from what human contributors actually use.
This repository must instead give agents a concise, accurate, and maintained set of instructions so they can
build, test, lint, and commit exactly like a human contributor would, in every component of the monorepo.

## What Changes

- Fill in the root `AGENTS.md` "Development process" section with concrete, concise pointers (environment
  setup, dependency install, running tests/lint, commit hooks, PR flow) rather than `...`, sourced from
  `docs/source/contributing.rst` so the two never contradict each other.
- Create `partcad/AGENTS.md` documenting how to build, test (`pytest`, working directory, markers), and lint
  the core Python module, plus any module-specific conventions (async/sync coroutine naming, coordinate/location
  format) an agent needs to write conforming code. It SHALL state that running `pytest` to a clean pass is the
  required validation step for any change to the core module.
- Create `partcad-cli/AGENTS.md` documenting how to build, test, and lint the CLI package, and its relationship
  to the `partcad` core module. It SHALL also document the example-driven validation workflow already used in
  CI (`.github/workflows/test.yml`'s `test-examples-partcad`/`test-examples-all` jobs): running relevant `pc`/
  `partcad` CLI commands (`list`, `test`, `render`) against the example projects under `./examples`, since that
  end-to-end run — not `pytest` alone — is what actually gates CLI changes in CI.
- Create `partcad-ide-vscode/AGENTS.md` documenting the Node/TypeScript toolchain (`npm`, `nox` sessions,
  `eslint`, packaging the `.vsix`, installing it locally) used by the VS Code extension.
- Ensure every new/updated `AGENTS.md` file only states commands and conventions that are verified against the
  actual repo tooling (`pyproject.toml`, `dev-tools/pre-commit-config.yaml`, `.github/workflows/*.yml`,
  `package.json` files) rather than assumed or invented.
- No change to `CLAUDE.md` beyond what the existing symlink to `AGENTS.md` already picks up automatically.

## Capabilities

### New Capabilities
- `agent-instructions`: Concise, per-component `AGENTS.md` instructions (root + `partcad` + `partcad-cli` +
  `partcad-ide-vscode`) that let a coding agent set up the environment, build, test, lint, and commit code using
  the same tools and conventions as human contributors, kept consistent with `docs/source/contributing.rst`.

### Modified Capabilities
(none — no existing specs cover agent instructions yet)

## Impact

- Affected files: `AGENTS.md` (root, edited in place; `CLAUDE.md` is an existing symlink to it and needs no
  separate edit), new `partcad/AGENTS.md`, `partcad-cli/AGENTS.md`, `partcad-ide-vscode/AGENTS.md`.
- No source code, build, or CI changes — this is documentation-only and carries no runtime or breaking impact.
- Downstream: every future coding-agent session in this repo (Claude Code, Cursor, others reading `AGENTS.md`)
  benefits immediately since `CLAUDE.md` already symlinks to the root file and `.cursor`/`.claude` command
  configs reference the same monorepo layout.
