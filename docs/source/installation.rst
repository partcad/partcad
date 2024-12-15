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

The commands and options supported by PartCAD CLI:

.. code-block:: shell

  # TODO: @alexanderilyin: This should be updated.
  $ pc help
  usage: pc [-h] [-v] [--no-ansi] [-p CONFIG_PATH] {add,add-part,add-assembly,init,info,install,update,list,list-all,list-parts,list-assemblies,render,inspect,status} ...

  PartCAD command line tool

  positional arguments:
    {add,add-part,add-assembly,init,info,install,update,list,list-all,list-parts,list-assemblies,render,inspect,status}
      add                 Import a package
      add-part            Add a part
      add-assembly        Add an assembly
      init                Create a new PartCAD package in the current directory
      info                Show detailed information about a part, assembly, or scene
      install             Download and set up all imported packages
      update              Refresh all imported packages
      list                List imported packages
      list-all            List available parts, assemblies and scenes
      list-parts          List available parts
      list-assemblies     List available assemblies
      render              Generate a rendered view of parts, assemblies, or scenes in the package
      inspect             View a part, assembly, or scene visually
      status              Show the current state of PartCAD's internal data

  options:
    -h, --help            show this help message and exit
    -v                    Increase verbosity level
    --no-ansi             Produce plain text logs without colors or animations
    -p CONFIG_PATH        Specify the package path (YAML file or directory with 'partcad.yaml')


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
use ``pc status`` to investigate and to determine the location of the cached files.
