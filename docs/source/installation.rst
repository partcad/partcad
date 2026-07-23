Installation
############


==================
Command line tools
==================

PartCAD command line tools are implemented in Python and, in theory,
available on all platforms where Python is available. However, it is only
getting tested on Linux, MacOS and Windows.

.. code-block:: shell

  $ python -m pip install -U partcad-cli

.. note::

  PartCAD works best when `conda <https://docs.conda.io/>`_ is installed.
  If that doesn't help (e.g. MacOS+arm64) then try ``mamba``.
  On Windows, PartCAD must be used inside a ``conda`` environment.

.. note::

  On Ubuntu, try ``apt install libcairo2-dev`` if ``pip install`` fails to install ``cairo``.

.. note::

  Git does not need to be installed. PartCAD talks to git servers itself, through the
  ``libgit2`` library that comes with its dependencies, so packages imported from git
  repositories are cloned and updated without the ``git`` command line tool. Where git is
  installed, PartCAD still reads its configuration: see :ref:`git-configuration`.

The commands and options supported by PartCAD CLI:

.. code-block:: text

  $ pc --help

   Usage: pc [OPTIONS] COMMAND [ARGS]...


   ██████╗  █████╗ ██████╗ ████████╗ ██████╗ █████╗ ██████╗
   ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
   ██████╔╝███████║██████╔╝   ██║   ██║     ███████║██║  ██║
   ██╔═══╝ ██╔══██║██╔══██╗   ██║   ██║     ██╔══██║██║  ██║
   ██║     ██║  ██║██║  ██║   ██║   ╚██████╗██║  ██║██████╔╝
   ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═════╝

  Host commands:
    version      Display the versions of the PartCAD Python Module and CLI, then exit
    config       Show the current user configuration
    system       PartCAD system commands (reset, set, status, telemetry)

  Package commands:
    init         Create a new PartCAD package in the current directory
    install      Download and set up all imported packages
    update       Force update all imported packages to their latest versions
    lint         Run linting checks on files within packages

  Object commands:
    list         List components (parts, sketches, assemblies, interfaces, mates, packages)
    add          Add a dependency, sketch, part, or assembly
    import       Import a dependency, sketch, part, or assembly
    test         Run tests on a part, assembly, or scene
    inspect      View a part, assembly, or scene visually
    info         Show detailed information about a part, assembly, or scene
    convert      Convert parts or sketches to another format and update their type
    export       Export a 3D view of parts, assemblies, or scenes
    render       Render a 2D projection of parts, assemblies, or scenes onto a plane

  Workflow commands:
    ai           AI-powered workflows (regenerate)
    supply       Manage the supply chain of the current project

  Other commands:
    adhoc        Ad-hoc operations that do not require a package
    healthcheck  Check the host system for known issues
    search       Search for parts, sketches, or assemblies

Common options apply to every command, including ``-v``/``-q`` to raise or lower verbosity, ``--no-ansi`` for
plain-text logs, and ``-p PATH`` to select the package (a ``partcad.yaml`` file or a directory that contains
one). Run ``pc <command> --help`` to see the options for any command.

For a full command reference, see :doc:`cli`.


=====================================
Latest Development Version of PartCAD
=====================================

You can install the latest development version of PartCAD from the ``devel`` branch on
`PartCAD <https://github.com/partcad/partcad>`_. First, create an isolated Python environment,
and ensure ``pip``, ``setuptools``, and ``wheel`` are upgraded, then follow the instructions
below to install the core module and the CLI tool.

1. **Install or upgrade the Core Python Module**

   .. code-block:: shell

      $ python -m pip install --upgrade git+https://github.com/partcad/partcad.git@devel#subdirectory=partcad

2. **Install or upgrade the CLI**

   .. code-block:: shell

      $ python -m pip install --upgrade git+https://github.com/partcad/partcad.git@devel#subdirectory=partcad-cli

=============
Python module
=============

PartCAD provides Python modules that can be used in CAD as code scripts
(such as ``CadQuery`` and ``build123d``). It's a dependency of ``partcad-cli`` so it
doesn't usually need to be installed separately.

.. code-block:: shell

    $ python -m pip install -U partcad
    $ python
    ...
    >>> import partcad as pc
    >>> ctx = pc.init()

============
AI providers
============

The SDKs of the supported AI providers are optional. Install the extra that
matches the provider you intend to use, either on ``partcad-cli``:

.. code-block:: shell

    $ python -m pip install -U 'partcad-cli[ai-google]'   # Google Gemini
    $ python -m pip install -U 'partcad-cli[ai-openai]'   # OpenAI
    $ python -m pip install -U 'partcad-cli[ai-ollama]'   # locally hosted Ollama
    $ python -m pip install -U 'partcad-cli[ai]'          # all of the above

or on ``partcad`` itself, using the same extra names:

.. code-block:: shell

    $ python -m pip install -U 'partcad[ai]'

Without the matching extra, using an AI provider fails with an error naming the
package to install. Everything else in PartCAD works without them.

=======
Linting
=======

The linter used by ``pc lint`` to check Python files is optional. Install the
``lint`` extra to enable it, either on ``partcad-cli``:

.. code-block:: shell

    $ python -m pip install -U 'partcad-cli[lint]'

or on ``partcad`` itself, using the same extra name:

.. code-block:: shell

    $ python -m pip install -U 'partcad[lint]'

Without the extra, linting Python files reports an error naming the package to
install. Everything else in PartCAD, including linting of YAML files, works
without it.

============================
Visual Studio Code extension
============================

This extension is available through the VS Code marketplace.
The corresponding marketplace page is `here <https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad>`_.

=========================
Public PartCAD repository
=========================

The public PartCAD repository is hosted at `GitHub <https://github.com/partcad/partcad-index>`_.
If necessary, PartCAD tools are automatically retrieving the contents of this
repository and all other required repositories and packages. No manual action is needed is need to `install` it.

However, if you suspect that something is wrong with locally cached files,
use ``pc system status`` to investigate and to determine the location of the cached files.
