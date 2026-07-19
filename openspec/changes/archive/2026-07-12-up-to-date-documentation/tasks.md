## 1. Establish the documentation environment and baseline build

- [x] 1.1 Provision the docs environment (`poetry install` with the `docs` group) and confirm `sphinx-build` is
      available (`poetry run sphinx-build --version`). Done: `sphinx-build 8.2.3` available via Poetry.
- [x] 1.2 Run the project's documented build `sphinx-build -M html docs/source docs/build -n -W` and capture the
      full list of current errors/warnings as the baseline to fix. Baseline: build already passes (exit 0, zero
      warnings); the task is now to keep it clean after edits.

## 2. Audit the user-facing surface (source of truth)

- [x] 2.1 Enumerate every CLI command group and subcommand from
      `partcad-cli/src/partcad_cli/click/commands/`, cross-checked with `pc --help` and `pc <group> --help`,
      into a checklist. Done: 21 top-level commands captured (see scratchpad `cli_help.txt`, `audit.md`).
- [x] 2.2 Enumerate every user-facing VS Code command from `partcad-ide-vscode/package.json`
      (`contributes.commands`) into the same checklist. Done: recorded in `audit.md` (init/open, add/import,
      inspect, test, AI gen/regen/change, 9 export formats).
- [x] 2.3 Map each CLI command and extension command to where it is (or should be) documented in `docs/source`
      and the relevant `README.md`; mark gaps and stale references (e.g. `installation.rst` `pc --help`,
      missing `search`/`ai`/`adhoc`/`lint`/`config`/`convert`/`export`/`healthcheck`/`import` coverage). Done:
      gaps + doc plan recorded in `audit.md`.

## 3. Fix CLI documentation accuracy and coverage

- [x] 3.1 Update the `pc --help` block and any other reproduced command lists in
      `docs/source/installation.rst` so they match the current top-level commands and names
      (e.g. `system status` not top-level `status`). Done: replaced with current grouped listing + common
      options note + link to the new reference.
- [x] 3.2 Document the missing command groups (`search`, `ai`, `adhoc`, `lint`, `config`, `convert`, `export`,
      `healthcheck`, `import`, `install`, `test`, `update`) — purpose and primary invocation/options — placing
      them in a command reference and/or the relevant workflow pages, keeping the `index.rst` toctree coherent.
      Done: new `docs/source/cli.rst` reference page added to the toctree.
- [x] 3.3 Verify the remaining CLI groups already mentioned (`add`, `info`, `init`, `inspect`, `list`, `render`,
      `supply`, `system`, `version`) are described accurately and reflect current options. Done: all covered in
      `cli.rst` with current subcommands/options.

## 4. Fix VS Code extension documentation

- [x] 4.1 Document the extension's user-facing workflows: initialize/open a package, refresh, add and import
      parts/assemblies/sketches/interfaces, inspect, and test. Done: new "Visual Studio Code extension" section
      in `features.rst`.
- [x] 4.2 Document AI part generation/regeneration and the "Export to …" actions, listing the supported formats
      (SVG, PNG, STEP, STL, 3MF, ThreeJS, OBJ, IGES, glTF). Done: "Generative AI" and "Export" subsections.

## 5. Refresh README files

- [x] 5.1 Update the four top-level READMEs (root, `partcad/`, `partcad-cli/`, `partcad-ide-vscode/`) to reflect
      current functionality and remove any stale/removed features. Done: created the missing
      `partcad-cli/README.md` (referenced by its `pyproject.toml`); added `IGES`/`glTF` to the root README export
      list; `partcad/README.md` and `partcad-ide-vscode/README.md` verified accurate and left as-is.
- [x] 5.2 Reconcile READMEs with `docs/source` so shared topics (installation, command names) do not disagree.
      Done: CLI README points to the new `cli.rst` reference; install instructions and command names match.
- [x] 5.3 Review `examples/README.md` and the per-example `examples/**/README.md` for accuracy (what each shows
      and how to run it); fix stale references. Done: all example READMEs use current commands
      (`pc inspect [-s|-a|-p]`, `pc supply find/quote/order --provider`), verified against live `--help`; no
      stale references found.

## 6. Prose quality pass

- [x] 6.1 Run a spell/style scan (e.g. `codespell`) plus manual review across `docs/source/*.rst` and README
      files; fix all real spelling and grammar errors (including known typos `contrinute`, `insteaf`,
      `contrbute`) while leaving valid domain terms (`build123d`, `CadQuery`, `assy`) untouched. Done: fixed
      `contrinute`, `insteaf`, `contrbute`, `witht`, `cacheing`, `requestor`; codespell now exits 0 across all
      docs and READMEs.
- [x] 6.2 Rewrite excessively complex sentences into clearer prose (active voice, one idea per sentence,
      consistent terminology) without changing meaning. Done: simplified the longest procedural run-ons in
      `use_cases.rst` and `contributing.rst`; left intentional marketing/vision voice in `index.rst` untouched.

## 7. Fix the build and verify

- [x] 7.1 Resolve every error and warning found in 1.2 (and any introduced during editing) by fixing the root
      cause (bad cross-reference, malformed directive, etc.), not by relaxing `-W`. Done: fixed a would-be
      `:ref:` failure (used `:doc:`) and an inline-literal trailing-space issue before they broke the build.
- [x] 7.2 Re-run `sphinx-build -M html docs/source docs/build -n -W` and confirm it exits with code 0 and
      produces HTML output. Done: exit 0, no warnings; `index.html` and `cli.html` produced.
- [x] 7.3 Re-run the audit checklist from section 2 to confirm every enumerated CLI and extension command is now
      documented, and confirm no known typos remain. Done: all 21 CLI groups present in `cli.rst`, all 9 export
      formats in `features.rst`, zero known typos remaining.
- [x] 7.4 Run `openspec validate up-to-date-documentation --changes up-to-date-documentation` to confirm the
      change is well-formed. Done: validation passes.
