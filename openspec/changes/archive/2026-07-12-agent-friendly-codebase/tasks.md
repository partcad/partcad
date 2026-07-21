## 1. Research source-of-truth commands

- [x] 1.1 Extract the exact setup/build/test/lint/commit commands from `docs/source/contributing.rst`,
      `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.black]`, `[tool.flake8]`, `[tool.isort]`,
      `[tool.poetry.scripts]`), `dev-tools/pre-commit-config.yaml`, and `.github/workflows/test.yml`.
- [x] 1.2 Extract the exact setup/build/test/lint commands for `partcad-ide-vscode` from
      `partcad-ide-vscode/package.json` (`scripts`), its `nox` sessions, and `.github/workflows/npm-test.yml`.
- [x] 1.3 Extract the exact example-driven CLI validation commands from `.github/workflows/test.yml`'s
      `test-examples-partcad` job (`pc list all -r //pub/examples/partcad`,
      `pc test -r --package //pub/examples/partcad`, `pc render -r --package //pub/examples/partcad`, run from
      `./examples`) and note the `test-examples-all` job's equivalent against `//pub/examples`.

## 2. Root AGENTS.md

- [x] 2.1 Replace the placeholder "Development process" section (currently `...`) in `AGENTS.md` with a short
      command index: environment setup (`poetry install`, `poetry shell`), running tests (`pytest`, `behave`),
      linting, and the `pre-commit` requirement — plus a link to `docs/source/contributing.rst` for
      Docker/dev-container setup and PR merge-criteria detail.
- [x] 2.2 Verify `CLAUDE.md` (symlink to `AGENTS.md`) renders the updated content correctly (no separate edit
      needed since it's a symlink).

## 3. partcad/AGENTS.md

- [x] 3.1 Create `partcad/AGENTS.md` with: dependency install (`poetry install`), running unit tests
      (`pytest`, working directory, `./partcad/tests` location), linting/formatting (`black`, `flake8`,
      `isort`), and the `pre-commit` requirement before commit.
- [x] 3.2 Add the async/sync coroutine naming convention (`_async` suffix) and coordinate/location format
      (`[[x,y,z],[rx,ry,rz],angle]`) from `contributing.rst`'s "Implementation Details" section, since these
      directly constrain how an agent writes conforming core code.
- [x] 3.3 State explicitly that running `pytest` (or `poetry run pytest`) to a clean pass is the required
      validation step for any change under `partcad/`, per specs/agent-instructions/spec.md.

## 4. partcad-cli/AGENTS.md

- [x] 4.1 Create `partcad-cli/AGENTS.md` with: dependency install (shared Poetry workspace), running CLI tests
      (`pytest`, `./partcad-cli/tests` location), linting/formatting, and how the CLI package relates to and
      imports from `partcad` core.
- [x] 4.2 Document how to manually exercise CLI commands (`pc`, `partcad`) after `poetry shell`/`poetry run`.
- [x] 4.3 Document the example-driven CLI validation workflow as the required validation step for any change
      under `partcad-cli/`: `cd examples`, then run `pc list all -r //pub/examples/partcad`,
      `pc test -r --package //pub/examples/partcad`, and `pc render -r --package //pub/examples/partcad`
      (sourced from `.github/workflows/test.yml`'s `test-examples-partcad` job), noting this runs in addition
      to, not instead of, the `pytest` suite from 4.1.

## 5. partcad-ide-vscode/AGENTS.md

- [x] 5.1 Create `partcad-ide-vscode/AGENTS.md` with: npm dependency install, build/package commands
      (`nox --session setup`, `nox --session build_package`), linting (`npm run lint`), and running the LSP
      server tests (`./partcad-ide-vscode/src/test/python_tests`).
- [x] 5.2 Document how to install and manually test the built extension locally
      (`code --install-extension partcad.vsix`, restarting the PartCAD extension after core changes).

## 6. Validation

- [x] 6.1 Confirm every command written into an `AGENTS.md` file matches its source config exactly (no invented
      flags or paths) per specs/agent-instructions/spec.md.
- [x] 6.2 Confirm the root `AGENTS.md` no longer contains a bare `...` placeholder and that its three component
      links (`./partcad/AGENTS.md`, `./partcad-cli/AGENTS.md`, `./partcad-ide-vscode/AGENTS.md`) resolve to
      existing, non-empty files.
- [x] 6.3 Run `openspec validate agent-friendly-codebase` (or equivalent) to confirm the change is well-formed
      before archiving.
