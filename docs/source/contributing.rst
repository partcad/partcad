Contributing
############

Everyone can contribute to the development of PartCAD,
which lowers the entry barrier to the design and manufacturing world
and speeds up innovation for humanity.

Find below some of the ways to contribute.

*****************
Why contributing?
*****************

By improving PartCAD itself, you can improve the framework and platform
capabilities for all of its users, no matter whether they are using public
packages or working on hermetic private repositories.

*******************
What to contribute?
*******************

Ideas and Feedback
==================

Share your ideas and feedback using
`PartCAD's Discord server <https://discord.gg/h5qhbHtygj>`_.

Develop Features
================

All PartCAD software components are present in
`the PartCAD's main Github repository <https://github.com/partcad/partcad/>`_.
All pull requests are welcome.

If you need help deciding what could be the best project for you to work on,
engage with the community on
`PartCAD's Discord server <https://discord.gg/h5qhbHtygj>`_

Spread The Word
===============

You can make a huge impact on lots of people by simply creating a simple post
or a basic video tutorial for PartCAD in your social media accounts.
It is very much appreciated.

PartCAD Public Repository
=========================

Besides main PartCAD software components, you can contribute to the community by publishing design data
as well as pluggable software modules to PartCAD Public Repository.

Assemblies
----------

Migrate your products to PartCAD by creating and publishing Assembly YAML files
for your products. Eliminate the need to develop and maintain a custom way to
store and to publish assembly instructions and bills of materials.
Enable the use or your assemblies in other PartCAD projects.

Start by creating a package (in a dedicated git repository)
for all products by your company or community.
Then add parametrized assembly declarations to the package.

The best way to write Assembly YAML files is to use the PartCAD VS Code extension
and its code completion features. Select the part you want to add in the explorer
view on the left. Then, in the Assembly YAML file editor, start typing ``- part:``
(including the trailing space) as if you were adding a new part to the assembly.
After you type ``- pa``, a code
completion suggestion appears that adds the complete YAML block for the selected
part.

Parts
-----

Publish your parts in the PartCAD Public Repository to enable their use (and
purchase if applicable) by other PartCAD users.

Start by creating a package (in a dedicated git repository)
for all parts and assemblies created by your company
or community, if you didn't do that yet.
Then add part declarations to the package.

If CAD files already exist for these parts, then you should probably start by
using those CAD files first. You can always migrate to Code-CAD technologies
(such as OpenSCAD, CadQuery, build123d or sdf) later. However you might want to host
the CAD files separately from the package's git repository
(and have PartCAD fetch them using `fileFrom: url`,
even if they are hosted in another git repository)
so that you do not blow up the repository size and
slow your projects down in perpetuity by a temporary use of legacy CAD files.

After that declare the location of ports.
This will enable connecting parts to each other, instead of placing them using
absolute and relative coordinates and ensuring they remain properly co-located
using finger-crossing guarantees.
Whenever possible, use interfaces and mating declarations instead of pure ports,
so that it's easier for PartCAD (including AIs using PartCAD) to determine
which parts are meant to be connected to which parts, and how exactly they need
to be connected.

Interfaces
----------

The most challenging step of adding parts is to declare all the ports.
This effort can be significantly reduced for all PartCAD users globally
by extending the library of standard interfaces.

Does your part have a port of the kind also found in many other parts?
Consider declaring a reusable interface.

Providers
---------

Advertise your online store and manufacturing services by integrating your API
with PartCAD.

Decide which one is more appropriate for your business:
``store`` or ``manufacturer``. Then see an existing provider implementation of
that kind as a reference. Alternatively, reach out to the PartCAD team to get
help with the implementation. Be at the forefront of the next industrial
revolution together with PartCAD!

Help a Friend
-------------

