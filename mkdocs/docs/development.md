# Development

## Environments

### WSL2

You can use PowerShell in order to show running environment:

```bash
wsl --list --verbose
```

You can get terminal inside WSL environment by name:

```bash
wsl -d docker-desktop
```

![WSL2 Connect](./assets/images/wsl2-connect.png)

In order to see details about processes you can install `htop`:

```bash
apk add htop
htop
```

![htop](./assets/images/wsl2-htop.png)

### VS Code

Use `remote-containers.rebuildAndReopenInContainer` aka "Dev Containers: Rebuild and Reopen in Container" to start
Docker Container with all necessary tooling and dependencies.

## Documentation

- `./docs/`: User documentation, based on Sphinx and available at <https://partcad.readthedocs.io/>

  ```bash
  cd docs
  sphinx-autobuild --host 0.0.0.0 --open-browser -b html "source" "build"
  ```

  > `--host 0.0.0.0` is required in case if you running `sphinx-autobuild` in Dev Containers and accessing HTML using
  > host browser. Docs will be served on http://127.0.0.1:8000/. There is also [`sphinx-serve`] Python module which also
  > could be used for similar functionality.

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

### Poetry

[Poetry] excels `pip` for managing Python projects because it combines dependency management, environment handling, and
project configuration into one tool, offering a streamlined workflow. It automatically resolves dependencies, uses a
`poetry.lock` for reproducibility, and supports modern standards like `pyproject.toml`. It also simplifies working with
virtual environments and distinguishes between production and development dependencies. Most frequent commands you'll
use:

- [`poetry install`] — reads the `poetry.lock` file to install the exact versions of dependencies.
- [`poetry shell ...`] — spawns a shell within the project’s virtual environment.
- [`poetry add ...`] — adds required packages to your `pyproject.toml` and installs them.

### Behavior-Driven Development (BDD)

Behavior tests are written in Gherkin language ([philosophy]) and stored in `./features` dir as `.feature` files. To run
tests, you need to use `behave` package:

```bash
poetry install --group=dev
behave
```

You can also run tests in parallel using `parallel`:

```bash
sudo apt install parallel
parallel behave ::: $(echo $(find features -type f -name '\*.feature'))
```

or use `behavex` to speedup tests execution:

- https://github.com/hrcorval/behavex
- https://github.com/hrcorval/behavex/issues/182

```bash
behavex
```

#### Available Steps

```bash
behave -f steps --dry-run --no-summary -q
behave -f steps.catalog --dry-run --no-summary -q
```

#### Environment Variables

| VARIABLE            | VALUES | DESCRIPTION                  |
| ------------------- | ------ | ---------------------------- |
| `BEHAVE_NO_CLEANUP` | [0,1]  | Do not remove temporary dirs |

#### Best Practices

- Do not use `And`, use `Given`, `When` or `Then` explicitly.
  - This will allow to avoid unexpected behavior when comment out some steps.

### Tests Generation

You can use [GitHub.copilot] to generate tests boiler plate using prompts like following:

> _Generate gherkin test for {filename}._

> _Generate gherkin test for %function% in {filename}. Add tags._

### Test Reports

- https://allurereport.org/
- https://pytest-cov.readthedocs.io/

```bash
allure serve allure-results
```

### End-to-End Testing

- https://download.virtualbox.org/virtualbox/7.0.22/VirtualBox-7.0.22-165102-Win.exe
- https://developer.hashicorp.com/vagrant/install?product_intent=vagrant

### Profiling

```bash
python -m cProfile -o pc-version.prof $(command -v pc) version
flameprof -o /tmp/pc-version.svg -r $(command -v pc) version
```

#### cProfile

You can use `cProfile` & `snakeviz` to profile CLI application, for example:

```bash
python -m cProfile -o pc-version.prof $(command -v pc) version
snakeviz pc-version.prof
```

#### yappi

```bash
python -m yappi -f callgrind --output-file=pc-version.callgrind $(command -v pc) version
gprof2dot -f callgrind -s pc-version.callgrind > pc-version.dot
dot -Tpng pc-version.dot -o pc-version.png
```

#### flameprof

```bash
flameprof -o /tmp/pc-version.svg -r $(command -v pc) version
```

#### pyprof2calltree

- https://github.com/pwaller/pyprof2calltree/

#### `print("HERE")` & `ts`

But if you really want cut to the chase... Instrument sources manually:

```python
import inspect
print("{}:{}".format(**file**, inspect.currentframe().f_lineno), flush=True)
```

Run application or script and filter output:

```bash
/usr/bin/time -v partcad version | ts -i %.S | grep -v '00.0000'
```

You will be able to get hints where to narrow the digging:

```
⬢ [Docker] ❯ partcad version | ts -i %.S | grep -v -e '00.'
07.381081 /workspaces/partcad/partcad/src/partcad/geom.py:18
01.349555 /workspaces/partcad/partcad/src/partcad/ai_ollama.py:21
03.799578 /workspaces/partcad/partcad/src/partcad/shape.py:14
04.304258 /workspaces/partcad/partcad/src/partcad/shape.py:17
03:10:51.860 INFO PartCAD version: 0.7.16
03:10:51.860 INFO PartCAD CLI version: 0.7.16
```

## Conda

You can create isolated env and install specific version of `partcad-cli` for testing:

```bash
# Leave cute environment if any
[ -n "$VIRTUAL_ENV" ] && deactivate

export TESTBED_DIR=/tmp/testbed
mkdir -pv "${TESTBED_DIR}" && cd "${TESTBED_DIR}"
conda create --yes --name testbed python=3.11
conda info --envs
conda activate testbed
# python -m venv testbed
python -m pip install partcad-cli
```

## Git

### LFS

- [Installing Git Large File Storage]
- [Installing on Linux using packagecloud]
- [Configuring Git Large File Storage]

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

### Commit Signing

- https://blog.1password.com/git-commit-signing/
- https://developer.1password.com/docs/ssh/git-commit-signing/

```ini
[safe]
	directory = /workspaces/partcad
[user]
	email = username@partcad.org
	name = First Last
```

```bash
git config user.signingkey "$(ssh-add -L)"
git config commit.gpgsign true
git config gpg.format ssh
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

> Current plan has [limit of 75 files].

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
[`sphinx-serve`]: https://pypi.org/project/sphinx-serve/
[CodeRabbit]: https://docs.coderabbit.ai/guides/commands/
[GitHub.copilot]: https://marketplace.visualstudio.com/items?itemName=GitHub.copilot
[limit of 75 files]: https://github.com/partcad/partcad/pull/219#issuecomment-2507628294
[Poetry]: https://python-poetry.org/
[philosophy]: https://behave.readthedocs.io/en/latest/philosophy/
[Installing on Linux using packagecloud]: https://github.com/git-lfs/git-lfs/blob/main/INSTALLING.md
[Installing Git Large File Storage]:
  https://docs.github.com/en/repositories/working-with-files/managing-large-files/installing-git-large-file-storage?platform=linux
[Configuring Git Large File Storage]:
  https://docs.github.com/en/repositories/working-with-files/managing-large-files/configuring-git-large-file-storage
