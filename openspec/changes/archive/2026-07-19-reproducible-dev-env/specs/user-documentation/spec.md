## ADDED Requirements

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