Do you know an opensource project that maintains assembly instructions or doing
something else that can be radically improved by using PartCAD?
Do you know a business that uses legacy tools and struggles to scale
collaboration in the era of Git?
Do you know a local additive manufacturing shop that can use more local
customers?
Do you know a collection of parts that the community can really benefit from if
only these parts and corresponding assembly ideas were easily discoverable?

Help them migrate to PartCAD!

******************
How to contribute?
******************

.. _Environment:

Environment
===========

Our team is using `Visual Studio Code`_ and `Docker`_ which boosts
software development by providing a powerful, customizable editor and ensuring consistent environments with
containerization.

VS Code's rich extensions and debugging tools integrate seamlessly with Docker, allowing developers to write, test, and
debug code within containers.

This setup eliminates environment inconsistencies, accelerates development, and improves team collaboration.

Docker
------

`Docker`_ helps build, share, run, and verify applications anywhere — without tedious environment configuration or
management. There are two main options how to setup Docker.

If you do not have previous experience with Docker, then here is good place to start:

- `Docker Docs - Get Started`_

Engine
------

If your primary development system is Linux then you can install Docker daemon directly on your host, see `Install`_ for
more details on how to install it in the distribution you're using. Minimum required versions:

- Docker Engine: v27.4.0 or higher
- Docker Desktop for Mac/Windows: 4.37.1 or higher

.. note::

    *`Docker Engine`_ is an open source containerization technology for building and containerizing your applications.
    Docker Engine acts as a client-server application with:*

    - A server with a long-running daemon process `dockerd`_.
    - APIs which specify interfaces that programs can use to talk to and instruct the Docker daemon.
    - A command line interface (CLI) client `Docker`_.

    The CLI uses `Docker APIs`_ to control or interact with the Docker daemon through scripting or direct CLI commands.
    Many other Docker applications use the underlying API and CLI. The daemon creates and manages Docker objects, such as
    images, containers, networks, and volumes.

    For more details, see `Docker Architecture`_.

Desktop
-------

If you're working on macOS or Windows, you can still install Engine, but that would require managing a local Linux VM.
Docker Desktop provides a convenient solution and handles the required virtualization for you:

- `Install on Mac`_
- `Install on Windows`_

.. note::

    *`Docker Desktop` is a one-click-install application for your Mac, Linux, or Windows environment that lets you build,
    share, and run containerized applications and microservices.*

.. image:: images/docker-for-desktop.png
  :width: 80%
  :align: center
  :alt: A screenshot of Docker Desktop's user interface, showing the "Containers" tab.

Visual Studio Code
==================

VS Code available for macOS, Linux, and Windows, has extensible architecture and has rich customization and integration
options. Here is good place to get familiar with it:

- `Setting up Visual Studio Code`_

.. note::

    *Visual Studio Code combines the simplicity of a source code editor with powerful developer tooling, like IntelliSense
    code completion and debugging.*

    *First and foremost, it is an editor that gets out of your way. The delightfully frictionless edit-build-debug cycle
    means less time fiddling with your environment, and more time executing on your ideas.*

.. image:: images/vs-code-behave.png
  :width: 80%
  :align: center
  :alt: A screenshot of a Visual Studio Code environment. The terminal window shows a behave command being executed to test BDD (Behavior-Driven Development) scenarios for a PartCAD project.

Dev Containers
--------------

VS Code also provides seamless integration with Docker for managing environments by supporting `Dev Containers`_
specification.

.. note::

    _The Visual Studio Code Dev Containers extension lets you use a container as a full-featured development environment.
    It allows you to open any folder inside (or mounted into) a container and take advantage of Visual Studio Code's full
    feature set. A `devcontainer.json`_ file in your project tells VS Code how to access (or create) a development
    container with a well-defined tool and runtime stack. This container can be used to run an application or to separate
    tools, libraries, or runtimes needed for working with a codebase._

Following docs section provides good overview of available features:

- `Developing inside a Container`_

