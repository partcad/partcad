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

``pc daemon``
  Manage the background daemon described above. There is one per workspace, it is started on demand by the
  first command that needs it, and it is not normally something to think about — these are here for when it
  is:

  - ``pc daemon start`` — Start this workspace's daemon if it is not already running, and print the endpoint
    it serves on — a socket path, or a named pipe on Windows. This is also how the VS Code extension finds the
    daemon, so that "where is it" has one implementation rather than one per language. The endpoint is printed
    once the daemon answers on it, so whoever reads it can connect straight away.
  - ``pc daemon stop`` — Stop the daemon serving this workspace, and say whether one was running.
  - ``pc daemon status`` — Display the state of the internal data the daemon holds.
  - ``pc daemon reset`` — Drop that state. ``--repo-only``, ``--sandbox-only`` and ``--cache-only`` narrow it
    to the cached dependencies, the sandboxed runtime environments, or the filesystem cache respectively;
    without them all of it goes.
  - ``pc daemon set telemetry`` — Set the daemon's telemetry settings (``type``, ``env``, ``sentryDsn``),
    the daemon-side counterpart of ``pc system set``.

  There is no daemon to restart after changing a setting: every command hands the daemon its own resolved user
  configuration, as explained above. Stopping one is for upgrades and for clearing a wedged state.

  .. note::

    On Windows the daemon serves a named pipe rather than a Unix socket, and it is started as a detached
    process rather than by forking; ``pc daemon start``/``stop`` work the same way and print the same kind of
    answer. ``pc`` itself does not use it yet — each command there still runs a service of its own — so what a
    daemon buys on Windows today is the editor extension's warm context.

``pc open``
  Open a file in a third-party application, on this machine::

    pc open cube.step                       # in a locally installed FreeCAD
    pc open --use-docker cube.step          # or in a container, when there is none
    pc open --with blender cube.stl         # a mesh, in Blender
    pc open --with blender cube.step        # a solid, converted to STL for Blender first
    pc open --with gazebo warehouse.world   # a scene, in Gazebo
    pc open --with mujoco stack.xml         # a scene, in MuJoCo
    pc open --with mujoco warehouse.world   # a world, converted to MJCF for MuJoCo first
    pc open --with kicad Arduino_Nano.step  # a board, in KiCad

  ``--with`` names the application: ``freecad`` (the default), ``blender``, ``gazebo`` for a Gazebo world --
  which is what a :ref:`scene <scenes>` of type ``world`` is, and what ``pc export -S -t world`` writes --
  ``mujoco`` for a scene, and
  ``kicad`` for a board. A locally installed one is always
  used when there is one: the command looks on the ``PATH``, in ``/Applications`` on macOS, under
  ``Program Files`` on Windows, and for a flatpak on Linux. Gazebo is looked for under all three of the names
  it has had (``gz sim``, ``ign gazebo``, ``gazebo``), and whichever the machine has is the one used.

  Blender reads meshes and nothing else, so a file that is not one is converted to STL and Blender is given
  that instead: an STL, an OBJ or a glTF is imported as it is, while a STEP file, a CadQuery script or a mesh
  in a format Blender ships no importer for (3MF) is converted first. This is the one thing ``pc open`` asks
  the PartCAD daemon for, because turning a solid into a mesh is CAD work; the window still opens on the
  machine the command was run on. The converted copy is written under this workspace's own directory (never
  beside your file), named after the object it came from, and reused until that object changes. ``--type``
  says what the file holds when its name does not -- a ``.py`` is a CadQuery script, a build123d one or an SDF
  one -- and the VS Code extension passes the declared type of the object you clicked. A ``.blend`` is
  Blender's own file and is opened, not converted.

  MuJoCo reads MJCF and no other model format, so the same thing happens for the same reason: a scene that is
  not already an MJCF model -- a Gazebo world, above all -- is written out as one and MuJoCo is given that.
  It is the same daemon round trip and the same conversion machinery, asked for a scene instead of a part.

  An object that only means something inside a package -- an ASSY file, a URDF -- has nothing to convert
  ad-hoc, and is refused with that rather than converted wrongly: export it to a mesh first
  (``pc export -t stl``), or a scene to MJCF (``pc export -S -t mjcf``), and open that.

  KiCad is handed the board rather than the file named, when the two are not the same: a ``kicad`` part *is*
  the STEP file KiCad's command line writes out of the board, so ``pc open --with kicad`` on it opens the
  ``.kicad_pro`` (or ``.kicad_pcb``, or ``.kicad_sch``) beside it. Nothing is created here and nothing is
  rendered -- a file with no board beside it is handed over as it is. Every application but Blender is given
  the file it was pointed at, whatever it holds.

  With ``--use-docker``, a machine that has no local installation runs the application in a container instead
  — one container per application, named after it (``partcad-freecad``, ``partcad-blender``,
  ``partcad-gazebo``, ``partcad-mujoco``, ``partcad-kicad``), created from the application's image
  (``--docker-image`` overrides it; FreeCAD's is ``linuxserver/freecad:latest``, since the FreeCAD project
  publishes no image of its own, Blender's is ``linuxserver/blender:latest`` for the same reason, Gazebo's is
  ``gazebosim/gz-harmonic:latest``, MuJoCo's is ``ghcr.io/google-deepmind/mujoco:latest``, and KiCad's is the
  ``ghcr.io/partcad/partcad-container-kicad`` image PartCAD already builds for ``kicad`` parts) the first
  time and reused afterwards, so a container you have prepared
  keeps being the one that is used. Without ``--use-docker``, a machine with neither the application nor
  Docker is told so rather than being left with a command that quietly did nothing. Remove the application's
  own container (``docker rm -f partcad-freecad``, ``partcad-blender``,
  ``partcad-gazebo``, ``partcad-mujoco``, ``partcad-kicad``) to have the next ``pc open``
  create a fresh one. The workspace and the directory holding this workspace's daemon socket are mounted **at
  the paths they have on the host**, which is what lets one path mean the same thing on both sides. A file
  that is not in this workspace gets its own workspace mounted instead, so that whatever is mounted always
  contains the file the application is handed; a container created for one workspace and then used from
  another says so, and says to remove it, rather than opening a name the container cannot resolve.

  A containerised application draws on the host's X display. On Linux that display is usually a socket, which
  is shared with the container along with its authority cookie, and nothing needs configuring; a display
  reached over TCP — a forwarded one, or an X server on macOS or Windows (XQuartz, VcXsrv) — has to be
  installed and allowed to accept the connection. When there is none, the command says which one to install
  and what to run rather than starting a container whose window never appears.

  Like ``pc lint --file`` and ``pc upgrade``, this never talks to the daemon — a daemon can be remote, where
  the window would open on somebody else's screen. That is also why it takes a path rather than a
  ``<package>:<part>`` name: resolving a name is a package-graph question, which is the round trip this
  command does not make. ``--json`` prints what happened (or the reason it did not) as one object, which is
  what the VS Code extension's "Open in..." context menu reads.

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
  which loads the packages the objects really depend on. Every piece of :ref:`software` is prepared too, by
  fetching its file - it has no cache key, being a file rather than something built out of one. Nothing is
  built. Use ``-P`` to install a package
  other than the current one and ``-r`` to prepare the objects of the imported packages too.

