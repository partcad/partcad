## Purpose

Concise, per-component `AGENTS.md` instructions (root + `partcad` + `partcad-cli` + `partcad-ide-vscode`) that
let a coding agent set up the environment, build, test, lint, validate, and commit code using the same tools
and conventions as human contributors, kept consistent with `docs/source/contributing.rst` and the repo's
actual tooling configuration.

## Requirements

### Requirement: Root AGENTS.md has no placeholder content
The root `AGENTS.md` file SHALL NOT contain placeholder text (such as a bare `...`) in any section. Every
section SHALL contain concrete, actionable content or a link to where that content lives.

#### Scenario: Development process section is filled in
- **WHEN** an agent reads the "Development process" section of the root `AGENTS.md`
- **THEN** it finds concrete setup, build, test, lint, and commit commands or explicit links to files/docs
  containing them, and does not find a placeholder such as `...`

### Requirement: Every linked component has an AGENTS.md file
For every component the root `AGENTS.md` links to (`partcad`, `partcad-cli`, `partcad-ide-vscode`), a matching
`AGENTS.md` file SHALL exist at that component's root directory.

#### Scenario: Following a root-level component link resolves
- **WHEN** an agent follows the link to `./partcad/AGENTS.md`, `./partcad-cli/AGENTS.md`, or
  `./partcad-ide-vscode/AGENTS.md` from the root `AGENTS.md`
- **THEN** the target file exists and is non-empty

### Requirement: Component AGENTS.md covers environment setup, build, test, and lint
Each component `AGENTS.md` (`partcad`, `partcad-cli`, `partcad-ide-vscode`) SHALL document, at minimum: how to
install dependencies for that component, how to run its automated tests, and how to run its linter/formatter,
using commands that are runnable as written from that component's directory (or the repo root, if stated).

#### Scenario: Agent locates the test command for a component
- **WHEN** an agent needs to run tests for `partcad`, `partcad-cli`, or `partcad-ide-vscode`
- **THEN** the component's `AGENTS.md` states a concrete command (e.g. `pytest`, `poetry run pytest`, or
  `npm test`) that an agent can execute without consulting any other file

#### Scenario: Agent locates the lint command for a component
- **WHEN** an agent needs to lint or format code it wrote in `partcad`, `partcad-cli`, or `partcad-ide-vscode`
- **THEN** the component's `AGENTS.md` states a concrete lint/format command (e.g. `black`, `flake8`, `isort`,
  or `npm run lint`) matching what `pyproject.toml` or `partcad-ide-vscode/package.json` actually configures

### Requirement: Instructions stay consistent with existing tooling configuration
Every command stated in an `AGENTS.md` file SHALL match a command, script, or hook actually defined in this
repository's configuration (`pyproject.toml`, `dev-tools/pre-commit-config.yaml`, `.github/workflows/*.yml`, or
`partcad-ide-vscode/package.json`), so instructions do not go stale relative to the tooling they describe.

#### Scenario: A stated test command matches the real test configuration
- **WHEN** an `AGENTS.md` file states a command for running tests
- **THEN** that command corresponds to what `pyproject.toml`'s `[tool.pytest.ini_options]` /
  `[tool.poetry.scripts]`, or `partcad-ide-vscode/package.json`'s `scripts`, actually define for that component

### Requirement: partcad/AGENTS.md documents pytest-based validation
`partcad/AGENTS.md` SHALL instruct an agent to validate any change to the core module by running the `pytest`
suite to a clean pass, stating the concrete command, so agents treat `pytest` as the required validation gate
for core changes rather than an optional check.

#### Scenario: Agent validates a core-module change
- **WHEN** an agent has modified code under `partcad/`
- **THEN** `partcad/AGENTS.md` tells it to run `pytest` (or `poetry run pytest`) and treat a clean run as the
  required validation signal before considering the change complete

### Requirement: partcad-cli/AGENTS.md documents example-based CLI validation
`partcad-cli/AGENTS.md` SHALL instruct an agent to validate any change to the CLI by running the relevant `pc`/
`partcad` CLI commands against the example projects under `./examples`, matching the commands CI runs in
`.github/workflows/test.yml`'s `test-examples-partcad`/`test-examples-all` jobs (`list`, `test`, `render`), in
addition to the CLI's `pytest` suite.

#### Scenario: Agent validates a CLI change
- **WHEN** an agent has modified code under `partcad-cli/`
- **THEN** `partcad-cli/AGENTS.md` tells it to `cd examples` and run commands such as
  `pc list all -r //pub/examples/partcad`, `pc test -r --package //pub/examples/partcad`, and
  `pc render -r --package //pub/examples/partcad` as a required end-to-end validation step, not only unit tests

### Requirement: Commit workflow instructions reference pre-commit hooks
Instructions covering how to commit changes SHALL mention that `pre-commit` hooks are configured
(`dev-tools/pre-commit-config.yaml`) and are required to pass in CI, so an agent does not bypass or ignore them
by default.

#### Scenario: Agent prepares to commit code
- **WHEN** an agent is about to commit a change in any component of this repository
- **THEN** the relevant `AGENTS.md` (root or component-level) tells it that `pre-commit` hooks run on commit and
  must pass before a PR can merge