.. _Visual Studio Code: https://code.visualstudio.com/
.. _Dev Containers: https://containers.dev/
.. _Install on Mac: https://docs.docker.com/desktop/setup/install/mac-install/
.. _Install on Windows: https://docs.docker.com/desktop/setup/install/windows-install/
.. _Install: https://docs.docker.com/engine/install/
.. _Docker Architecture: https://docs.docker.com/get-started/docker-overview/#docker-architecture
.. _Docker APIs: https://docs.docker.com/reference/api/engine/
.. _dockerd: https://docs.docker.com/reference/cli/dockerd
.. _Docker Desktop: https://docs.docker.com/desktop/
.. _Docker Docs - Get Started: https://docs.docker.com/get-started/
.. _Docker Engine: https://docs.docker.com/engine/
.. _Setting up Visual Studio Code: https://code.visualstudio.com/docs/setup/setup-overview
.. _devcontainer.json: https://code.visualstudio.com/docs/devcontainers/containers#_create-a-devcontainerjson-file
.. _Developing inside a Container: https://code.visualstudio.com/docs/devcontainers/containers

Quick Start
===========

.. note::

  Following tutorial assumes that you have previous experience with both `VS Code`_ and `Docker`_ or have read
  `Environment`_ first.

Overall process starting from setting up environment till merging changes in default branch is the following:

1. Clone Git Repository.
2. Install Python Dependencies.
3. Activate Virtual Environment.
4. Make Changes in Source Files.
5. Run Tests.
6. Commit & Push Changes.
7. Open Pull Request.
8. Meet PR Merge Criteria.

Retrieve the Source Code
------------------------

Due to variations in Docker setup across operating systems, this step has distinct best practices. Please follow the
section for your OS below. Once you have cloned the repository, VS Code will start the Dev Container.

The last time we've measured, the size of base Docker Image with all system-level dependencies baked in is 2.83 GB, main highlights are:

- APT Packages: 770.56 MB
- Git: 423.87 MB
- Python: 411.28 MB
- Common Utils: 251.11 MB
- Debian (Bookworm): 116.56 MB

Mac & Windows
^^^^^^^^^^^^^

  .. warning::

    Since macOS and Windows run containers in a VM, "`bind`_" mounts are not as fast as using the container's filesystem
    directly. Fortunately, Docker has the concept of a local "`named volume`_" that can act like the container's
    filesystem but survives container rebuilds. This makes it ideal for storing package folders like ``node_modules``,
    data folders, or output folders like ``build`` where write performance is critical.

  In order to have optimal performance use the following documentation, but when prompted to provide GitHub repository
  name use ``partcad/partcad`` to clone our main repository:

  - `Open a Git repository or GitHub PR in an isolated container volume`_

Linux
^^^^^

  Since Linux can run Docker Engine directly on your host system, you can use the following documentation to bootstrap
  environment.

  - `Open an existing folder in a container`_

Without VS Code: Dev Containers CLI
-----------------------------------

If you do not use VS Code — or you are automating the workflow, for example from a coding agent — you can enter the same
environment from a terminal with the `Dev Containers CLI`_. It reads the same ``.devcontainer/devcontainer.json``, so
you get the same image, features, mounts, and lifecycle commands the VS Code extension would give you.

Start the environment from the repository root on your host. The first run is slow while features are installed:

.. code-block:: bash

  $ npx --yes @devcontainers/cli up --workspace-folder .

Then run any command inside it:

.. code-block:: bash

  $ npx --yes @devcontainers/cli exec --workspace-folder . <command>

The project virtual environment is not activated automatically and ``pytest``, ``pc``, and ``partcad`` are not on
``$PATH``, so prefix project commands with ``poetry run``:

.. code-block:: bash

  $ npx --yes @devcontainers/cli exec --workspace-folder . poetry run pc version

.. note::

  ``poetry.toml`` sets ``in-project = true``, so the virtual environment lives at ``./.venv`` inside the bind-mounted
  workspace and is shared between your host and the container. If you run ``poetry`` on both sides, each will rebuild
  ``.venv`` because the interpreter paths recorded in it are only valid on one side. Keep Python work on one side.

