CLI command reference
#####################

This page lists every command in the PartCAD command line interface. Both ``pc`` and ``partcad`` invoke the
same tool. Run ``pc <command> --help`` at any time to see the full, up-to-date options for a command.

Common options, such as ``-v``/``-q`` (verbosity), ``--no-ansi`` (plain-text logs), ``--offline``,
``--threads-max``, and ``-p PATH`` (select the package), apply to every command.

``--devel-pub`` is one of those common options, and is worth calling out. The public index (the ``pub``
dependency, published at `partcad-index <https://github.com/partcad/partcad-index>`_) lives in a repository of
its own, so nothing in your package pins which version of it you get: an ordinary run imports its default
branch, which is the released state. ``--devel-pub`` imports its ``devel`` branch instead — the branch that a
release fast-forwards ``main`` to — so a change staged there can be exercised before it is released. The
redirect follows the repository rather than the dependency name, so it applies wherever the index appears in
the dependency tree and leaves every other dependency alone. The same switch is available as the
``PC_DEVEL_PUB`` environment variable, as ``develPub`` in the user configuration, and as the ``partcad.develPub``
setting of the VS Code extension.

Every boolean ``PC_*`` variable (``PC_DEVEL_PUB``, ``PC_FORCE_UPDATE``, ``PC_OFFLINE``, ``PC_CACHE_FILES``, the
``PC_TELEMETRY_*`` switches, …) is read the same way: ``1``, ``true``, ``yes``, ``on`` turn it on, and ``0``,
``false``, ``no``, ``off`` or an empty value turn it off, ignoring case. Setting one to anything else turns it
on.

*************
Host commands
*************

``pc version``
  Display the versions of the PartCAD Python module and CLI, then exit.

``pc config``
  Show the current user configuration.

``pc system``
  Manage PartCAD's system-wide state and settings:

  - ``pc system status`` — Display the state of the internal data used by PartCAD, including the location of
    the local cache.
  - ``pc system reset`` — Reset all internal state maintained by PartCAD, for example to clear a corrupted
    cache.
  - ``pc system set`` — Set system-wide settings, such as the telemetry type, environment, and Sentry DSN.
  - ``pc system telemetry`` — Inspect or clear locally stored telemetry data (``info``, ``clear``).

****************
Package commands
****************

``pc init``
  Create a new PartCAD package (a ``partcad.yaml`` file) in the current directory. Use ``-i`` for interactive
  mode, and options such as ``--desc``, ``--url``, and ``--manufacturable`` to prefill package metadata.

``pc install``
  Download and set up all packages imported by the current package.

``pc update``
  Force update all imported packages to their latest versions.

``pc lint``
  Run linting checks on the files within packages. Use ``-r`` to check imported packages recursively and
  ``-f`` to run only checks whose name starts with a given prefix.

***************
Object commands
***************

``pc list``
  List components. Subcommands select what to list: ``all``, ``parts``, ``sketches``, ``assemblies``,
  ``interfaces``, ``mates``, and ``packages``.

``pc add``
  Add an object to a package. Subcommands: ``dep`` (a dependency), ``sketch``, ``part``, and ``assembly``.

``pc import``
  Import an existing object into a package. Subcommands: ``part`` (import an existing part and optionally
  convert its format) and ``assembly`` (import an assembly from a file, creating the parts and an Assembly
  YAML file).

``pc test``
  Run tests on a part, assembly, or scene. Use ``-r`` to test imported packages recursively, ``-f`` to filter
  by name prefix, and ``-s``/``-i``/``-a``/``-S`` to indicate a sketch, interface, assembly, or scene.

``pc inspect``
  View a part, assembly, or scene visually. Use ``-V`` for a verbal (text) description instead of a visual
  one, and ``-p <name>=<value>`` to set parameters.

``pc info``
  Show detailed information about a part, assembly, or scene, including its parameters.

``pc convert``
  Convert parts or sketches to another format and update their type in the package. Subcommands: ``part`` and
  ``sketch``.

``pc export``
  Export a 3D view of parts, assemblies, or scenes. Choose the format with ``-t``:
  ``step``, ``brep``, ``stl``, ``3mf``, ``threejs``, ``obj``, ``gltf``, or ``iges``. Use ``-O`` to set the
  output directory and ``-r`` to export recursively.

``pc render``
  Render a 2D projection of parts, assemblies, or scenes onto a plane. Choose the format with ``-t``:
  ``svg``, ``png``, or ``readme``.

*****************
Workflow commands
*****************

``pc supply``
  Manage the supply chain of the current project:

  - ``pc supply caps`` — Show the capabilities of a provider.
  - ``pc supply find`` — Find suppliers.
  - ``pc supply quote`` — Get a quote from suppliers.
  - ``pc supply order`` — Place an order with suppliers.

**************
Other commands
**************

``pc adhoc``
  Ad-hoc operations that run on the fly without creating or configuring a package. Subcommand: ``convert``
  (convert a part or sketch to another format without updating its type).

``pc healthcheck``
  Check the host system for known issues. Use ``--dry-run`` to list the available checks, ``--filters`` to run
  only checks with the given tags, and ``--fix`` to attempt automatic fixes.

``pc search``
  Search for objects by keyword. Subcommands: ``all``, ``parts``, ``sketches``, ``assemblies``,
  ``interfaces``, and ``packages``.
