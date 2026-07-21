## Purpose

Accuracy, completeness, buildability, and writing quality of PartCAD's user-facing documentation
(`docs/source/*.rst` and all `README.md` files): every user-visible CLI command and VS Code extension feature is
documented, the documented surface matches the software that ships, the Sphinx site builds with no errors or
warnings, and the prose is free of typos, grammar mistakes, and needlessly complex sentences.

## Requirements

### Requirement: Every user-facing CLI command is documented
The documentation SHALL describe every user-facing `pc`/`partcad` CLI command group and subcommand that exists
under `partcad-cli/src/partcad_cli/click/commands/`, including at minimum its purpose and its primary options.
No user-invocable command group SHALL be absent from the documentation.

#### Scenario: A command group present in the CLI is present in the docs
- **WHEN** a reviewer lists the top-level command groups exposed by `pc --help` (e.g. `add`, `ai`, `adhoc`,
  `config`, `convert`, `export`, `healthcheck`, `import`, `info`, `init`, `inspect`, `install`, `lint`, `list`,
  `render`, `search`, `supply`, `system`, `test`, `update`, `version`)
- **THEN** each of those command groups is described in `docs/source` (in a command reference or a relevant
  workflow/feature page)

#### Scenario: A previously undocumented group is covered
- **WHEN** a reviewer looks for the `search`, `ai`, `adhoc`, `lint`, `config`, `convert`, `export`,
  `healthcheck`, `import`, `install`, `test`, or `update` commands in the documentation
- **THEN** each has at least a description of what it does and how to invoke it, rather than zero mentions

### Requirement: The documented CLI surface matches the actual CLI
Any place in the documentation that reproduces CLI output or a command list (such as the `pc --help` block in
`docs/source/installation.rst`) SHALL match the CLI's current top-level commands and their current names, so the
documentation does not present removed, renamed, or missing commands as current.

#### Scenario: Reproduced help output is current
- **WHEN** the documentation shows a `pc --help` command listing
- **THEN** the listed commands and names match the current CLI (for example, the current `system status` is not
  shown as a top-level `status`, and no top-level group shown in `pc --help` is missing from the block)

### Requirement: Every user-facing VS Code extension command is documented
The documentation SHALL describe the user-facing commands the VS Code extension contributes
(`partcad-ide-vscode/package.json` → `contributes.commands`), covering package initialization/opening, adding
and importing parts/assemblies/sketches/interfaces, inspecting and testing, AI part generation/regeneration, and
exporting to the supported file formats.

#### Scenario: Extension export actions are documented
- **WHEN** a reviewer checks whether the extension's "Export to …" actions (SVG, PNG, STEP, STL, 3MF, ThreeJS,
  OBJ, IGES, glTF) are described
- **THEN** the documentation lists the supported export formats available from the extension

#### Scenario: Core extension workflows are documented
- **WHEN** a reviewer looks for how to initialize/open a package, add or import an object, and inspect or test it
  from the extension
- **THEN** each of these workflows is described in the documentation

### Requirement: README files reflect current functionality and agree with the docs
Every tracked `README.md` (repository root, `partcad/`, `partcad-cli/`, `partcad-ide-vscode/`, `examples/` and
its per-example READMEs) SHALL describe the current functionality of its component and SHALL NOT contradict
`docs/source`.

#### Scenario: Component README describes current behavior
- **WHEN** a reviewer reads the root, `partcad/`, `partcad-cli/`, or `partcad-ide-vscode` `README.md`
- **THEN** it describes functionality that currently exists and does not reference removed commands or features

#### Scenario: README and docs do not disagree
- **WHEN** a topic (such as installation or a command name) appears in both a `README.md` and `docs/source`
- **THEN** the two describe it consistently

### Requirement: Documentation builds to HTML with no errors or warnings
The `docs/source` tree SHALL render to HTML with no errors and no warnings using the project's documented build
command from `docs/source/contributing.rst`: `sphinx-build -M html docs/source docs/build -n -W` (the `-W` flag
turns warnings into errors, so any warning fails the build).

#### Scenario: Warnings-as-errors build succeeds
- **WHEN** `sphinx-build -M html docs/source docs/build -n -W` is run in the project's documentation environment
- **THEN** the command exits successfully with a zero exit code and produces HTML output

### Requirement: Documentation prose is well written
The documentation SHALL follow standard technical-writing practices: it SHALL be free of spelling and grammar
mistakes and SHALL avoid excessively complex sentences (preferring one idea per sentence, active voice, and
consistent terminology).

#### Scenario: Known typos are removed
- **WHEN** a reviewer searches the documentation for the misspellings currently present (for example
  `contrinute`, `insteaf`, `contrbute`)
- **THEN** none are found, and no new spelling errors are introduced

#### Scenario: Overly complex sentences are simplified
- **WHEN** a reviewer encounters a sentence that packs multiple clauses or ideas together to the point of being
  hard to follow
- **THEN** it has been rewritten into clearer, simpler sentences without losing meaning

### Requirement: Contributing documentation covers the CLI-based dev container workflow
`docs/source/contributing.rst` SHALL document how to start and use the development environment via the
`@devcontainers/cli` command line tool, as an alternative to the VS Code Dev Containers extension, so that
contributors who do not use VS Code — and automated agents — have a supported path to the same environment.

#### Scenario: A contributor without VS Code sets up the environment
- **WHEN** a contributor who does not use VS Code reads `docs/source/contributing.rst`
- **THEN** they find the concrete commands to start the development environment and to run commands inside it
  from a terminal, alongside the existing VS Code Dev Containers instructions

#### Scenario: A contributor commits from the terminal
- **WHEN** a contributor following the CLI-based workflow is ready to commit
- **THEN** the documentation states that `git commit` must be run inside the development environment for the
  `pre-commit` hooks to be available, and explains the `` `pre-commit` not found `` failure that results from
  committing on the host