Committing from the CLI
^^^^^^^^^^^^^^^^^^^^^^^

Run ``git commit`` **inside** the environment. That is where ``pre-commit`` is installed, by the ``postStartCommand``
declared in ``.devcontainer/devcontainer.json``:

.. code-block:: bash

  $ npx --yes @devcontainers/cli exec --workspace-folder . git commit -m "<message>"

If you commit on the host instead, the commit fails with ``` `pre-commit` not found ```. The ``.git/hooks/pre-commit``
script is generated by ``pre-commit install`` running inside the container, so it refers to an interpreter path that
only exists there. Re-run the commit inside the environment rather than bypassing the hooks with ``--no-verify``.

The VS Code extension copies your host git identity into the container, but the CLI does not, and anything written to
the container's home directory is lost when the container is recreated. If the commit fails with ``Author identity
unknown``, set the identity repo-locally — ``.git/config`` lives in the bind-mounted workspace, so it survives
container recreates and is never committed:

.. code-block:: bash

  $ git config --local user.name "<your name>"
  $ git config --local user.email "<your email>"

.. warning::

  Do not mount your host ``~/.gitconfig`` into the container to solve this. If it contains ``url.*.insteadOf`` rules
  that rewrite ``https://github.com/`` to SSH — a common setup — the ``git-lfs`` feature's post-create step will
  attempt SSH, find no key inside the container, and fail the entire ``up``.

If you sign your commits, note that the VS Code extension forwards your GPG agent automatically but the CLI does not —
the container will have your public key but no private key, and the commit fails to sign. Forward the agent's extra
socket when starting the environment, which keeps your private key on the host:

.. code-block:: bash

  $ npx --yes @devcontainers/cli up --workspace-folder . \
      --mount "type=bind,source=$(gpgconf --list-dirs agent-extra-socket),target=/run/host-gpg-agent.sock"

Then point the container's agent socket at the forwarded one. Note the socket lives under ``/run/user/$(id -u)/gnupg/``,
not ``~/.gnupg/``:

.. code-block:: bash

  $ gpgconf --kill gpg-agent
  $ ln -sf /run/host-gpg-agent.sock /run/user/$(id -u)/gnupg/S.gpg-agent

.. _Dev Containers CLI: https://github.com/devcontainers/cli

Install Dependencies
--------------------

We are using `Poetry`_ to manage dependencies and virtual environments.

.. note::

    Poetry is a tool for dependency management and packaging in Python. It allows you to declare the libraries your
    project depends on and it will manage (install/update) them for you. Poetry offers a lockfile to ensure repeatable
    installs, and can build your project for distribution.

Once the Dev Container is started, open a shell session in the Terminal view of VS Code. The current working directory
will be ``/workspaces/partcad`` containing the source files. To install Python packages, run the following:

.. code-block:: bash

  $ poetry install

It will create virtual environment in ``.venv/`` directory and download about 1.5 GB dependencies. Once all dependencies
are downloaded Poetry will also install current package in editable mode, and you will see the following:

.. code-block::

  Installing the current project: partcad (0.8.51)