``pc update``
  Force update all imported packages to their latest versions. This updates the packages a package imports;
  to upgrade the PartCAD installation itself, use ``pc upgrade``.

``pc lint``
  Run linting checks on the files within packages. Use ``-r`` to check imported packages recursively and
  ``-f`` to run only checks whose name starts with a given prefix. ``--file PATH`` (repeatable) checks the
  named files instead, in this process rather than through the daemon; add ``--json`` for machine-readable
  findings and ``--stdin`` to check unsaved content supplied on standard input. ``--schema`` says which schema
  an ASSY ``--file`` is checked against -- ``assembly``, ``scene`` (the same one with ``how:`` forbidden), or
  ``auto``, the default, which reads the declaration out of the package that names the file.

***************
Object commands
***************

``pc list``
  List components. Subcommands select what to list: ``all``, ``parts``, ``sketches``, ``assemblies``,
  ``scenes``, ``interfaces``, ``mates``, ``providers``, ``software``, and ``packages``.

``pc add``
  Add an object to a package. Subcommands: ``dep`` (a dependency), ``sketch``, ``part``, ``assembly``,
  ``scene``, and ``software``.

  Each object subcommand takes a file the package already has, **or an http(s) URL**. Given a URL, the file is
  fetched once so that the declaration can be written with the ``fileHash`` of what came back -- an object
  added from a URL is pinned, and therefore reproducible, from the moment it exists (see :ref:`file-hash`).
  The fetched copy is not kept: the package deliberately does not carry the file, and ``pc install`` fetches
  it when it is first needed. A fetch that fails adds nothing, because a declaration written without the hash
  is the unpinned one this exists to avoid.

``pc import``
  Import an existing object into a package. Subcommands: ``part`` (import an existing part and optionally
  convert its format), ``assembly`` (import an assembly from a file, creating the parts and an Assembly
  YAML file), and ``scene`` (import a Gazebo world, creating the parts and an Assembly YAML scene).
  ``pc import`` is a one-shot conversion; to keep reading the source file itself,
  declare it as an assembly of the ``step`` type or a scene of the ``world`` type instead (see
  :ref:`assembly_step` and :ref:`scenes`).

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

  It also requires what is to be made to be *reproducible*: an object read from a file the package fetches
  rather than carries has to pin it with ``fileHash``, or nothing says which bytes it was made from and the
  next run may quietly make something else (see :ref:`reproducibility`). The same is asked of the
  :ref:`software` an object declares -- every reference has to resolve, and the file it resolves to has to be
  obtainable and be the one that was meant. A board nobody can flash is not a board anybody can make.

