## ADDED Requirements

### Requirement: The dev container definition is the single source of truth for the environment
`.devcontainer/devcontainer.json` SHALL be the only authoritative definition of the development environment in
which this repository's build, test, and commit gates run. It SHALL define the container image, the dev
container features, the mounts, the environment variables required for the hooks to pass (`remoteEnv`), and the
lifecycle commands that install the git hooks. No other file, script, or documentation page SHALL restate those
values in a way that could drift from it.

#### Scenario: A tool reconstructs the environment
- **WHEN** any tool, script, or contributor reconstructs the development environment
- **THEN** it derives the image, features, mounts, environment variables, and lifecycle commands from
  `.devcontainer/devcontainer.json` rather than from hardcoded copies of those values

#### Scenario: Documentation refers to environment settings
- **WHEN** documentation needs to state the image tag, the `SKIP` hook list, or the `pre-commit install`
  invocation
- **THEN** it names `.devcontainer/devcontainer.json` as the source of that value instead of duplicating the
  value as the authoritative copy

### Requirement: The container image is pinned to an exact version
`.devcontainer/devcontainer.json` SHALL reference the container image by an exact version tag, and dev container
features SHALL be pinned by digest in `.devcontainer/devcontainer-lock.json`, so that two contributors building
the environment at different times obtain the same toolchain.

#### Scenario: Image reference is inspected
- **WHEN** a reviewer reads the `image` field of `.devcontainer/devcontainer.json`
- **THEN** it names a specific version tag (for example `ghcr.io/partcad/partcad-devcontainer:0.7.146`) and not
  a floating tag such as `latest`

#### Scenario: Features are resolved
- **WHEN** the dev container features declared in `.devcontainer/devcontainer.json` are resolved
- **THEN** `.devcontainer/devcontainer-lock.json` supplies a `resolved` digest and an `integrity` hash for each
  feature, and that lock file is committed to the repository

### Requirement: A headless entry point into the environment exists
The repository SHALL support entering the development environment without an interactive editor, so that a
coding agent or a CI job can run commands inside the same environment a VS Code user gets. This entry point
SHALL be driven by `.devcontainer/devcontainer.json` and SHALL NOT require the VS Code Dev Containers extension.

#### Scenario: An agent starts the environment from a terminal
- **WHEN** a coding agent working in a terminal needs the development environment
- **THEN** it can start the container with a documented non-interactive command
  (`npx --yes @devcontainers/cli up --workspace-folder .`) that applies the image, features, mounts, and
  lifecycle commands declared in `.devcontainer/devcontainer.json`

#### Scenario: An agent runs a command inside the environment
- **WHEN** a coding agent needs to run a build, test, lint, or git command in the environment
- **THEN** it can execute that command inside the running container with a documented non-interactive command
  (`npx --yes @devcontainers/cli exec --workspace-folder . <command>`), and the command observes the same
  toolchain, `PATH`, and environment variables as it would in the VS Code Dev Containers workflow

### Requirement: Every configured hook entry point resolves to an existing file
Every hook declared in `dev-tools/pre-commit-config.yaml` whose `entry` names a path inside this repository
SHALL point at a file that exists in the repository and is executable. A hook SHALL NOT depend on being listed
in the `SKIP` environment variable in order to avoid failing on a missing file.

#### Scenario: Hook entry points are audited
- **WHEN** a reviewer resolves each repository-relative `entry` path in `dev-tools/pre-commit-config.yaml`
  (for example `.devcontainer/pytest_hook.sh` and `.devcontainer/behave_hook.sh`)
- **THEN** every such path exists in the repository and carries the executable bit

#### Scenario: A skipped hook is un-skipped
- **WHEN** a hook is removed from the `SKIP` list declared in `.devcontainer/devcontainer.json`
- **THEN** that hook fails only because of the code being committed, never because its entry point script is
  absent from the repository

### Requirement: Commits pass their gates inside the reproducible environment
`git commit` SHALL succeed inside the reproducible environment with the configured `pre-commit` hooks running,
without requiring `--no-verify` and without requiring the contributor to disable hooks that the environment
does not already skip by design.

#### Scenario: A commit is made inside the environment
- **WHEN** a contributor or coding agent commits staged changes from inside the reproducible environment
- **THEN** the installed `pre-commit` hooks execute, and the commit is created if and only if those hooks pass

#### Scenario: A commit is attempted outside the environment
- **WHEN** `git commit` is attempted on a host that lacks the container toolchain, and the repository's git
  hooks were installed inside the container
- **THEN** the failure is attributable to the missing environment, and the documented remedy is to run the
  commit inside the reproducible environment rather than to bypass the hooks with `--no-verify`