.. warning::

    **A checkout that predates the one-wheel layout needs cleaning out first.** This repository used to hold six
    Python distributions in six top-level directories -- ``partcad/``, ``partcad-cli/``, ``partcad-client/``,
    ``partcad-ide-client/``, ``partcad-service-json-rpc/``, ``partcad-utils/`` -- and to install a seventh,
    ``partcad-dev``, as the root project. Switching to the branch that collapsed them into ``src/`` leaves both
    behind, and neither goes away on its own:

    * ``git`` does not remove the old directories, because the only files still in them are ignored ones
      (``__pycache__/``, ``*.egg-info/``). They look empty and are not.
    * ``.venv`` keeps the ``partcad-dev`` install. Its ``.pth`` still puts the six deleted ``*/src`` directories on
      ``sys.path`` and its ``pc`` still points at the pre-rename entry point, so ``pc`` fails with
      ``ModuleNotFoundError: No module named 'partcad_cli.click.command'``. ``poetry install`` does not replace it
      -- the distribution was renamed, so Poetry does not know it is there -- and ``pip uninstall partcad-dev``
      refuses to remove it, with ``ValueError: ('Invalid group name', 'poetry-multiproject-plugin')``, because the
      metadata it left behind names an entry point group that is not valid.

    Delete both from the repository root, then install again:

    .. code-block:: bash

      $ rm -rf partcad partcad-cli partcad-client partcad-ide-client partcad-service-json-rpc partcad-utils
      $ rm -rf .venv/lib/python*/site-packages/partcad_dev.pth \
               .venv/lib/python*/site-packages/partcad_dev-*.dist-info
      $ poetry install

    A fresh clone needs none of this.

Activate Environment
--------------------

In order to update your ``$PATH`` and be able to run commandline tools such as ``pytest`` you need to activate virtual
environment:

.. code-block:: bash

  $ poetry shell

or

.. code-block:: bash

  $ $(poetry env activate)

After that you will be able to run ``pc``, for example ``pc version``, which will output something along the lines:

.. code-block::

  INFO:  PartCAD Python Module version: 0.7.40
  INFO:  PartCAD CLI version: 0.7.40

Make Changes
------------

Make the changes through Visual Studio Code how you would do for any other project.

Manual Tests
------------

To test functionality of the Python core module, use corresponding command line interface (CLI) commands.

To test CLI functionality, simply type commands in a shell session in the Terminal view of the VSCode where the development takes place.

To test VSCode plugin, run the following commands in a shell session in the Terminal view before restarting the VSCode:

.. code-block:: bash

    $ cd ide/vscode
    $ npm ci
    $ npm run vsce-package
    $ code --install-extension partcad.vsix

To test the Python core module using the VSCode plugin, click the `Restart PartCAD` icon in the PartCAD's `Context` view after each change.

.. note::

  If you are developing inside the PartCAD Dev container using PartCAD VSCode extension, and are seeing this:

  .. code-block:: text

      ERROR: Failed to clone repo https://github.com/partcad/partcad-index.git after 0 retries

  then you are likely to have Git configured to use SSH creds to access GitHub,
  while the SSH creds are not available in the Dev container.

  This could be fixed by running ``ssh-add`` on the host
  and confirmed by running ``ssh-add -l`` inside the container.

To test documentation changes, run the following command before navigating your favorite VSCode browser extension to `./docs/build/html`:

.. code-block:: bash

    $ sphinx-build -M html docs/source docs/build -n -W

Alternatively, run the following command before navigating your favorite VSCode browser extension to `127.0.0.1:8000`:

.. code-block:: bash

    $ sphinx-autobuild --host 127.0.0.1 -b html docs/source docs/build

Automated Tests
---------------

Pytest
^^^^^^

PartCAD uses ``pytest`` for unit testing, where a particular piece of code or feature is tested.

If you `activated virtual environment`_ you can just run ``pytest`` from a bash session in the Terminal view of VSCode.

You can also use VS Code's built-in **Testing** integration to run and debug tests via the UI. To set this up:

1. Open the Command Palette (``Ctrl+Shift+P`` or ``Cmd+Shift+P``)
2. Run ``Python: Select Interpreter``
3. Select ``('.venv': Poetry) .venv/bin/python`` from the list

You also can run ``pytest`` without activating environment via Poetry, for example:

.. code-block:: bash

    $ poetry run pytest

The tests for the core module are located in the ``./tests/partcad`` directory.
The tests for the CLI module are located in the ``./tests/partcad_cli`` directory.
The tests for the IDE viewer client are located in the ``./tests/partcad_ide_client`` directory.
The tests for the LSP server of VSCode plugin are located in the ``./ide/vscode/src/test/python_tests`` directory.

