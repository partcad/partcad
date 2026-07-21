## ADDED Requirements

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

## MODIFIED Requirements

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
