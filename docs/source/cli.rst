CLI command reference
#####################

This page lists every command in the PartCAD command line interface. Both ``pc`` and ``partcad`` invoke the
same tool. Run ``pc <command> --help`` at any time to see the full, up-to-date options for a command.

Common options, such as ``-v``/``-q`` (verbosity), ``--no-ansi`` (plain-text logs), ``--offline``,
``--threads-max``, and ``-p PATH`` (select the package), apply to every command.

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
  ``svg``, ``png``, ``readme``, ``pdf``, or ``html``.

  ``-t readme`` generates a markdown document instead of a projection: the package document (``README.md``,
  listing what the package declares) or, when ``-a`` names an assembly, that assembly's own document
  (``<assembly>.md``, listing the bill of materials — every part and sub-assembly it is made of, recursively,
  grouped by the package they come from and counted). An assembly can also ask for its own document in the
  package configuration, by declaring ``readme`` in its ``render`` section.

  Only assemblies that a package declares are listed as sub-assemblies. An assembly embedded in an Assembly
  YAML file's nested ``links:`` section belongs to no package, so it is not listed on its own: the parts it
  holds are counted towards the assembly that embeds it.

  ``-t pdf`` and ``-t html`` generate the assembly instruction book of the assembly named by ``-a``: a title
  page, the same bill of materials, then — sub-assemblies first, since they have to exist before the assembly
  that uses them — a page showing each (sub-)assembly as it should look once it is together, followed by one
  page per assembly step. A step page shows the two items being joined, and below them an exploded view of the
  joint with a line drawn across the gap it opens. That gap is half of the largest dimension of the two items,
  unless the step sets ``exploded:`` in its ``connect:`` or ``connectPorts:`` section (see :doc:`assy`). The
  last page collects
  links: to this assembly and its package, to every other package that supplies at least three of its parts,
  and to PartCAD. The HTML is one self-contained file that shows a single page at a time, with arrows on
  either side (and the arrow keys) to flip through it. As with ``readme``, an assembly can ask for either
  document in the package configuration, by declaring ``pdf`` or ``html`` in its ``render`` section.

  Both formats are only defined for an assembly declared as ``type: assy``: the steps come from the Assembly
  YAML file, and an assembly that has none is refused rather than reduced to a title page and a parts list. An
  assembly that is not meant to be built at all (``manufacturable: false``, on the assembly or inherited from
  its package) is refused too; pass ``--ignore-manufacturability`` to generate the document anyway.

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