**The first run is slow, and that is the sandboxes rather than the tests.** A test whose part is scripted
(build123d, CadQuery, SDF, OpenSCAD) runs in a Python environment PartCAD provisions on first use -- a fresh
interpreter plus a pip install of the CAD stack -- and whichever test is the first to need a given one pays for
building it. Once built they are cached under ``~/.partcad`` and reused, so the same suite that took half an
hour cold takes minutes warm. The ``pytest`` ``pre-commit`` hook allows 15 minutes per test for that reason
(``PC_PYTEST_TIMEOUT`` overrides it); a test reported as timing out on a cold cache is worth simply running
again before it is treated as a bug.

**A gate reads the session's verdict, not pytest's exit code.** The two disagree on Windows, in both
directions: pytest has exited ``0`` with a test having failed, and it exits ``127`` after a session in which
every test passed. So a caller that must not be wrong sets ``PYTEST_RESULT_MARKER`` to a path, and the
``pytest_sessionfinish`` hook in the repository's root ``conftest.py`` writes ``success`` there only when
pytest's *final* exit status is clean *and* it counted no failed tests, and ``failure`` otherwise -- a
collection error included, which pytest reports as exit status 2. "Final" is load-bearing: pytest's terminal
reporter can still raise the status after the inner session hooks have run (exceeding ``--max-warnings`` is
how), so the hook is the outermost wrapper and reads ``session.exitstatus`` rather than the status it was
handed. Both gates do this -- the ``pytest`` ``pre-commit`` hook and the ``Pytest`` job in CI -- and both fail
unless they read ``success``, so a run that never reaches the hook at all (a crash mid-suite, a runner that
goes away) writes no marker and fails too. Nothing is written unless that variable is set, so an ordinary
``poetry run pytest`` is unaffected.

Behave
^^^^^^

PartCAD uses ``behave`` for integration testing, where a part of the system is tested as a whole.

To run tests using ``behave``, execute the following command in an activated environment:

.. code-block:: bash

    $ behave

Feature definitions and step implementations are located in the ``./features`` directory.

Examples
^^^^^^^^

The packages under ``./examples`` are documentation, and they are also a
regression test. Each one declares a ``render:`` section, and the images and
``README.md`` files that ``pc render`` produces from it are **checked in**. That
is deliberate: a change in how PartCAD renders then shows up as a diff in those
files, and whoever made the change gets to decide whether it is an improvement
or a regression before it reaches a reader of the README.

So if your change affects what a projection or a generated document looks like,
re-render the examples and commit the result along with it:

.. code-block:: bash

    $ cd examples && pc render -r

Two things guard the invariant. The ``example-images`` ``pre-commit`` hook is
instant and checks only what is already on disk: every image an example's
``README.md`` points at has to exist and be checked in, and no ``.gitignore``
may hide one. It exists because the mistake that costs is asymmetric -- a
regenerated ``README.md`` is a tracked file and stages itself with ``git add
-u``, while the images beside it are new and untracked and do not. The
``Examples (PartCAD)`` CI job then renders everything and fails if the working
tree changed at all; that check runs on one cell of the matrix, because what is
checked in is one rendering.

Everything PartCAD implements itself can be a baseline, including the DXF --
which a CAD tool would otherwise stamp with the time it was written and a fresh
pair of GUIDs. The built-in DXF renderer writes fixed values for those instead,
and pins the order of the ``CLASSES`` section, which ezdxf otherwise derives
from a ``set`` and so emits differently per process. That is the
``reproducible`` parameter of the ``dxf`` file type, on by default; a drawing
that has to record when it was really written sets ``reproducible: false``, and
stops being diffable.

An implementation another package supplies is not PartCAD's to fix, and one of
them may well write a different file every time. Those files are named in the
CI check's ``UNSTABLE`` list, which is deliberately short: every entry is a file
nobody is watching any more, so it needs a reason there and the same reason
where a reader of that package will meet it. See ``examples/feature_render_custom``,
whose SVG and PDF are the only entries today.