``pc sim``
  Run the simulations a part or an assembly declares in its ``simulate:`` section, and check the
  ``validation:`` condition each of them states. Use ``-a`` when the object is an assembly, ``-r`` to run
  everything the imported packages declare too, ``-f`` to run only the simulation of a given name, and
  ``--json`` to print the whole of what each simulation plugin reported. A validation that does not hold
  exits non-zero.

  Where ``pc test`` asks whether a part can be *made*, this asks whether it *works*: it places the object in
  the scene the declaration names, at the ``offset:`` the declaration states, runs the scene through the
  simulation plugin the declaration names, and evaluates the ``validation:`` expression over the ``before``
  and ``after`` the plugin hands back. Nothing needs installing to run one -- the plugin runs in a PartCAD
  sandbox that installs whatever it needs.

  PartCAD implements no simulator: a package imports one and names it in ``simulation:``
  (`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ is the MuJoCo one). The *scene* does
  have a built-in default -- an empty world holding the object -- so a simulation of a part standing on its
  own is a few lines. See :doc:`simulation` and ``examples/feature_simulate``.

``pc inspect``
  View a part, assembly, or scene visually. Use ``-V`` for a verbal (text) description instead of a visual
  one, and ``-p <name>=<value>`` to set parameters.

``pc info``
  Show detailed information about a part, assembly, scene, or software, including its parameters.

``pc bom``
  Print the bill of materials of an assembly or a scene: every part it is made of, recursively, with how many of each
  are needed and, where the object says so, the vendor and the SKU to order it by. Use ``-P`` to name the
  package the assembly comes from, ``-p <name>=<value>`` to set parameters, and ``-j``/``--json`` to produce
  JSON on standard output instead of a table.

  ``-s``/``--stop-at-purchasable`` stops the recursion at a sub-assembly that can be bought ready-made — one
  that declares both a ``vendor`` and an ``sku``, and that a supplier of its package reports as available.
  Such a sub-assembly is listed as a single line item and its own contents are left out: it is one thing to
  order, not a list of parts to source and assemble. A sub-assembly that names a vendor and an SKU nobody
  supplies is still expanded.

  The :ref:`software` the parts and the assembly ship with is listed under a heading of its own, counted
  apart from the hardware. Each software line names the package it came from and the revision of that
  package, because a firmware image — unlike a bracket — is a different file once its package publishes
  again.

``pc convert``
  Convert parts, sketches, assemblies or scenes to another format and update their type in the package.
  Subcommands: ``part``, ``sketch``, ``assembly`` and ``scene``. An assembly converts between ``assy`` and
  ``urdf``: to URDF it writes the ``.urdf`` file and the meshes it references; to ASSY it writes an ``stl``
  part for every URDF link, an interface pair for every joint, and an ``.assy`` that places the parts with
  ``connect:``. A scene converts between ``assy`` and ``world``: to a Gazebo world it writes the ``.world``
  file and the meshes it references; to ASSY it copies every shape the world places into the package as a
  part of its own and writes an ``.assy`` that places them.

``pc export``
  Export a 3D view of parts, assemblies, or scenes. Use ``-a`` for an assembly and ``-S`` for a scene.
  Choose the format with ``-t``:
  ``step``, ``brep``, ``stl``, ``3mf``, ``threejs``, ``obj``, ``gltf``, ``iges``, ``urdf``, ``world``,
  ``mjcf``, or any
  file type a package implements itself (see :ref:`output-files`). Use ``-O`` to set the output directory and
  ``-r`` to export recursively. ``urdf`` writes a ``.urdf`` file plus a directory of the mesh files it
  references, and ``world`` (a Gazebo ``.world``, SDFormat) and ``mjcf`` (a MuJoCo model) write theirs the
  same way -- those are the formats a scene has. ``-e``
  names a further package whose ``export:`` options and implementations are used, which is how one package's
  exporter is applied to another package's objects.

``pc render``
  Render a 2D projection of parts, assemblies, or scenes onto a plane. Choose the format with ``-t``:
  ``svg``, ``png``, ``jpeg``, ``dxf``, ``readme``, ``pdf``, ``html``, or any file type a package implements
  itself (see :ref:`output-files`). ``-e`` works the same way as it does for ``pc export``, reading the
  ``render:`` options from another package.

  ``--with-ports`` draws every port of the object on the projection: a coordinate frame at each, with the long
  arrow along ``+Z`` — the direction a part travels along when it is connected through that port — and the
  name a ``connectPorts:`` would have to use written beside it. ``--with-interfaces`` names each *instance* of
  an interface once, draws a line from that name out to each port that belongs to it, and draws each port's
  boundary sketch where the port is. ``--with-all`` draws both. On an assembly or a scene all three walk
  everything inside it and place each child's ports where it put the child, which is how a connection that
  went wrong is found: two frames that should have met and did not. Every port drawn is also listed in the
  log, with the exact name to write in an Assembly YAML file.

  The options apply to whichever format is being written — the projection is the same one underneath ``svg``,
  ``png``, ``jpeg`` and ``dxf`` — and a package can ask for the same thing permanently, by declaring
  ``with_ports:`` or ``with_interfaces:`` on a file type of its own (see :ref:`output-files`, and
  ``examples/feature_interface``, which keeps four such drawings checked in). ``port_marker_size`` and
  ``port_label_size`` set how big the markers and the names are, as a fraction of the projection's largest
  dimension.

  A port is a coordinate frame rather than geometry, but it is projected like everything else: the axis it is
  offset along is the one a given projection collapses, so two frames a millimetre apart along the line of
  sight are drawn one on top of the other. A port that comes out ambiguous is worth the same second and third
  ``--view`` below that an ambiguous feature is.

  ``--view`` picks the direction the object is looked at from for this one run: ``front``, ``back``, ``left``,
  ``right``, ``top``, ``bottom`` or ``iso``. Each name is shorthand for a pair of vectors, which
  ``--viewport-origin`` and ``--viewport-up`` give as ``X,Y,Z`` instead: the first is where the camera is, the
  second is which way is up in the resulting picture. Either one replaces the vector the name resolved to, so
  ``--view top --viewport-up 0,1,0.5`` tilts the top view without spelling the rest of it out:

  .. code-block:: shell

    pc render -t png --view front -O ./ bracket
    pc render -t png --view top --viewport-up 0,1,0.5 -O ./ bracket
    pc render -t png --viewport-origin 120,-40,60 -O ./ bracket

  All three are the ``viewport_origin`` and ``viewport_up`` of a render file type in ``partcad.yaml``
  (see :ref:`output-files`), passed for one command instead of written down — so they layer on top of whatever
  the package and the object configured, and a file type that does not project (``step``, ``readme``, an
  assembly instruction book) never reads them. PartCAD is Z-up with ``+Y`` pointing away from the front view,
  which is what puts ``+X`` on the right of it.

  A rendered file is named after the object, so several views of one object go into directories of their own
  rather than over each other:

  .. code-block:: shell

    for view in front top iso; do
      mkdir -p ./views/$view
      pc render -t png --view $view -O ./views/$view bracket
    done

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

  Declaring one with a ``path`` says the opposite: that this ``pdf`` is a file of the package's own — a
  drawing, a datasheet — written by that implementation like any other file type, and no instruction book is
  generated over it (see :ref:`output-files`).

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
  Ad-hoc operations that run on the fly, on a file that belongs to no package: PartCAD declares the file in a
  throwaway package of its own, produces one output file, and deletes the package again. Nothing is created and
  nothing is configured. Subcommands, each taking ``part`` or ``sketch``:

  - ``pc adhoc convert`` — write the file back out as another format
    (``pc adhoc convert part bracket.step bracket.stl``).
  - ``pc adhoc render`` — write a 2D projection of it: ``svg``, ``png``, ``jpeg`` or ``dxf``
    (``pc adhoc render part --view top bracket.step bracket.png``).

  Both infer the types from the file names, and take ``--input``/``--output`` to say them outright. ``pc adhoc
  render`` takes the same ``--view``, ``--viewport-origin`` and ``--viewport-up`` as ``pc render`` — and with no
  ``partcad.yaml`` to configure a viewport in, they are the only way to aim one. The output file name may be
  left off when ``--output`` names the type: the file is then named after the input.

  Which of the two to use is which kind of file is wanted, and it is the same distinction as between
  ``pc export`` and ``pc render``: geometry another CAD tool can go on working with, or a picture. A file type a
  package implements itself is available to neither, since there is no package here to declare it in.

  The assembly formats ``assy`` and ``urdf`` are refused by both: an ASSY file is a set of references to the
  parts of a package and a URDF becomes a part per link, so neither means anything without one. Declare it in a
  package and use ``pc convert assembly``, ``pc export`` or ``pc render`` instead.

``pc healthcheck``
  Check the host system for known issues. Use ``--dry-run`` to list the available checks, ``--filters`` to run
  only checks with the given tags, and ``--fix`` to attempt automatic fixes.

``pc search``
  Search for objects by keyword. Subcommands: ``all``, ``parts``, ``sketches``, ``assemblies``,
  ``scenes``, ``interfaces``, and ``packages``.
