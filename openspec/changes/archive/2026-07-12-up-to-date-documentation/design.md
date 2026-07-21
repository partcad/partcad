## Context

PartCAD's user documentation lives in two places: reStructuredText under `docs/source/` (rendered to HTML by
Sphinx with the `sphinx_rtd_theme`, built via `sphinx-build -M html docs/source docs/build -n -W`) and a set of
Markdown `README.md` files (repository root, each package, and every example project). The software surface it
must describe is defined by two authoritative sources:

- the CLI command tree under `partcad-cli/src/partcad_cli/click/commands/` (loaded dynamically by
  `partcad-cli/src/partcad_cli/click/loader.py`), and
- the VS Code extension commands declared in `partcad-ide-vscode/package.json` under `contributes.commands`.

Today the docs have drifted from both: the `pc --help` block in `installation.rst` is missing ~9 command groups
and shows the old top-level `status` (now `system status`); groups like `search`, `ai`, `adhoc`, `lint`,
`config` have no mentions at all; committed prose contains typos; and there is no enforced guarantee the site
builds warning-free. This change is documentation-only — no CLI or extension behavior changes.

## Goals / Non-Goals

**Goals:**
- Make the documented CLI and extension surface an accurate reflection of what actually ships.
- Guarantee a clean `-n -W` (nitpicky, warnings-as-errors) Sphinx build.
- Raise prose quality: remove typos/grammar errors, simplify over-complex sentences.
- Keep `README.md` files consistent with `docs/source`.
- Leave behind a repeatable audit method (command-tree vs. docs) so future drift is easy to detect.

**Non-Goals:**
- No changes to CLI/extension/library behavior, flags, or output.
- Not auto-generating docs from the Click tree (e.g. `sphinx-click`) in this change — see Decisions.
- Not restructuring the docs information architecture beyond what accuracy and a clean build require.
- Not rewriting `contributing.rst`'s process content (only fixing its typos/prose as part of the quality pass).

## Decisions

- **Authoritative surface = source, not memory.** The audit derives the CLI list from
  `partcad-cli/src/partcad_cli/click/commands/` (cross-checked with `pc --help` and each `pc <group> --help`)
  and the extension list from `package.json` `contributes.commands`. Docs are reconciled against these, not
  against prior doc text. Alternative (trusting existing docs as the baseline) rejected — that is exactly what
  drifted.
- **Manual, curated prose over generated CLI reference (for now).** We keep hand-written `.rst`/`README` rather
  than introducing `sphinx-click` auto-generation. Rationale: adding an extension + reformatting every command
  page is a larger, riskier change than the accuracy fix being asked for, and the existing docs are narrative
  (workflow-oriented), not a flat command dump. We instead add/patch a command reference section and note the
  audit method so regeneration can be considered later. Trade-off: future drift is still possible — mitigated by
  the documented audit step and the clean-build gate.
- **Clean build is a gate, verified with the project's own command.** We use exactly
  `sphinx-build -M html docs/source docs/build -n -W` from `contributing.rst` as the pass/fail check, run in the
  Poetry `docs` group environment. Using the project's documented command (rather than a looser one) ensures we
  catch the same warnings CI/contributors would. Note `conf.py` sets `html_js_files` to an external
  `googletagmanager.com` URL and `extensions = []`; the build check will surface any warning this or missing
  references produce, and we fix the cause rather than relax `-W`.
- **Fix prose in place, page by page.** Typos/grammar/complex-sentence fixes are applied directly in each file
  during the same pass that checks accuracy, keeping one coherent edit per file rather than a separate
  mechanical spellcheck commit. A spell/style scan (e.g. `codespell` and manual review) seeds the list; every
  flagged item is judged in context (PartCAD-specific terms like `build123d`, `CadQuery`, `assy` are not
  errors).
- **Scope README depth by audience.** Per-example `examples/**/README.md` stay short and example-specific
  (what the example shows + how to run it); the four top-level READMEs (root, `partcad`, `partcad-cli`,
  `partcad-ide-vscode`) get the fuller accuracy pass and must agree with `docs/source`.

## Risks / Trade-offs

- [The clean `-n -W` build may surface pre-existing warnings unrelated to content (theme, external JS, missing
  cross-references)] → Treat build-fixing as part of the change; fix the root cause (bad reference, malformed
  directive) rather than disabling `-W`. If a warning is truly external/unfixable, document why and narrow the
  suppression to that specific case.
- [Manual audit can still miss a command] → Make the audit explicit and reproducible: enumerate the command
  files and the `contributes.commands` list, diff against a checklist, and record the mapping so a reviewer can
  re-run it. The spec's scenarios name the specific groups that must appear.
- [Subjective "excessively complex sentence" / "well written" criteria] → Anchor to concrete, checkable proxies
  in the spec (known typos removed; specific dense sentences simplified) plus a tool-assisted spell pass, rather
  than relying purely on judgment.
- [Docs environment not yet built locally] → The Poetry `docs` dependency group exists; provisioning `.venv`
  and running the documented Sphinx command is part of the tasks, so the build gate is actually executed, not
  assumed.

## Migration Plan

Documentation-only change. Rollout is a normal PR; rollback is a `git revert`. No data, API, or deployment
migration. The only "deploy" effect is the rebuilt Read the Docs / HTML site picking up corrected content.

## Open Questions

- Should a dedicated CLI **command-reference page** be added to the `index.rst` toctree, or should the missing
  commands be folded into the existing workflow pages (`tutorial`, `features`, `use_cases`)? Leaning toward a
  concise reference section plus contextual mentions; final placement decided during implementation to keep the
  toctree coherent and the build clean.