Commit & Push Changes
---------------------

You can commit changes from either terminal or VS Code UI which will trigger local git hooks managed by ``pre-commit`` to
enforce coding standards and catch some of the problems early.

pre-commit
^^^^^^^^^^

.. note::

    `pre-commit`_ is a framework for managing and maintaining multi-language pre-commit hooks.

Configuration file is located at ``.devcontainer/.pre-commit-config.yaml`` where you can see all supported hooks.

In rare cases, you might need to temporarily disable hooks. There are two options:

1. Use `temporarily disable hooks`_ to skip specific individual hooks
2. Use `git commit --no-verify`_ to skip all hooks at once

Remember: These hooks are required to pass in CI before PR merge.

.. warning::

    While you can remove local git hooks completely, be aware that:
    1. Your PR will be blocked from merging until all hook checks pass in CI
    2. You'll miss early feedback that could prevent CI failures
    3. You may need to make additional commits to fix issues that hooks would have caught locally

    Option 1: Using pre-commit (recommended)

    .. code-block:: bash

      # To remove hooks:
      pre-commit uninstall --config .devcontainer/.pre-commit-config.yaml
      # To restore hooks later:
      pre-commit install --config .devcontainer/.pre-commit-config.yaml

    Option 2: Manual removal (use with caution):

    .. code-block:: bash

      # Make sure you're in the right directory first
      if [ -d ".git/hooks" ]; then
        # Backup hooks first
        mkdir -p .git/hooks_backup
        mv .git/hooks/* .git/hooks_backup/
        echo "Hooks backed up to .git/hooks_backup/"
      else
        echo "Error: .git/hooks directory not found"
      fi

Open Pull Request
-----------------

There are multiple options how PR could be opened, please refer to the following to choose option which works best for
you.

- `Creating a pull request`_
- `GitHub Pull Requests in Visual Studio Code`_

Meet PR Merge Criteria
----------------------

Depending on files changed in PR you might need to get required checks to pass first and get reviews from owners or
maintainers, following are related GH docs:

- `About Status Checks`_
- `Required reviews`_

.. _deep-test:

Running the full test matrix
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

CI fans out over operating systems, and a pull request does not pay for all of them. By default it drops both
Ubuntu 22.04 images and the second macOS, which is most of the cost -- macOS minutes bill at ten times the
Linux rate. What stays is Ubuntu 24.04 on x86_64 and arm64, both Windows images, and one macOS.

The full matrix runs on the nightly schedule, on a manual workflow run, and on a push, which includes the
release. A push to ``devel`` is the exception: it runs no matrix at all unless its head commit message starts
with ``Version updated``, which is the release commit. That exception applies to pushes and to nothing else --
the nightly run has no head commit to read a message from, so the guard leads with the event name and lets
every other trigger through. It did not, from the day the guard was written until 0.8.32, and the nightly was
skipped every night in between: if you change that condition, keep the event-name clause first.
To run it on a pull request before it merges, put ``#deepTest`` anywhere in the pull request title or
description and re-run the checks. Worth doing when the change touches packaging, dependencies, the standalone
bundle or the snap, or anything else where an older OS version could behave differently.

The ``Standalone`` workflow reads the same marker: without it, a pull request builds four of the seven
standalone bundles -- it drops both Ubuntu 22.04 images and macOS on x86_64, whose runner bills at the same ten
times the Linux rate. The ``IDE`` workflow reads it too, for the one IDE whose command line bundle is
deep-only: the Intel macOS application is built and installed on a deep run and on no other. A release always
builds all seven bundles and all four IDEs, and refuses to publish if any is missing.

Both workflows install each macOS artifact on macOS 15 *and* on macOS 26, because there is one macOS build per
architecture and it is frozen on the older release -- so "a bundle runs on the OS it was built on and
everything newer" stopped being an assumption and became something a job checks. Only the Intel half of that
is deep-only.

The Python axis is not the same for every job, because not every job is testing the same thing. ``Pytest`` and
``Examples (All)`` run the whole supported range: they exercise PartCAD's own code, so the interpreter it runs
on is the point. ``Examples (PartCAD)`` and ``Repo //pub`` render packages, so what they are really testing is
the sandbox -- and a sandbox is built at the version PartCAD pins rather than at the version PartCAD is running
on, so they run the two ends of the range a sandbox can be built at instead
(``sandbox_versions.MIN_PYTHON_VERSION_CADQUERY`` and ``MAX_PYTHON_VERSION_CAD``). ``Behave`` drives the command
line, so it stays on the oldest and newest supported Python.

Implementation Details
----------------------

The following information is useful for PartCAD contributors.

.. _location:

Coordinates / Location
^^^^^^^^^^^^^^^^^^^^^^

PartCAD uses OpenCASCADE Location objects (TopLoc_Location) to represent locations of objects in 3D space.

.. code-block:: javascript

    [[1, 2, 3], [4, 5, 6], 70]

The above list represents a location with the following components:

1. ``[1, 2, 3]``: Translation or offset (in millimeters) along the X, Y, and Z axes
2. ``[4, 5, 6]``: The X, Y and Z sizes of the vector to rotate around
3. ``70``: The angle of rotation around the above vector


Internal geometry representation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PartCAD maintains parts as OpenCASCADE objects. Similar to ``wrapped`` objects found
in ``CadQuery`` and ``build123d``.

Parallelism
^^^^^^^^^^^

1. Asynchronous at heart

  PartCAD is designed to run most of its logic as coroutines in the asyncio's event loop.

2. Threads for the muscle

  There is a separate thread pool created for long-running procedures that are CPU intensive.
  The number of threads matches the number of CPU cores minus 1 (if there is more than 1).

  Coroutines can spawn tasks on the thread pool. Tasks on the thread pool can't call coroutines that use asyncio.Lock().

3. Digest external code properly

  Separate processes are spawned (optionally, in a sandboxed environment) to process third-party CAD-as-code parts and assemblies.
  One thread is consumed in the thread pool to wait for each such process to complete (to cap the number of CPU cores occupied).

4. Friendly face

  To make it apparent to external users, all externally visible coroutines have names that end with "_async".
  Each such coroutine is accompanied by a synchronous wrapper (which does not have "_async" in its name).


.. _Open a Git repository or GitHub PR in an isolated container volume: https://code.visualstudio.com/docs/devcontainers/containers#_quick-start-open-a-git-repository-or-github-pr-in-an-isolated-container-volume
.. _Open an existing folder in a container: https://code.visualstudio.com/docs/devcontainers/containers#_quick-start-open-an-existing-folder-in-a-container
.. _named volume: https://docs.docker.com/engine/storage/volumes/
.. _bind: https://docs.docker.com/engine/storage/bind-mounts/
.. _VS Code: environment.md#visual-studio-code
.. _Docker: environment.md#docker
.. _Poetry: https://python-poetry.org/docs/
.. _activated virtual environment: #activate-environment
.. _pytest: https://docs.pytest.org/en/stable/
.. _Behave: https://behave.readthedocs.io/en/latest/
.. _pre-commit: https://pre-commit.com/
.. _temporarily disable hooks: https://pre-commit.com/#temporarily-disabling-hooks
.. _git commit --no-verify: https://git-scm.com/book/fa/v2/Customizing-Git-Git-Hooks#_committing_workflow_hooks
.. _gh pr create: https://cli.github.com/manual/gh_pr_create
.. _Creating a pull request: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
.. _GitHub Pull Requests in Visual Studio Code: https://code.visualstudio.com/blogs/2018/09/10/introducing-github-pullrequests
.. _Merging a pull request: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request
.. _About Status Checks: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks#checks
.. _Required reviews: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews
