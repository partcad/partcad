CLI command reference
#####################

This page lists every command in the PartCAD command line interface. Both ``pc`` and ``partcad`` invoke the
same tool. Run ``pc <command> --help`` at any time to see the full, up-to-date options for a command.

Common options, such as ``-v``/``-q`` (verbosity), ``--no-ansi`` (plain-text logs), ``--offline``,
``--threads-max``, and ``-p PATH`` (select the package), apply to every command.

``--devel-index`` is one of those common options, and is worth calling out. The public index (the ``pub``
dependency, published at `partcad-index <https://github.com/partcad/partcad-index>`_) lives in a repository of
its own, and a package imports it at ``main``: the revision ``pc init`` writes into the dependency, and the
default branch a plain import lands on anyway. Either way that is the released state. ``--devel-index`` imports
its ``devel`` branch instead — the branch that a release fast-forwards ``main`` to — so a change staged there
can be exercised before it is released. It replaces the revision a package names rather than deferring to it,
which is what it exists to do. The redirect follows the repository rather than the dependency name, so it
applies wherever the index appears in the dependency tree and leaves every other dependency alone. The same
switch is available as the ``PC_DEVEL_INDEX`` environment variable, as ``develIndex`` in the user configuration,
and as the ``partcad.develIndex`` setting of the VS Code extension.

Every boolean ``PC_*`` variable (``PC_DEVEL_INDEX``, ``PC_FORCE_UPDATE``, ``PC_OFFLINE``, ``PC_CACHE_FILES``, the
``PC_TELEMETRY_*`` switches, …) is read the same way: ``1``, ``true``, ``yes``, ``on`` turn it on, and ``0``,
``false``, ``no``, ``off`` or an empty value turn it off, ignoring case. Setting one to anything else turns it
on.

Most commands are served by a background daemon that stays warm between invocations, which raises the question
of *whose* configuration the work runs under. It is always yours, as of the moment you ran the command: ``pc``
resolves its user configuration — the config file, the ``PC_*`` environment and the options on the command line,
layered — and hands a copy to the daemon with every request, and the daemon builds the package context from
that copy rather than from the configuration it was started with. So ``pc --devel-index list`` means what it
says even when a daemon has been running since before you set it, and there is no daemon to restart after
changing a setting.

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

``pc upgrade``
  Upgrade PartCAD itself to the latest version. This upgrades the installation on this machine; the packages a
  package imports are ``pc update``.

  PartCAD upgrades itself whichever way it was installed: the Python wheels are upgraded with ``pip``, and a
  standalone bundle downloads the matching release, verifies its checksum, and installs it beside the running
  copy. Nothing is downloaded and no daemon is disturbed until a newer version has actually been found; once
  one has, every PartCAD daemon running on the machine is asked to stop and waited for, because all of them are
  executing files that are about to be replaced. The new version goes in beside the old one, and the old one is
  then removed — including the copy the command is itself running from, which goes as soon as the command
  exits. An installation that runs from a source checkout is reported and skipped — update that one with
  ``git``.

  Use ``--check`` to report whether a newer PartCAD is available without installing anything, and
  ``--to-version`` to install a specific version instead of the latest one. Under the global ``--offline`` flag
  the version check is skipped entirely.

  The "Update PartCAD" command in the VS Code extension runs exactly this, so the two never drift apart.

****************
Package commands
****************

``pc init``
  Create a new PartCAD package (a ``partcad.yaml`` file) in the current directory. Use ``-i`` for interactive
  mode, and options such as ``--desc``, ``--url``, and ``--manufacturable`` to prefill package metadata.

``pc install``
  Download everything the current package needs to be built - the PartCAD counterpart of ``npm install``.
  It fetches all imported packages, then prepares every sketch, part and assembly by computing its cache key:
  that downloads the files behind ``fileFrom`` and resolves each alias, enrich, compound and assembly link,
  which loads the packages the objects really depend on. Nothing is built. Use ``-P`` to install a package
  other than the current one and ``-r`` to prepare the objects of the imported packages too.

``pc update``
  Force update all imported packages to their latest versions. This updates the packages a package imports;
  to upgrade the PartCAD installation itself, use ``pc upgrade``.

``pc lint``
  Run linting checks on the files within packages. Use ``-r`` to check imported packages recursively and
  ``-f`` to run only checks whose name starts with a given prefix. ``--file PATH`` (repeatable) checks the
  named files instead, in this process rather than through the daemon; add ``--json`` for machine-readable
  findings and ``--stdin`` to check unsaved content supplied on standard input.

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
  YAML file). ``pc import assembly`` is a one-shot conversion; to keep reading the source file itself,
  declare it as an assembly of the ``step`` type instead (see :ref:`assembly_step`).

