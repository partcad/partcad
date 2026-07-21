## Context

The monorepo has three components with different toolchains — `partcad` (Python core, Poetry/pytest),
`partcad-cli` (Python CLI, same Poetry workspace), and `partcad-ide-vscode` (TypeScript/Node, npm/nox) — plus
integration tests in `./features` (behave) and docs in `./docs` (Sphinx). The root `AGENTS.md`/`CLAUDE.md`
already anticipates per-component `AGENTS.md` files but they were never written, and the root file's own
"Development process" section is an empty placeholder. Human-oriented setup/test/commit instructions already
exist in `docs/source/contributing.rst`, `pyproject.toml`, `dev-tools/pre-commit-config.yaml`, and
`.github/workflows/*.yml` — this change reformats/summarizes that existing source of truth for agent
consumption, it does not invent new process.

## Goals / Non-Goals

**Goals:**
- Give a coding agent everything needed to set up the environment, build, run tests, lint, and commit in each
  component, without re-deriving it from `contributing.rst` or CI YAML every session.
- Keep every file short (agents pay a context-window cost per file read) and skimmable — command lists and
  short bullets, not prose.
- Keep instructions accurate over time: the root file references `contributing.rst` for anything long-form or
  likely to drift (Docker/dev-container setup, PR review criteria) instead of duplicating it.

**Non-Goals:**
- Not rewriting or restructuring `docs/source/contributing.rst` (human-facing docs are out of scope).
- Not adding new lint/test tooling, CI jobs, or pre-commit hooks.
- Not documenting `./features` (behave) or `./docs` (Sphinx) as their own top-level components — behave tests
  belong conceptually to `partcad`/`partcad-cli` and are covered by their `AGENTS.md`; docs build steps are
  covered by a `docs` mention in the root file only, since no agent work is expected to be centered there yet.

## Decisions

- **One `AGENTS.md` per existing package directory (`partcad/`, `partcad-cli/`, `partcad-ide-vscode/`), matching
  the links already present in the root file.** Alternative considered: a single root `AGENTS.md` with
  component sections. Rejected because the root file already promises per-directory files, and directory-local
  files let an agent working inside `partcad-cli/` find conventions without reading unrelated Python/TS/CLI
  detail — Claude Code and Cursor both discover the nearest `AGENTS.md`/`CLAUDE.md` up the directory tree.
- **Root `AGENTS.md` "Development process" section becomes a short command index, not a copy of
  `contributing.rst`.** It lists the minimal commands (`poetry install`, `poetry shell`, `pytest`, `behave`,
  `pre-commit run`) and links to `docs/source/contributing.rst` for the Docker/dev-container narrative and PR
  merge-criteria detail that agents don't need to act on. Rejected duplicating the full guide inline: it would
  drift from `contributing.rst` and blow the token budget every agent pays to read `AGENTS.md`.
  `CLAUDE.md` is already a symlink to `AGENTS.md`, so it needs no separate edit.
- **`contributing.rst`'s parallelism section (asyncio/thread pool) and the `_async` naming suffix convention are
  duplicated briefly in `partcad/AGENTS.md`**, since they directly constrain how an agent should write new core
  code, unlike the process-only sections that stay linked rather than copied.
- **Commands are copied verbatim from their source of truth** (`pyproject.toml` scripts/tool sections,
  `dev-tools/pre-commit-config.yaml`, `.github/workflows/test.yml`, `partcad-ide-vscode/package.json` scripts)
  rather than paraphrased, so they can be run as-is.
- **`partcad-cli/AGENTS.md`'s validation step is the examples-based CLI smoke test, not `pytest` alone.**
  `.github/workflows/test.yml`'s `test-examples-partcad` job runs `pc list all -r //pub/examples/partcad`,
  `pc test -r --package //pub/examples/partcad`, and `pc render -r --package //pub/examples/partcad` from the
  `./examples` directory (the `test-examples-all` job does the same against `//pub/examples`); this is the
  actual CI gate for CLI correctness (argument parsing, package resolution, output), which the CLI's own
  `pytest` unit tests don't exercise end-to-end. Alternative considered: documenting only `pytest` for
  `partcad-cli`, matching `partcad`. Rejected because it would let an agent believe unit tests alone validate a
  CLI change when CI actually also requires the example run to pass.
  `partcad/AGENTS.md`'s validation step stays `pytest` alone — the core module has no CLI surface to smoke-test
  against the examples the same way.

## Risks / Trade-offs

- [Instructions drift from `contributing.rst` or CI over time as tooling changes] → Root file explicitly points
  to `contributing.rst` as the source of truth for anything not command-level, and each `AGENTS.md` sources its
  commands from a named config file (`pyproject.toml`, `package.json`, workflow YAML) so a future update to
  those files is the natural trigger to also update the matching `AGENTS.md`.
- [Per-package `AGENTS.md` content overlaps/contradicts the root file] → Root file only contains cross-cutting
  and monorepo-wide commands; component-specific commands (e.g. `npm run lint` vs `pytest`) live only in the
  matching package's `AGENTS.md`.
- [Agents outside Claude Code / Cursor don't discover `AGENTS.md`] → Out of scope; `AGENTS.md` is the emerging
  cross-tool convention (Claude Code, Cursor, and others) and the repo's own `.claude`/`.cursor` configs already
  assume it.

## Migration Plan

Documentation-only change: add/edit four Markdown files, no code or config changes, no rollback risk beyond a
`git revert`.

## Open Questions

None outstanding — scope confirmed by proposal.md's Impact section (four `AGENTS.md` files, no code changes).
