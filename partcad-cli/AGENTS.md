# partcad-cli

CLI interface (`pc` / `partcad` commands) to most `partcad` core functionality. Source:
`./src/partcad_cli`. Tests: `./tests`. Part of the shared Poetry workspace rooted at the repo root — depends on
the `partcad` package in this monorepo (`../partcad`); run all commands below from the repo root unless noted.

`pc daemon start` / `pc daemon stop` manage the per-workspace background daemon from
[`partcad-service-json-rpc`](../partcad-service-json-rpc) (a client helper, `partcad_service_json_rpc.client`,
backs them). Migrating the rest of the CLI onto that daemon (so command bodies stop importing `partcad`) is
in-progress follow-up work.

## Setup

All commands on this page run **inside the dev container**, not on the host — see "Where commands run" in the
root [AGENTS.md](../AGENTS.md) for how to enter it. Dependencies are already installed in the image; re-run
`poetry install` only after changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix the
commands below with `poetry run` (e.g. `poetry run pytest ...`, `poetry run pc ...`).

```bash
poetry install   # from repo root; installs partcad-cli (and partcad) in editable mode
```

## Test and validate changes

Two validation steps are required for any change under `partcad-cli/` — both must pass, unit tests alone are
not sufficient because CI also gates on the example run:

1. Unit tests:

   ```bash
   pytest partcad-cli -x -p no:error-for-skips -p no:warnings --dist no   # matches CI (test-pytest job)
   ```

2. End-to-end CLI validation against the example projects (matches CI's `test-examples-partcad` job in
   `.github/workflows/test.yml`):

   ```bash
   cd examples
   pc list all -r //pub/examples/partcad
   pc test -r --package //pub/examples/partcad
   pc render -r --package //pub/examples/partcad
   ```

   If `pc`/`partcad` isn't resolvable even under `poetry run`, run the module directly instead:
   `poetry run python -m partcad_cli.click.command --no-ansi <same args>`.

## Manual CLI exercise

Under `poetry run`, the CLI is available as `pc` or `partcad`:

```bash
pc version
pc list all -r //pub/examples/partcad   # from ./examples, or any dir with a partcad.yaml
```

## Lint / format

```bash
black --check partcad-cli
flake8 partcad-cli
isort --check partcad-cli
```

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