``pc test``
  Run tests on a part, assembly, or scene. Use ``-r`` to test imported packages recursively, ``-f`` to filter
  by name prefix, and ``-s``/``-i``/``-a``/``-S`` to indicate a sketch, interface, assembly, or scene.
  The tests cover whether the object builds (``cad``), whether it can be manufactured or purchased
  (``cam`` and the methods below it), and whether an assembly's connection instructions can be followed
  (``connect``); see "Testing the instructions" in :doc:`assy`.

  The manufacturability test asks for exactly what ``pc supply`` would order. An assembly that is sold
  assembled (see :ref:`procurement`) passes once a supplier carries it, and is not taken apart: the parts
  inside it are the seller's problem. Every other assembly has to declare how it is assembled, and everything
  it is procured from -- its parts, and the sub-assemblies that are ordered assembled -- has to be obtainable
  on its own.

``pc inspect``
  View a part, assembly, or scene visually. Use ``-V`` for a verbal (text) description instead of a visual
  one, and ``-p <name>=<value>`` to set parameters.

``pc info``
  Show detailed information about a part, assembly, or scene, including its parameters.

``pc bom``
  Print the bill of materials of an assembly: every part it is made of, recursively, with how many of each
  are needed and, where the object says so, the vendor and the SKU to order it by. Use ``-P`` to name the
  package the assembly comes from, ``-p <name>=<value>`` to set parameters, and ``-j``/``--json`` to produce
  JSON on standard output instead of a table.

  ``-s``/``--stop-at-purchasable`` stops the recursion at a sub-assembly that can be bought ready-made — one
  that declares both a ``vendor`` and an ``sku``, and that a supplier of its package reports as available.
  Such a sub-assembly is listed as a single line item and its own contents are left out: it is one thing to
  order, not a list of parts to source and assemble. A sub-assembly that names a vendor and an SKU nobody
  supplies is still expanded.

``pc convert``
  Convert parts, sketches or assemblies to another format and update their type in the package. Subcommands:
  ``part``, ``sketch`` and ``assembly``. An assembly converts between ``assy`` and ``urdf``: to URDF it writes
  the ``.urdf`` file and the meshes it references; to ASSY it writes an ``stl`` part for every URDF link, an
  interface pair for every joint, and an ``.assy`` that places the parts with ``connect:``.

``pc export``
  Export a 3D view of parts, assemblies, or scenes. Choose the format with ``-t``:
  ``step``, ``brep``, ``stl``, ``3mf``, ``threejs``, ``obj``, ``gltf``, ``iges``, ``urdf``, or any file type a
  package implements itself (see :ref:`output-files`). Use ``-O`` to set the output directory and ``-r`` to
  export recursively. ``urdf`` writes a ``.urdf`` file plus a directory of the mesh files it references. ``-e``
  names a further package whose ``export:`` options and implementations are used, which is how one package's
  exporter is applied to another package's objects.

``pc render``
  Render a 2D projection of parts, assemblies, or scenes onto a plane. Choose the format with ``-t``:
  ``svg``, ``png``, ``jpeg``, ``dxf``, ``readme``, ``pdf``, ``html``, or any file type a package implements
  itself (see :ref:`output-files`). ``-e`` works the same way as it does for ``pc export``, reading the
  ``render:`` options from another package.

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

  ``find`` and ``quote`` take parts and assemblies alike. A requested assembly that is sold assembled (one with
  ``vendor`` and ``sku`` set, see :ref:`procurement`) is ordered as one item. Any other assembly is procured as
  the objects it is made of, and the walk stops at every sub-assembly that is sold assembled: such a
  sub-assembly is ordered as one item instead of being taken apart. Pass ``--recursive`` (``-r``) to walk all
  the way down to the parts regardless, and order those.

**************
Other commands
**************

``pc adhoc``
  Ad-hoc operations that run on the fly without creating or configuring a package. Subcommand: ``convert``
  (convert a part or sketch to another format without updating its type). The assembly formats ``assy`` and
  ``urdf`` are refused here: an ASSY file is a set of references to the parts of a package and a URDF becomes a
  part per link, so neither means anything without one. Use ``pc convert assembly`` in a package instead.

``pc healthcheck``
  Check the host system for known issues. Use ``--dry-run`` to list the available checks, ``--filters`` to run
  only checks with the given tags, and ``--fix`` to attempt automatic fixes.

``pc search``
  Search for objects by keyword. Subcommands: ``all``, ``parts``, ``sketches``, ``assemblies``,
  ``interfaces``, and ``packages``.
