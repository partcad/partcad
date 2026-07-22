## Why

The user-facing documentation has drifted behind the software: `docs/source/installation.rst` prints a `pc --help`
listing of ~13 top-level commands while the CLI actually ships ~21 command groups, and entire groups (`search`,
`ai`, `adhoc`, `lint`, `config`, `convert`, `export`, `healthcheck`, `import`, `system`) are either absent or
barely mentioned across `docs/source`. There are also outright typos in committed prose (`contrinute`, `insteaf`,
`How to contrbute?`), and no guarantee that `docs/source` renders to HTML cleanly under the project's own
warnings-as-errors build (`sphinx-build -M html docs/source docs/build -n -W`). The result is that new users and
contributors are given instructions that no longer match the tools in front of them.

## What Changes

- Audit every user-facing capability — the full `pc`/`partcad` CLI surface and every VS Code extension command —
  against `docs/source/*.rst` and all `README.md` files, and produce a documented, verifiable coverage map so
  nothing user-visible is silently undocumented.
- Update `docs/source/installation.rst` (and any other stale command references) so the documented CLI surface
  matches the actual top-level commands and their current names (e.g. `status` is now `system status`).
- Document the currently-missing CLI command groups (`search`, `ai`, `adhoc`, `lint`, `config`, `convert`,
  `export`, `healthcheck`, `import`, `install`, `test`, `update`) and the VS Code extension's user-facing
  commands (init/open package, add/import/inspect/test/regenerate, and the export-to-format actions).
- Refresh the `README.md` files (root, `partcad/`, `partcad-cli/`, `partcad-ide-vscode/`, `examples/` and its
  per-example READMEs) so they reflect the current functionality and are consistent with `docs/source`.
- Make a clean documentation build a first-class, checkable requirement: `docs/source` MUST render to HTML with
  no errors or warnings under `sphinx-build -M html docs/source docs/build -n -W`, per
  `docs/source/contributing.rst`.
- Fix typos, grammar mistakes, and excessively complex sentences throughout the documentation, applying standard
  technical-writing practices (active voice, one idea per sentence, consistent terminology).
- No source-code, CLI, or extension behavior changes — documentation and README content only.

## Capabilities

### New Capabilities
- `user-documentation`: Accuracy, completeness, buildability, and writing quality of PartCAD's user-facing
  documentation (`docs/source/*.rst` and all `README.md` files) — every user-visible CLI command and VS Code
  extension feature is documented, the Sphinx site builds with no errors/warnings, and the prose is free of
  typos, grammar mistakes, and needlessly complex sentences.

### Modified Capabilities
(none — no existing spec covers user-facing documentation; `agent-instructions` covers only contributor
`AGENTS.md` guidance and is unaffected)

## Impact

- Affected files: `docs/source/*.rst` (notably `installation.rst`, `tutorial.rst`, `features.rst`,
  `use_cases.rst`, `configuration.rst`, `contributing.rst`), `docs/source/conf.py` if a warning originates there,
  and every tracked `README.md` (root, `partcad/`, `partcad-cli/`, `partcad-ide-vscode/`, `examples/**`).
- Source of truth for the audit: the CLI command tree under
  `partcad-cli/src/partcad_cli/click/commands/` and the extension command list in
  `partcad-ide-vscode/package.json` (`contributes.commands`).
- Build/tooling: relies on the existing Sphinx toolchain (`sphinx`, `sphinx-rtd-theme`, extensions in the
  `docs` Poetry group); no new dependencies. Verified via the documented `sphinx-build ... -n -W` command.
- No runtime, API, or breaking impact; changes are limited to documentation content.
