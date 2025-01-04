---
tags:
  - Tutorials
---

# Quick Start

!!! info

    Following tutorial assumes that you have previous experience with both [VS Code] and [Docker] or have read
    [Environment] first.

Overall process starting from setting up environment till merging changes in default branch is the following:

1. Clone Git Repository.
2. Install Python Dependencies.
3. Activate Virtual Environment.
4. Make Changes in Source Files.
5. Run Tests.
6. Commit & Push Changes.
7. Open Pull Request.
8. Meet PR Merge Criteria.

## Clone Git Repository

Due to differences in Docker setup on Linux vs other system this step has different best practicies. Please follow
section for your OS below, and once you have cloned repository VS Code will start Dev Container.

Current size of base Docker Image with all system level dependencies baked-in is 2.83 GB, main highlights are:

- Debian Bookwork: 116.56 Mb
- Common Utils: 251.11 Mb
- Git: 423.87 Mb
- APT Packages: 770.56 Mb
- Python: 411.28 Mb

### Mac & Windows

!!! warning

    Since macOS and Windows run containers in a VM, "[bind]" mounts are not as fast as using the container's filesystem
    directly. Fortunately, Docker has the concept of a local "[named volume]" that can act like the container's
    filesystem but survives container rebuilds. This makes it ideal for storing package folders like `node_modules`,
    data folders, or output folders like `build` where write performance is critical.

In order to have optimal performance use the following documentation, but when prompted to provide GitHub repository
name use `partcad/partcad` to clone our main repository:

- [Quick start: Open a Git repository or GitHub PR in an isolated container volume]

### Linux

Since Linux can run Docker Engine directly on your host system, you can use the following documentation to bootstrap
environment.

- [Quick start: Open an existing folder in a container]

## Install Dependencies

We are using [Poetry] to manage dependencies and virtual environments.

!!! info

    Poetry is a tool for dependency management and packaging in Python. It allows you to declare the libraries your
    project depends on and it will manage (install/update) them for you. Poetry offers a lockfile to ensure repeatable
    installs, and can build your project for distribution.

Once Dev Container is started you will be able to open terminal, with current working directory at `/workspaces/partcad`
containing source files. In order to install Python packages you have to run the following:

```bash
$ poetry install
```

It will create virtual environment in `.venv/` directory and download about 1.6G dependencies. Once all dependencies are
downloaded Poetry will also install current package in editable mode, and you will see the following:

```text
Installing the current project: partcad-dev (0.1.0)
```

## Activate Environment

In order to update your `$PATH` and be able to run commandline tools such as `pytest` you need to activate virtual
environment:

```bash
poetry shell
```

After that you will be able to run `pc`, for example `pc version`, which will output something along the lines:

```text
INFO:  PartCAD Python Module version: 0.7.40
INFO:  PartCAD CLI version: 0.7.40
```

## Make Changes

Make necessary updates, for example in current Quick Start editing `docs/mkdocs/docs/development/quick-start.md`

## Run Tests

We are using both Unit and Functional testing with main tools being [pytest] & [Behave]:

!!! quote

    The `pytest` framework makes it easy to write small, readable tests, and can scale to support complex functional
    testing for applications and libraries.

!!! quote

    `behave` uses tests written in a natural language style, backed up by Python code.

### pytest

If you [activated virtual environment] you can just run `pytest` from terminal.

You also can use built-in **Testing** integration to be able to run and debug tests via VS Code UI, but for that you
will have to select correct Python Interpreter first by running `Python: Select Interpreter` from Command Palette and
point it to `('.venv': Poetry) .venv/bin/python`.

You also can run `pytest` without activating environment via Poetry, for example:

```bash
$ poetry run pytest
```

### Behave

## Commit & Push Changes

You can commit changes from either terminal or VS Code UI which will trigger local git hooks managed by `pre-commit` to
enforce coding standards and catch some of the problems early.

### pre-commit

!!! quote

    [pre-commit] is a framework for managing and maintaining multi-language pre-commit hooks.

Configuration file is located at `.devcontainer/.pre-commit-config.yaml` were you can see all supported hooks.

!!! info

    In rare cases you might have to [temporarily disable hooks] but remember this they also run in CI and required to
    pass before PR could be merged. This will allow you to skip individual hooks.

    Another option is [git commit --no-verify] which will skip all hooks at once.

## Open Pull Request

There are multiple options how PR could be opened, please refer to the following to choose option which works best for
you.

- [Creating a pull request]
- [GitHub Pull Requests in Visual Studio Code]

## Meet PR Merge Criteria

Depending on files changed in PR you might need to get required checks to pass first and get reviews from owners or
maintainers, following are related GH docs:

- [About Status Checks]
- [Required reviews]

[Quick start: Open a Git repository or GitHub PR in an isolated container volume]:
  https://code.visualstudio.com/docs/devcontainers/containers#_quick-start-open-a-git-repository-or-github-pr-in-an-isolated-container-volume
[Quick start: Open an existing folder in a container]:
  https://code.visualstudio.com/docs/devcontainers/containers#_quick-start-open-an-existing-folder-in-a-container
[named volume]: https://docs.docker.com/engine/storage/volumes/
[bind]: https://docs.docker.com/engine/storage/bind-mounts/
[VS Code]: environment.md#visual-studio-code
[Docker]: environment.md#docker
[Environment]: environment.md
[Poetry]: https://python-poetry.org/docs/
[activated virtual environment]: #activate-environment
[pytest]: https://docs.pytest.org/en/stable/
[Behave]: https://behave.readthedocs.io/en/latest/
[pre-commit]: https://pre-commit.com/
[temporarily disable hooks]: https://pre-commit.com/#temporarily-disabling-hooks
[git commit --no-verify]: https://git-scm.com/book/fa/v2/Customizing-Git-Git-Hooks#_committing_workflow_hooks
[gh pr create]: https://cli.github.com/manual/gh_pr_create
[Creating a pull request]:
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
[GitHub Pull Requests in Visual Studio Code]:
  https://code.visualstudio.com/blogs/2018/09/10/introducing-github-pullrequests
[Merging a pull request]:
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request
[About Status Checks]:
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks#checks
[Required reviews]:
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews
