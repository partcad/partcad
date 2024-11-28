# Development

## Documentation

- `./docs/`: User documentation, based on Sphinx and available at <https://partcad.readthedocs.io/>

  ```bash
  cd docs
  sphinx-autobuild --host 0.0.0.0 --open-browser -b html "source" "build"
  ```

  > `--host 0.0.0.0` is required in case if you running `sphinx-autobuild` in Dev Containers and accessing HTML using
  > host browser. Docs will be served on http://127.0.0.1:8000/

- `./mkdocs/`: Developer's handbook, based on [`mkdocs-material`] You can serve `mkdocs` docs locally with realtime
  updates:
  ```bash
  poetry install --group=docs
  cd mkdocs
  poetry run mkdocs serve
  ```
  > Docs will be served on http://127.0.0.1:8000/partcad/partcad/

## Host Dependencies

- `shellcheck`: used by [`pre-commit`]
- `bash-completion`: used by [`click`]
- `cmake`, `libcairo2-dev`, `pkg-config` `python3-dev`: used by [`pycairo`]
  - `ffmpeg`, `libsm6`, `libxext6`: those probably as well
- `openscad`, `pypy3`, `pypy3-dev`: used by PartCAD
- `graphviz`: was used by `gprof2dot`
- `pipx`: used by [`poetry-plugin-export`]
- `time`, `moreutils`: used in terminal for troubleshooting

Dependencies are listed in `.devcontainer/apt.in`. You can install them:

```bash
cd .devcontainer
sudo apt install $(cat apt.txt)
```

And also you can update them:

```bash
cd .devcontainer
sudo apt install --upgrade $(cat apt.in)
sudo ./apt-compile.sh
```

## Limitations

### glibc 2.35+

Wheels in [`cadquery-ocp`] v7.7.2 require glibc to be v2.35 or newer:

```
Skipping wheel cadquery_ocp-7.7.2-cp310-cp310-manylinux_2_35_x86_64.whl as this is not supported by the current environment
```

## Python

Current base version of Python is 3.10. Environment variable for packages configurations could be set in `.env` file.

## Poetry

[Poetry] excels `pip` for managing Python projects because it combines dependency management, environment handling, and
project configuration into one tool, offering a streamlined workflow. It automatically resolves dependencies, uses a
`poetry.lock` for reproducibility, and supports modern standards like `pyproject.toml`. It also simplifies working with
virtual environments and distinguishes between production and development dependencies. Most frequent commands you'll
use:

- [`poetry install`] — reads the `poetry.lock` file to install the exact versions of dependencies.
- [`poetry shell ...`] — spawns a shell within the project’s virtual environment.
- [`poetry add ...`] — adds required packages to your `pyproject.toml` and installs them.

## Git

### Hooks

We use the [`pre-commit`] tool to ensure consistent code quality and adherence to coding standards by automatically
running checks on code before it is committed to a repository. It helps catch issues like syntax errors, formatting
inconsistencies, and potential bugs early in the development process, reducing the need for manual review and minimizing
errors in production. By automating these checks, [`pre-commit`] streamlines the development workflow, enforces best
practices, and ensures that every commit meets predefined quality standards, fostering cleaner and more maintainable
codebases. Those hooks are automatically installed in Dev Container:

```
Running Installing pre-commit hooks from devcontainer.json...
pre-commit installed at .git/hooks/pre-commit
```

You also can install them manually:

```bash
pre-commit install
```

### GitHub

#### Actions & Workflows

Some GitHub Actions are relying on Dev Container for managing the environment, ensuring consistency between the CI
environment and the development environment. To expedite job execution, a PR-specific Docker image cache is utilized
with the following specifications:

- Tag format: `PR-XXX` (where XXX is the PR number)
- Cache location: GitHub Container Registry (ghcr.io)
- Full path: <https://ghcr.io/partcad/partcad-devcontainer>

#### CodeRabbit Commands (Invoked using PR comments)

[CodeRabbit] is an AI-powered code reviewer that delivers context-aware feedback on pull requests within minutes,
streamlining the code review process.

It provides valuable insights and identifies issues that are often missed, enhancing the overall review quality. You can
use the following commands on PRs to interact with it:

**Review Commands:**

- `@coderabbitai summary` - Generates a fresh PR summary.
- `@coderabbitai review` - Initiates an incremental review of new changes only (useful for repos with disabled
  auto-reviews).
- `@coderabbitai full review` - Performs a comprehensive review of all files, regardless of previous reviews.

**Review Flow Control:**

- `@coderabbitai pause` - Temporarily halts PR reviews.
- `@coderabbitai resume` - Continues previously paused reviews.

**Management Commands:**

- `@coderabbitai resolve` - Resolves all the CodeRabbit review comments.
- `@coderabbitai configuration` - Displays the current CodeRabbit configuration for the repository.

**Help:**

- `@coderabbitai help` - Displays available commands and usage information.

[`cadquery-ocp`]: https://pypi.org/project/cadquery-ocp/
[`click`]: https://pypi.org/project/click/
[`mkdocs-material`]: https://squidfunk.github.io/mkdocs-material/
[`poetry add ...`]: https://python-poetry.org/docs/cli#add
[`poetry install`]: https://python-poetry.org/docs/cli#install
[`poetry shell ...`]: https://python-poetry.org/docs/cli#shell
[`poetry-plugin-export`]: https://pypi.org/project/poetry-plugin-export/
[`pre-commit`]: https://pypi.org/project/pre-commit/
[`pycairo`]: https://pypi.org/project/pycairo/
[CodeRabbit]: https://docs.coderabbit.ai/guides/commands/
[Poetry]: https://python-poetry.org/
