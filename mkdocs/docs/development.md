# Development

## Documentation

- `./docs/`: user documentation, based on Sphinx and available at <https://partcad.readthedocs.io/>.
- `./mkdocs/`: developer's handbook, based on [`mkdocs-material`][10].

You can serve `mkdocs` docs locally with realtime updates:

```bash
poetry install --group=docs
cd mkdocs
poetry run mkdocs serve
```

## Host Dependencies

- `shellcheck`: used by [`pre-commit`][6]
- `bash-completion`: used by [`click`][7]
- `cmake`, `libcairo2-dev`, `pkg-config` `python3-dev`: used by [`pycairo`][5]
  - `ffmpeg`, `libsm6`, `libxext6`: those probably as well
- `openscad`, `pypy3`, `pypy3-dev`: used by PartCAD
- `graphviz`: was used by `gprof2dot`
- `pipx`: used by [`poetry-plugin-export`][8]
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

Wheels in [`cadquery-ocp v7.7.2`][9] require glibc to be v2.35 or newer:

```
Skipping wheel cadquery_ocp-7.7.2-cp310-cp310-manylinux_2_35_x86_64.whl as this is not supported by the current environment
```

## Python

Current base version of Python is 3.10. Environment variable for packages configurations could be set in `.env` file.

## Poetry

[Poetry][1] excels `pip` for managing Python projects because it combines dependency management, environment handling,
and project configuration into one tool, offering a streamlined workflow. It automatically resolves dependencies, uses a
`poetry.lock` for reproducibility, and supports modern standards like `pyproject.toml`. It also simplifies working with
virtual environments and distinguishes between production and development dependencies. Most frequent commands you'll
use:

- [`poetry install`][3] — reads the `poetry.lock` file to install the exact versions of dependencies.
- [`poetry shell ...`][2] — spawns a shell within the project’s virtual environment.
- [`poetry add ...`][4] — adds required packages to your `pyproject.toml` and installs them.

## Git

### Hooks

We use the [`pre-commit`][6] tool to ensure consistent code quality and adherence to coding standards by automatically
running checks on code before it is committed to a repository. It helps catch issues like syntax errors, formatting
inconsistencies, and potential bugs early in the development process, reducing the need for manual review and minimizing
errors in production. By automating these checks, [`pre-commit`][6] streamlines the development workflow, enforces best
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

Most CI builds are designed to run within the Dev Container, ensuring consistency between the CI environment and the
development environment. To expedite job execution, a PR-specific Docker Image cache is utilized and stored under tags
`PR-XXX` at:

- <https://ghcr.io/partcad/partcad-devcontainer>

#### CodeRabbit Commands (Invoked using PR comments)

[CodeRabbit][11] is an AI-powered code reviewer that delivers context-aware feedback on pull requests within minutes,
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

[1]: https://python-poetry.org/
[2]: https://python-poetry.org/docs/cli#shell
[3]: https://python-poetry.org/docs/cli#install
[4]: https://python-poetry.org/docs/cli#add
[5]: https://pypi.org/project/pycairo/
[6]: https://pypi.org/project/pre-commit/
[7]: https://pypi.org/project/click/
[8]: https://pypi.org/project/poetry-plugin-export/
[9]: https://pypi.org/project/cadquery-ocp/
[10]: https://squidfunk.github.io/mkdocs-material/
[11]: https://docs.coderabbit.ai/guides/commands/
