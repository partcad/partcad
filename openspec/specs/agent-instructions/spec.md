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
Instructions covering how to commit changes SHALL state that `pre-commit` hooks are configured
(`dev-tools/pre-commit-config.yaml`), that they are required to pass in CI, and that they are installed and run
inside the reproducible development environment defined by `.devcontainer/devcontainer.json`. The instructions
SHALL tell an agent that a `` `pre-commit` not found `` failure means the commit is being attempted outside that
environment, and that the remedy is to re-run the commit inside it rather than to bypass the hooks with
`--no-verify`.

#### Scenario: Agent prepares to commit code
- **WHEN** an agent is about to commit a change in any component of this repository
- **THEN** the relevant `AGENTS.md` (root or component-level) tells it that `pre-commit` hooks run on commit and
  must pass before a PR can merge

#### Scenario: Agent hits a missing pre-commit binary
- **WHEN** an agent runs `git commit` and the hook fails with `` `pre-commit` not found ``
- **THEN** the instructions identify this as the signature of committing outside the development environment,
  and direct the agent to re-run the commit inside the environment instead of retrying with `--no-verify`

#### Scenario: Agent is tempted to bypass hooks
- **WHEN** an agent encounters any failure originating from the commit hooks
- **THEN** the instructions state that `--no-verify` is not an acceptable workaround unless the human has
  explicitly instructed it, and that the hooks must be made to pass instead

### Requirement: Agent instructions state the headless command for entering the environment
The root `AGENTS.md` SHALL state the concrete, non-interactive commands a coding agent uses to start the
development environment and to run commands inside it, so an agent working in a terminal can reach the same
environment a VS Code user gets without consulting any other file.

#### Scenario: Agent needs to enter the environment
- **WHEN** a coding agent reads the root `AGENTS.md` to set up its environment
- **THEN** it finds the concrete `npx --yes @devcontainers/cli up --workspace-folder .` command to start the
  environment and the corresponding `npx --yes @devcontainers/cli exec --workspace-folder . <command>` form to
  run commands inside it

#### Scenario: Agent distinguishes host from container
- **WHEN** a coding agent reads a build, test, lint, or commit command in the root `AGENTS.md`
- **THEN** the instructions make clear whether that command is to be run on the host or inside the development
  environment, rather than leaving the location implicit

### Requirement: Agent instructions direct validation into the reproducible environment
Agent-facing instructions SHALL direct agents to run the repository's validation gates (`pytest`, `behave`,
lint/format) inside the reproducible development environment, so that an agent's local result matches what CI
enforces rather than depending on whatever happens to be installed on the host.

#### Scenario: Agent validates a change
- **WHEN** a coding agent has modified code and needs to validate it before committing
- **THEN** the instructions tell it to run the validation commands inside the development environment, and do
  not present host-level invocations as the primary path

### Requirement: Agent instructions document how to verify a commit succeeded
The root `AGENTS.md` SHALL tell an agent how to confirm that a commit actually landed with its hooks having
run, so the agent reports the outcome from evidence rather than from the absence of an error message.

#### Scenario: Agent confirms its commit
- **WHEN** a coding agent has run `git commit` inside the development environment
- **THEN** the instructions state how to verify the result (for example, inspecting `git log` and the hook
  output) before the agent claims the commit succeeded
