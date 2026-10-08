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

An assembly is built out of other assemblies, and the daemon builds those **one at a time, each in a request of
its own**. So asking for an assembly whose sub-assemblies have not been built yet prints a line naming them::

    Building these sub-assemblies first: //pub/examples/partcad/produce_assembly_assy:primitive

and then builds each one before building what you asked for. You will see a ``DONE:`` line per step rather than
one for the whole thing; nothing is built twice, since each one is cached as it is finished. This is why an
assembly that takes many minutes no longer has to fit into a single request, and it is entirely automatic --
there is nothing to turn on and no command of your own to run.

.. _recursive-names:

**********************************
Naming a package and what is below
**********************************

A package name ending in ``...`` means **that package and every package below it**, transitively::

    pc list parts //pub/examples...      # the parts of that package and of everything it imports
    pc install -P //pub/examples...      # prepare all of them
    pc test -P ...                       # test this package and everything below it

``...`` on its own is the current package and everything below it, and ``//...`` is the whole workspace from
the root down. The last path separator is optional, so ``//pub/examples/...`` is the same request as
``//pub/examples...``.

The suffix can also be written on an **object** name, in front of the ``:``, which is what makes it more than
a flag::

    pc render ...:bolt                   # every part named 'bolt', here and below
    pc render //pub/examples...:bolt     # every part named 'bolt' in that subtree
    pc export -a ...:frame               # every assembly named 'frame', here and below
    pc info ...:bolt                     # what each of them is

An object name that carries the suffix also says where the walk starts, so it wins over ``-P`` — the same rule
a fully qualified ``//package:name`` already follows.

A walk over a named object asks every package of the subtree for its **own** object of that name, and passes
over the packages that declare none: a tree of forty packages in which three declare a ``bolt`` is three
renders, not thirty-seven complaints. Finding it nowhere in the subtree is the one failure, and it is reported
once.

``-x``/``--exclude`` leaves a package **and everything below it** out of the walk, and can be given more than
once::

    pc test -P //pub... -x //pub/universe/lego/ldraw    # all of //pub but the LDraw library's twenty thousand parts
    pc list parts ... -x vendor -x experimental         # relative names are relative to the current package

An excluded package is not loaded by the walk at all, which is what makes it worth having for a package served
by a repository plugin: none of the requests its children would have cost are made. It does not make the package
unreachable -- an assembly elsewhere in the tree can still use one of its parts -- only absent from the walk.
Every command that walks a subtree takes it: ``pc test``, ``pc render``, ``pc export``, ``pc lint``, ``pc info``,
``pc sim``, ``pc cam`` and the ``pc list`` commands.

``-r``/``--recursive`` is the older spelling of a ``...`` on the package name and still works everywhere it
did. It cannot say where the walk starts, it is not available on every command that could use one (``pc info``
has none), and the rest of this page is written with ``...``. Note that ``pc supply find -r`` and
``pc supply quote -r`` mean something else entirely — break every assembly down to its parts — and take no
``...``, and so does ``pc instructions -r``, which puts the steps of the sub-assemblies into the instructions.

.. _fast-only:

***********************************
Slow assemblies and ``--fast-only``
***********************************

``pc`` gives up on the daemon when it has said nothing for five minutes. That is a bound on *silence*, not on
the command -- a recursive render reports every object as it goes and can run for an hour -- and building or
rendering one large assembly is exactly a stretch of silence. An assembly (or a scene) that is known to take
longer says so where it is declared, in seconds:

.. code-block:: yaml

  assemblies:
    skyscraper:
      type: assy
      timeout: 1800

While the daemon works on it -- building it, rendering it, exporting it, testing it -- it tells ``pc`` so,
and ``pc`` waits up to 1800 seconds instead of 300 for as long as that lasts. A declared timeout only ever
lengthens the wait, never shortens it, and ``PC_DAEMON_IDLE_TIMEOUT`` still sets the default (``0`` waits
forever, whatever an assembly declares).

Declaring a timeout is also saying the assembly is slow, and ``--fast-only`` (``-f``) leaves out every assembly
and scene that says so::

    pc render --fast-only //pub...       # render everything quick in the whole public index
    pc test -r --fast-only               # test this package and everything below it, the quick parts

It is read from the declaration alone, so leaving an object out builds nothing. An assembly that *places* a
slow one is built by building that one, and is left out only if it declares a timeout of its own. The flag is
offered by ``pc render``, ``pc export``, ``pc test``, ``pc sim``, ``pc list`` and ``pc search``; on ``pc test``
and ``pc sim`` it is ``--fast-only`` alone, since ``-f`` is their ``--filter``. Every recursive run over
``//pub`` in PartCAD's own CI passes it.

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
  - ``pc system status config`` — Dump the configuration this installation resolved, with the configuration
    file, the ``PC_*`` environment and the command line already applied. The same report as ``pc config``,
    beside the two below so that "what is this machine doing" is one command with three answers. An option
    whose value is a secret says only whether it is set; a ``git.auth`` entry keeps its host, username and
    key path and loses its password and passphrase; and the ``user`` section is reported as which of its
    fields are configured, never as the name and addresses in them.
  - ``pc system status env`` — Dump the ``PC_*`` environment variables this ``pc`` process was started with.
    Not the same thing as the report above: the configuration says what an option resolved to, this says what
    the environment asked for, and they disagree whenever a command-line option won or a value was rejected.
    A variable whose name says its value authenticates — ``PC_REMOTE_SANDBOX_TOKEN``, or anything else with
    ``TOKEN``, ``KEY``, ``SECRET``, ``PASSWORD``, ``CREDENTIAL`` or ``AUTH`` between the underscores of its
    name — is listed but printed as ``<scrubbed>``, so the report stays something you can paste into a bug.
  - ``pc system reset`` — Reset all internal state maintained by PartCAD, for example to clear a corrupted
    cache.
  - ``pc system prune`` — Remove the containers and images PartCAD created for the ``docker`` sandbox.
    Only what carries PartCAD's labels (see ``tools/containers/README.md``), so an image somebody else put on
    the machine is never touched — and neither is a third-party sandbox image whose author did not adopt the
    convention, which has to be removed by hand. ``--stale`` narrows it to what is out of date: images built
    for another PartCAD release, and containers nothing is using.
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
    ``--all`` stops every PartCAD daemon on this machine and waits for each to exit, which is what
    the IDE's uninstaller and ``install.sh --uninstall`` run before removing the files a daemon runs
    from; it exits non-zero if one did not stop.
  - ``pc daemon status`` — Display the state of the internal data the daemon holds.
  - ``pc daemon status config`` — Dump the configuration the daemon itself resolved, the daemon-side
    counterpart of ``pc system status config``. The two differ on purpose: a daemon is warm and shared per
    workspace, so its own configuration is whatever its environment held when something first started it —
    possibly days ago, possibly from a VS Code window. It is not what your command ran under (that travels
    with the command, as explained above); it is what the daemon falls back on for a client that sends none.
  - ``pc daemon status env`` — Dump the ``PC_*`` environment variables the daemon process is running with.
    On POSIX this is the one report that cannot be worked out from this side at all, because the shared
    socket daemon inherited the environment of whatever started it. On Windows the client connects to a
    one-shot stdio service spawned as its own child rather than to the named-pipe daemon, so the answer is
    usually the same as ``pc system status env`` — still the environment of the process doing the work, just
    not a different one. Credentials are scrubbed on the far side, so the value never reaches the wire.
  - ``pc daemon reset`` — Drop that state. ``--repo-only``, ``--sandbox-only`` and ``--cache-only`` narrow it
    to the cached dependencies, the sandboxed runtime environments, or the filesystem cache respectively;
    without them all of it goes.
  - ``pc daemon set telemetry`` — Set the daemon's telemetry settings (``type``, ``env``, ``sentryDsn``),
    the daemon-side counterpart of ``pc system set``.

  The three ``status`` reports reach the daemon serving this workspace and start one if none is answering yet
  — there is no reading the configuration or the environment of a process that does not exist. A daemon such
  a command started is one that inherited *this* shell, so ask when the daemon you mean is already up.

  There is no daemon to restart after changing a setting: every command hands the daemon its own resolved user
  configuration, as explained above. Stopping one is for upgrades and for clearing a wedged state.

  .. note::

    On Windows the daemon serves a named pipe rather than a Unix socket, and it is started as a detached
    process rather than by forking; ``pc daemon start``/``stop`` work the same way and print the same kind of
    answer. ``pc`` itself does not use it yet — each command there still runs a service of its own — so what a
    daemon buys on Windows today is the editor extension's warm context.

****************
Package commands
****************

``pc init``
  Create a new PartCAD package (a ``partcad.yaml`` file) in the current directory. Use ``-i`` for interactive
  mode, and options such as ``--desc``, ``--url``, and ``--manufacturable`` to prefill package metadata.

  It also sets up the repository the package is in: a **Render** command in ``.vscode/launch.json``, and the
  AI agent skills that teach a coding agent to drive PartCAD -- the ``pc`` plugin in
  ``.claude/skills/`` for Claude Code, and ``pc-``-prefixed skills in ``.cursor/skills/`` for Cursor. Both come
  out of the installed PartCAD, so they state the version that wrote them. Neither is a reason for the command
  to fail.

  ``--no-skills`` skips the skills. ``--skills-only`` installs *just* them and touches no package at all, which
  is how a repository that has a package already gets them, or gets a newer PartCAD's -- there is nothing to
  create, so an existing ``partcad.yaml`` is neither read nor replaced. ``--agents`` chooses which agents to
  install for: ``all`` (the default), or a comma-separated list of ``claude`` and ``cursor``. An agent PartCAD
  does not know is an error, because a typo that installs nothing looks exactly like an agent that is not
  supported yet.

  Installing again updates what is there and **removes the skills PartCAD has stopped shipping**: a retired
  skill left behind describes a CLI that has moved on, which is worse than no skill at all because the agent
  follows it anyway. Only PartCAD's own are removed -- the Cursor copies carry a ``metadata.partcad`` stamp
  saying which release wrote them, and a ``pc-`` skill without one is somebody else's and is left alone.

``pc install``
  Download everything the current package needs to be built - the PartCAD counterpart of ``npm install``.
  It fetches all imported packages, then prepares every sketch, part and assembly by computing its cache key:
  that downloads the files behind ``fileFrom`` and resolves each alias, enrich, compound and assembly link,
  which loads the packages the objects really depend on. Every piece of :ref:`software` is prepared too, by
  fetching its file - it has no cache key, being a file rather than something built out of one. Nothing is
  built. Use ``-P`` to install a package
  other than the current one, and name it as ``-P <package>...`` to prepare the objects of the packages below
  it too (see :ref:`recursive-names`).

``pc update``
  Force update all imported packages to their latest versions. This updates the packages a package imports;
  to upgrade the PartCAD installation itself, use ``pc upgrade``.

``pc lint``
  Run linting checks on the files within packages. Name the package as ``-P <package>...`` to check the
  packages below it too (see :ref:`recursive-names`), and use
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

  Each takes the package to list as its argument, the current one by default. Name it as ``<package>...`` to
  list the packages below it too — ``pc list parts //pub/examples...`` (see :ref:`recursive-names`).

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
  YAML file), and ``scene`` (import an arrangement file -- a Gazebo world, an MJCF model -- creating the
  parts and an Assembly YAML scene). ``pc import scene -t`` names the format where the file's extension does
  not say, or says the wrong thing, and is how a format a *package* reads is named: ``sim-gazebo:world``,
  ``sim-mujoco:mjcf``.
  ``pc import`` is a one-shot conversion; to keep reading the source file itself,
  declare it as an assembly of the ``step`` type or a scene of that reader's type instead (see
  :ref:`assembly_step` and :ref:`scenes`).

``pc test``
  Run tests on a part, assembly, or scene. Name the package as ``-P <package>...`` to test the packages
  below it too, or the object as ``...:<name>`` to test every object of that name from here down (see
  :ref:`recursive-names`). Use ``-f`` to filter
  by name prefix, and ``-s``/``-i``/``-a``/``-S`` to indicate a sketch, interface, assembly, or scene.
  The tests cover whether the object builds (``cad``), whether it can be manufactured or purchased
  (``manufacturability`` and the methods below it), whether an assembly's connection instructions can be
  followed (``connect``; see "Testing the instructions" in :doc:`assy`), whether the route a machine would cut
  it with can be produced (``cam``; see :ref:`pc cam <cam>`), and whether the engineering analyses a part asks
  for come back clean (``fea`` and ``cfd``; see :ref:`pc cae <cae>`).

  ``manufacturability`` answered to the name ``cam`` until :ref:`pc cam <cam>` existed, at which point one word
  was answering two questions -- "can this be made at all" and "here is the program that makes it". They are
  different checks now, and ``-f`` filters by name *prefix*: ``-f manufacturability`` selects that check and its
  three method-specific siblings, and ``-f cam`` selects the route check alone.

  Three of them ask something else: not whether the object built, but whether what was built is what
  somebody meant. ``shell`` fails a part that came back as a *surface* rather than as a body -- a set of
  faces with nothing said about which side of them is material, which renders and exports like the part
  that was meant while every boolean against it comes back with no solid in it, so interference, CAM, FEA
  and any mass computed from it are wrong. ``degenerate`` fails one that has no size left in some
  direction: a 2 x 2 brick that meshed into a flat disc because a subfile could not be fetched. ``solidity``
  fails one whose faces are oriented inward, which measures the right size and reports a *negative* volume.
  All three are about an object that looks entirely correct in a picture, which is why they have to be asked
  rather than noticed, and none of them needs a solver. ``shell`` needs nothing at all: its answer is read
  straight out of the geometry the object has already produced, so it is asked of every part.

  None of the three can be turned off on an object. A part that is a surface, or has collapsed in one
  direction, or is inside out, is a part nothing downstream can compute with -- whatever it was meant to be --
  and a check an object can exclude itself from is a check that reports on the objects that did not need
  checking. A kind of object that is exempt is exempt on what it *is*: a sketch is not measured for having
  size in every direction, and an assembly is checked through its parts.

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
  ``validation:`` condition each of them states. Use ``-a`` when the object is an assembly, ``-P
  <package>...`` or ``...:<name>`` to run everything the packages below declare too (see
  :ref:`recursive-names`), ``-f`` to run only the simulation of a given name, and
  ``--json`` to print the whole of what each simulation plugin reported. A validation that does not hold
  exits non-zero.

  Where ``pc test`` asks whether a part can be *made*, this asks whether it *works*: it places the object in
  the scene the declaration names, at the ``offset:`` the declaration states, runs the scene through the
  simulation plugin the declaration names, and evaluates the ``validation:`` expression over the ``before``
  and ``after`` the plugin hands back. Nothing needs installing to run one -- the plugin runs in a PartCAD
  sandbox that installs whatever it needs.

  PartCAD implements no simulator: a package imports one and names it in ``simulation:``
  (`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ is the MuJoCo one and
  `partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_ the Gazebo one; each also declares
  the reader, the writer and the ``pc ide open`` entry for that engine's own scene format). The *scene* does
  have a built-in default -- an empty world holding the object -- so a simulation of a part standing on its
  own is a few lines. See :doc:`simulation` and ``examples/feature_simulate``.

``pc info``
  Show detailed information about a part, assembly, scene, or software, including its parameters. Name the
  object as ``...:<name>`` to report every object of that name from here down, or pass ``<package>...`` as the
  package with no object at all to report each package of a subtree (see :ref:`recursive-names`).

  Where the object says what it is made of, the material it names is resolved and reported as
  ``Material`` — the formal and full names, the density both ways round, the coefficient of friction and
  the tags the catalogue states — rather than as the bare reference the configuration beside it already
  shows. A reference nothing answers to is reported as it was written, with the error, which is why no
  mass and no friction came from it. See :ref:`materials`.

  For anything with geometry it also reports what PartCAD **measured** when it built it:
  ``BoundingBox`` as ``min``, ``max`` and ``size`` in millimetres, and -- for anything holding a solid --
  its ``Volume`` in cubic millimetres with ``Solids`` saying how many solids that is the volume of. Neither
  can be read off a declaration: a part is a script, a file or a boolean of two others, and the only way to
  know how big it is, is to have built it. A sketch, a shell or a wire has a box and no volume; a negative
  volume means the faces are oriented inward and is reported as it stands.

  For an object read from a **file**, it also reports what the file itself states -- a STEP part or assembly
  (and a ``kicad`` part, which produces one) its header, products, layers and user-defined properties; a DXF
  sketch its layers, units and the elements carrying extended data. That last is where a sheet metal bend
  states its ``angle``, ``radius`` and ``direction``; see :ref:`sketch-annotations` and :ref:`sheet-metal`.
  Both formats report those pairs the same way, keys lower-cased and values as the file states them, so what
  reads them need not know which format answered.

  Reporting every layer rather than only the ones a sketch reads is deliberate: a layer filter that matched
  nothing and a layer that is not in the file both produce a sketch with nothing in it, and this is what
  tells them apart.

``pc bom``
  Print the bill of materials of a part, an assembly or a scene: what has to be procured to have it, with how
  many of each are needed and, where the object says so, the vendor and the SKU to order it by.

  - A part is what one of it is procured as: the part itself when it declares a ``vendor`` and an ``sku``, or
    says neither how it is bought nor how it is made; the stock it is made from when it has ``manufacturing:``
    instructions -- followed while that stock is made in turn, down to what is bought, and listed with
    ``kind: stock``; and nothing at all when it is made from nothing it names (printed, formed).
  - A sub-assembly that declares a ``vendor`` and an ``sku`` is one line item, ordered whole, and its own
    contents are left out. Any other sub-assembly is expanded into its own bill of materials, by these same
    rules.

  This is the rule ``pc supply`` fills its cart by, so the two agree on every count. Whether a supplier has
  something today is the supply quote's question; the bill of materials goes by what the model declares, and
  answers offline. Use ``-P`` to name the package the object comes from, ``-p <name>=<value>`` to set
  parameters, and ``-j``/``--json`` to produce JSON on standard output instead of a table.
  ``-s``/``--stop-at-purchasable`` is still accepted and changes nothing: a sub-assembly that declares a vendor
  and an SKU is always ordered whole now.

  The :ref:`software` the parts and the assembly ship with is listed under a heading of its own, counted
  apart from the hardware. Each software line names the package it came from and the revision of that
  package, because a firmware image — unlike a bracket — is a different file once its package publishes
  again.

.. _cae:

``pc cae``
  Run an engineering analysis on a part and report what it found. Subcommands: ``fea`` (finite element
  analysis) and ``cfd`` (computational fluid dynamics). Both take one part::

      pc cae fea :bracket
      pc cae cfd -i //pub/feature/cae/openfoam:cfd :duct

  The part says what it is held by and what it carries, in a section named after the analysis. ``fix:`` names
  what is held still — a list of interface types, or a map from an interface type to the instances of it that
  are held. ``load:`` names what is pulled on — a map from an interface type to one value for all of its
  instances, or a nested map naming the instance::

      parts:
        bracket:
          type: build123d
          path: bracket.py
          fea:
            fix:
              - m3-screw          # every instance of it is held
            load:
              hook: 5 kg          # every instance carries this
              rail:
                left: 30 N        # one named instance carries this
                right: 30 N

  A ``load`` value is a **force**. It may be written as a number and a unit — ``n``, ``nm``, ``mn``, ``kn`` or
  ``newton`` for force, ``mg``, ``g``, ``kg``, ``ton``, ``tonne``, ``lb`` or ``pound`` for mass — matched
  case-insensitively, with or without a space in front of it and with or without a plural ``s``. A bare number
  is a **mass in kilograms**, which is what "the shelf carries 5" means. A mass is weighed into a force at
  9.8 N/kg, so what is stored and handed to the solver is always newtons. ``cfd:`` takes the same two keys with
  the same meaning: what is held still, and what force the flow puts on it.

  The model the analysis produces is written to ``<part>.<analysis>.<extension>`` and saved as it stands.
  Which format that is — 3D or 2D — is the implementation's choice, and PartCAD does not convert it. The
  **findings** are the other half of the answer: a JSON array of what the analysis has to say about the part,
  printed as a table, or as the array itself with ``--json``. ``pc cae`` exits non-zero when there is at least
  one, so it can be used as a gate.

  Who runs the analysis is ``<package>:<file type>``. It defaults to the ``caeFeaImplementation`` /
  ``caeCfdImplementation`` :doc:`user configuration <configuration>` options — ``//pub/feature/cae/calculix:fea``
  and ``//pub/feature/cae/calculix:cfd`` — and ``-i``/``--implementation`` overrides it for one run. PartCAD
  ships no solver: an implementation is a package like any other, declared in a ``cae:`` section exactly as an
  export or a render implementation is declared in its own (see :ref:`output-files`), and installed as a
  dependency.

  An analysis that produces no answer is reported the same way by ``pc cae`` and by ``pc test``: which
  implementation was asked, what it said, and which platform it did not work on. The remedies differ — install a
  solver, use another machine, fix the part — and only the implementation's own sentence says which, so it is
  relayed as it stands rather than classified. The command and the check say it identically on purpose: a user
  who ran one of them and then the other must not be told two different things about the same machine.

  ``pc test`` runs the same analyses. Its ``fea`` and ``cfd`` tests apply to a part that declares the matching
  section — and to nothing else, so a package of bolts pays nothing for them. **One thing passes: the analysis
  ran and reported no findings.** A malformed section fails; a plugin that cannot be resolved fails (the
  package is not a dependency, did not load, or declares no such file type — the configuration is wrong
  wherever the package is opened); a plugin that resolves and cannot run fails too, whether what is missing is
  the solver, the mesher, or a sandbox that will not build. That last one is not a skip on purpose: a part
  declaring ``fea:`` has asked a question, and a plugin that answered nothing has failed. So declaring ``fea:``
  in a shared package does make ``pc test`` fail for everyone who has not installed what the implementation
  needs — that is what declaring it means, and a package unwilling to ask that of its readers should not
  declare the section. It is the one verdict ``pc test`` does not remember — installing a solver changes
  nothing a cache key is built from, so a remembered one would go on failing a part that now analyses perfectly
  well.

  **A machine with no container runtime is the one excuse.** An implementation naming a ``container:`` or a
  ``dockerImage`` (see :doc:`configuration`) is saying that a container is how what pip cannot install
  arrives; where there is no container runtime to run it in, nothing was ever asked, and the check skips with
  a ``WARNING`` carrying the whole report. It still declares the requirements that let it run in a ``conda``
  or ``venv`` sandbox, so a host with the non-Python pieces installed natively runs it there and a failure
  there is a failure. An implementation that names no image gets no excuse at all, and a container runtime
  that *is* here removes the excuse for one that does — an image that cannot be pulled or is missing the
  solver is something somebody can fix. A Docker daemon running Windows containers is not one of these
  runtimes: every image PartCAD uses is a Linux image.

.. _cam:

``pc cam``
  Produce the route files of the objects that declare one: the program a machine cuts them with. It takes the
  object's own outline, offsets it by the radius of the cutter, and cuts it at a series of depths -- a 2.5D
  route, which is what a CNC router does to sheet goods and what a mill does to a plate::

      pc cam                    # every object of this package that says how it is made
      pc cam :panel             # one of them
      pc cam -s :nameplate      # one that is a sketch
      pc cam -m laser :gasket   # one that could be made either way, written for the laser
      pc cam -P ...             # this package and everything it imports
      pc cam ...:panel          # every panel from here down

  Unlike ``pc cae``, this is a **package-level** command. An analysis is asked of one part; a route is what a
  package's cut list is made of, so with nothing named ``pc cam`` produces one for every sketch and part of
  the package that says how it is made and passes over every object that does not, silently. Most
  objects are never cut, and a package where three parts of forty are is the ordinary case rather than
  thirty-seven warnings. Naming an object that declares nothing *is* an error: naming one is asking about it,
  and coming back with nothing would look exactly like a route that went somewhere the user did not notice.
  An assembly and a scene are not routed at all -- an assembly is put together rather than cut, and a scene is
  an arrangement of things that were each cut on their own.

  The object says what is cut out of it, and how, in the ``manufacturing:``
  section that already says how it is made -- beside the machine it belongs to::

      parts:
        stock:
          type: build123d
          path: sheet.py

        panel:
          type: build123d
          path: panel.py
          manufacturing:
            method: subtractive
            source: stock
            cnc:
              operation: profile  # around the outside of it
              diameter: 6 mm      # the cutter
              depth_per_pass: 3 mm
              feed: 2400 mm/min
              speed: 18000 rpm

  A key written directly under ``manufacturing:`` is shared by every machine the
  part names; one written inside a machine's own subsection is that machine's
  and outranks it. A part may name several -- ``cnc:``, ``laser:``, ``drill:``
  -- and they are **alternatives**, ways it could be made rather than stages it
  goes through, so ``--machine`` picks which to write for and the programs land
  beside each other as ``panel.laser.nc`` and ``panel.cnc.nc``. A part that
  really is machined in stages is a chain of parts, each naming the previous one
  as its ``source``.

  A *sketch* has one of these sections too, with no ``method:`` in it: a drawing
  is not made from anything, it is a path a machine follows.

  ``operation:`` says which side of the outline the tool runs on. ``profile`` goes around the outside of the
  material and around the inside of every hole, so the object survives at its nominal size -- and cuts the
  holes first, because a profile cut ends by separating the part from its stock and a hole cut after that is
  cut in something that is no longer held. ``pocket`` clears what is inside the outline, ring by ring,
  innermost first so that the wall is cut last by a tool engaged on one side rather than buried in a slot; an
  island in the middle of one is refused rather than cut through. ``engrave`` follows the outline itself,
  offset by nothing, which is what a V-bit or a drag knife wants.

  A length may be written as a number and a unit -- ``mm``, ``cm``, ``m``, ``um``, ``in``, ``inch``, ``"``,
  ``ft``, ``mil`` or ``thou`` -- matched case-insensitively, with or without a space in front of it and with
  or without a plural. A bare number is **millimetres**. A feed may name the length, the time, or both:
  ``2400``, ``2400 mm/min``, ``40 mm/s``, ``60 in/min``; a bare number is millimetres per minute. A spindle
  speed is rpm, with or without the word. What the *file* is written in is a separate question and the
  ``units:`` parameter of the file type: a part 18 mm thick is cut 18 mm deep whether the program says ``G21``
  or ``G20``.

  ``safe_z:`` is a **clearance above the top of the object** rather than an absolute height, so it means the
  same thing wherever the object sits in Z.

  ``depth:`` is the one key with a conditional default. An object that does not say is cut **through**, from
  the top of its bounding box to the bottom. A sketch has no thickness to be cut through, so a sketch that
  does not say how deep to cut is refused. ``diameter:`` has no default at all and must not get one: every
  other parameter has a defensible default, and the diameter of the cutter is the one number that cannot be
  guessed from the part -- a route produced against a diameter nobody chose is wrong by exactly the amount
  nobody noticed.

  Every key of that section is also a parameter of the ``cam:`` file type that produces the route, which is
  what makes it three layers of one namespace: ``//builtin/cam`` underneath, then the package's own ``cam:``
  section, then the object's ``manufacturing:``. So a package cutting twenty parts from one sheet sets the
  cutter once and the one part that needs a smaller one says so for itself. The conversion above happens at
  every layer -- a ``mm/min`` written by the package is understood as surely as one written on the object.

  The route is written to ``<object>.<extension>`` -- ``panel.nc`` -- beside the package, or wherever ``-O``
  says. ``--json`` prints what was produced as the array it is: the file, the implementation that wrote it,
  and whatever that implementation counted about the route. ``pc cam`` exits non-zero if any object it was
  asked about produced no route, and reports every one of them rather than stopping at the first: a route is
  a file, and an object whose section is wrong must not cost the other nineteen theirs.

  Who produces it is ``<package>:<file type>``. Unlike an analysis, PartCAD **ships one** -- a route is
  arithmetic on the object's own outline rather than somebody else's program with a release cycle of its own,
  which is the test ``export:`` and ``render:`` already pass -- so ``camImplementation`` defaults to
  ``//builtin/cam:gcode`` and nothing has to be installed. A controller that wants a dialect of its own is a
  package declaring a file type in its own ``cam:`` section exactly as an export or a render implementation is
  declared in its own (see :ref:`output-files`), named by that option, by an ``implementation:`` in the
  object's own ``manufacturing:`` section, or by ``-i`` for one run -- in that order of precedence, narrowest
  last.

  What the built-in one writes is plain RS-274 with every curve linearized to within ``tolerance:`` of the
  true curve: an arc word is only an arc while the plane it was written in survives the post-processor, and
  one tolerance says exactly what the approximation costs where an arc and a tolerance would say less. Nothing
  in the file is a timestamp, a host name or a version, so the same object and the same parameters produce the
  same bytes on any machine.

  ``pc test`` runs this as its ``cam`` check, and it is the same code: the check produces the route and passes
  the object only if one came back. It applies to an object that says how it is made and to nothing
  else, so a package of bolts pays nothing for it -- the same gate the ``fea`` and ``cfd`` checks have, and
  the same cost model. There is one way to pass: a route was written. A malformed section fails, an
  implementation that cannot be resolved fails, and an implementation that resolved and produced nothing fails
  -- a tool bigger than the hole it was asked to cut, an outline the offset consumed, a sandbox that will not
  build. A machine that cannot provision a sandbox at all is the one thing it does not hold against the object:
  nothing was ever asked there, so it skips, loudly, and does not remember the skip.

  Unlike the analyses, the check does **not** keep what it produced. An analysis writes its model beside the
  package because the model is the answer somebody asked for; a route produced by a check is a by-product, and
  one left beside the package would be indistinguishable from the one this command writes -- checked in by
  accident, or read as current long after the part moved on. So the check routes into a temporary directory and
  deletes it.

  **The check that used to be called ``cam`` is ``manufacturability`` now.** It asks whether an object *can* be
  made or bought at all -- whether the geometry suits the method it declares, whether what it is made from is
  reproducible, whether a supplier could be found -- which is a different question from whether a
  post-processor can produce a program for it. Both are computer-aided manufacturing, which is why one word
  answered for both until this command existed.

  **The outline is a section taken at the bottom of the cut**, and that is the limit worth knowing. For a
  prismatic object -- a panel, a plate, a gasket, anything cut out of stock of one thickness -- it is the same
  outline at every depth. For an object whose cross-section changes over the cut there is no single right
  answer, and the route follows the bottom and says so, as a warning naming how much the two ends differ by:
  a route produced from an outline the user did not expect is the one failure that looks like a success all
  the way to the machine. There is also no lead-in, no tab and no ramp -- the tool plunges at the start of
  each contour and the part is free at the end of the last pass.

``pc convert``
  Convert parts, sketches, assemblies or scenes to another format and update their type in the package.
  Subcommands: ``part``, ``sketch``, ``assembly`` and ``scene``. An assembly converts between ``assy`` and
  ``urdf``: to URDF it writes the ``.urdf`` file and the meshes it references; to ASSY it writes an ``stl``
  part for every URDF link, an interface pair for every joint, and an ``.assy`` that places the parts with
  ``connect:``. A scene converts between ``assy`` and any file format the package graph reads as a scene --
  ``sim-gazebo:world`` and ``sim-mujoco:mjcf`` are the two today, each from its engine's plugin package. To
  such a format it writes the file and the meshes it references; to ASSY it copies every shape the file
  places into the package as a part of its own and writes an ``.assy`` that places them. Which formats those
  are is not a fixed list -- it is whatever the graph declares under ``import:`` with ``scene`` among its
  ``kinds`` -- so a package that teaches PartCAD an arrangement format converts to and from it too.

``pc filter``
  Declare a second assembly (or scene) made of some of the links of an existing one::

    pc filter FILTER SRC DST

  ``FILTER`` names the links to keep -- a JSON or YAML file, or the same written out on the command line --
  and ``DST`` is the new object: the ASSY file of ``SRC`` with everything the filter drops taken out of it,
  written as ``DST.assy`` and declared beside ``SRC``. If ``SRC`` is an assembly then ``DST`` is an assembly,
  and if ``SRC`` is a scene then ``DST`` is a scene; ``-a``/``-S`` settle it only for a package that declares
  both under one name. An existing ``DST`` is overwritten, and ``--dry-run`` says what would be written
  without writing it.

  .. code-block:: shell

    pc filter head.yaml logo logo_head
    pc filter '{bone1: null, bone2: null}' logo logo_bones
    pc filter '[block]' -S bench bench_block

  What a filter is, and what naming a link with and without children means, is the same everywhere it is
  accepted -- see :ref:`assy-filter`, which also covers the ``--filter`` of the two commands below and the
  equivalent in the VS Code viewer. The short of it: a link the filter names is kept, a link it does not name
  is dropped, and a link named with children under it keeps those children only.

  The **file** is filtered rather than the built assembly, so every link kept keeps its ``connect:``, its
  ``how:``, its parameters and its comments, and the result is an assembly somebody can build. That needs an
  Assembly YAML file to work from: an assembly held in a foreign format has no links of its own, and
  ``pc convert assembly -t assy`` is what turns one into a file that does.

  Dropping a link that another link was connected to is the one thing filtering can break, and it is checked:
  every ``connect:`` left pointing at nothing is reported, naming the line, by this command and by ``pc lint``
  afterwards.

``pc export``
  Export a 3D view of parts, assemblies, or scenes. Use ``-a`` for an assembly and ``-S`` for a scene.
  Choose the format with ``-t``:
  ``step``, ``brep``, ``stl``, ``3mf``, ``threejs``, ``obj``, ``gltf``, ``iges``, ``urdf``, or any
  file type a package implements itself (see :ref:`output-files`). Use ``-O`` to set the output directory,
  and ``-P <package>...`` or ``...:<name>`` to export the packages below this one too (see
  :ref:`recursive-names`). ``urdf`` writes a ``.urdf`` file plus a directory of the mesh files it
  references.

  ``--filter`` exports a *part* of one assembly or scene: the links it names, where the assembly put
  them, without writing anything into the package (see :ref:`assy-filter`). It applies to one named object --
  ``-a`` or ``-S`` says which kind it is -- so it is refused for a whole package and for a ``...`` subtree.
  A ``filter:`` on an ``export:`` file type asks for the same thing permanently, per file type, and this
  overrides it for one run.

  ``-t`` also takes a full path, ``-t sim-gazebo:world``, which names the package the implementation lives
  in. That is how a format PartCAD ships no implementation of is reached, and an engine's own scene format is
  exactly that: a Gazebo world (SDFormat) is written by
  `partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_ and a MuJoCo model (MJCF) by
  `partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_, beside the reader and the simulator
  that share their knowledge of the format, so ``-t sim-gazebo:world`` is the spelling that resolves and a
  bare ``-t world`` resolves to nothing. Both write a file plus a directory of the meshes it references, the
  way ``urdf`` does. ``-e``
  names a further package whose ``export:`` options and implementations are used, which is how one package's
  exporter is applied to another package's objects -- the same answer for every file type at once, where
  ``-t <package>:<type>`` is the answer for one.

``pc render``
  Render a 2D projection of parts, assemblies, or scenes onto a plane. Choose the format with ``-t``:
  ``svg``, ``png``, ``jpeg``, ``dxf``, ``readme``, ``pdf``, ``html``, or any file type a package implements
  itself (see :ref:`output-files`). ``-e`` works the same way as it does for ``pc export``, reading the
  ``render:`` options from another package. ``-P <package>...`` and ``...:<name>`` render a whole subtree, the
  same way they do for ``pc export`` (see :ref:`recursive-names`).

  ``--filter`` renders a *part* of one assembly or scene, exactly as it does for ``pc export`` above:

  .. code-block:: shell

    pc render -a -t png --filter head.yaml -O ./ logo
    pc render -a -t png --filter '{bone1: null, bone2: null}' -O ./ logo

  The file it writes is the one an unfiltered render would have written, under the object's own name, so two
  filters of one object overwrite each other -- use ``-O`` to send them to directories of their own. Unlike
  ``pc filter``, this leaves the package untouched and can select inside a link that places another package's
  assembly, because what is filtered is the assembly that was built rather than any file.

  A ``filter:`` on a ``render:`` file type says the same thing permanently and **per file type**, so one
  object can have a picture of one sub-assembly checked in beside the drawing of the whole of it. It is read
  in either place a file type is configured -- the package's ``render:`` section and the object's own -- and
  ``--filter`` overrides it for one run, the way ``--view`` overrides a configured viewport. See
  :ref:`assy-filter`.

  ``--port`` draws one named port rather than every one of them, and is repeated for several. A port is named
  the way the log names it -- its own name for a port of the object, and the path of links then the port for
  one inside an assembly, ``head/head_half_1`` becoming ``head:head_half_1:TL-m3`` -- which is also the path
  the VS Code viewer shows as rows. It says *which* ports rather than that any are drawn, so it goes with one
  of the three options below:

  .. code-block:: shell

    pc render -t png --with-all --with-internals --port bolt:thread-m8 -O ./ logo

  ``--with-ports`` draws every port of the object on the projection: a coordinate frame at each, with the long
  arrow along ``+Z`` — the direction a part travels along when it is connected through that port — and the
  name a ``connectPorts:`` would have to use, joined to it by a line. ``--with-interfaces`` names each
  *instance* of an interface once, draws a line from that name out to each port that belongs to it, and draws
  each port's boundary sketch where the port is. ``--with-all`` draws both. Every port drawn is also listed in
  the log, with the exact name to write in an Assembly YAML file.

  The names are written around the object rather than on it: spread evenly around it, each on the side its
  port is on, and with its line made as long as it takes for no name to land on the object or on another name.

  An assembly is taken at its word: what is drawn is what it says its ports are -- the ones its ``map:``
  externalizes and the ones it declares (see :ref:`assembly-ports`) -- and not everything inside it. That is
  the same boundary ``pc info`` and a ``connect:`` see, and an assembly that externalizes three ports of the
  forty it contains means those three. ``--with-internals`` draws what is inside one anyway, each child's
  ports placed where the assembly put the child, which is how a connection that went wrong is found: two
  frames that should have met and did not. On its own it asks for nothing; it says how deep the three options
  above reach.

  The options apply to whichever format is being written — the projection is the same one underneath ``svg``,
  ``png``, ``jpeg`` and ``dxf`` — and a package can ask for the same thing permanently, by declaring
  ``with_ports:``, ``with_interfaces:`` or ``with_internals:`` on a file type of its own (see
  :ref:`output-files`, and ``examples/feature_interface``, which keeps four such drawings checked in).
  ``port_marker_size`` and
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
  page, the same bill of materials, then a page per assembly step, in the order the Assembly YAML file lists
  the links. Whatever has to be made before a step can be done is explained just before it: a sub-assembly
  gets a page showing it as it should look once it is together, followed by its own steps, and a part that is
  manufactured rather than bought gets a page saying what it is made from, its manufacturing instructions
  written out, and — where it declares a job a route can be produced for (see ``pc cam``) — the route drawn
  from above. Something used in several places is explained once, with how many to make, in the lowest-level
  assembly that holds every place it is used, so it is made before the first step that needs it. ``pc render``
  writes the complete book — every sub-assembly that is built and every part that is — and ``pc instructions``
  below writes as much of it as is asked for. A step page shows the two items being joined, and below them an
  exploded view of the joint with a line drawn across the gap it opens. That gap is half of the largest dimension of the two items,
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

``pc instructions``
  Write the assembly instructions of the assembly named, as ``-t pdf`` (the default) or ``-t html``, into the
  current directory or the one ``-O`` names. It is the book ``pc render -t pdf`` writes, and the one the IDE's
  **Assembly** tab shows and saves; what differs is that it asks how much of it to write:

  * on its own, this assembly's own steps, in the order of its links, with a sub-assembly added as the finished
    thing it is;
  * ``-r``/``--recursive`` puts in the steps of every sub-assembly that is built, each just before the step that
    adds it;
  * ``-b``/``--build-parts`` puts in how to make every part that is built, each just before the step that first
    needs it. Primitive for now: the manufacturing instructions written out, and the route drawn where a part
    declares one.

  What is built and what is bought is what was chosen in the IDE's **Build vs Buy** tab for this assembly,
  which keeps the choices on the machine they were made on, in
  ``~/.partcad/garage/default/bvb/<assembly, escaped>.json``. Where nothing was chosen, a line item that can be
  either is bought, as the bill of materials assumes. The steps and pages come in the very order the IDE's
  **Build** tab lists them in, so a step selected there and a page of the file are the same step.

  The file is written by ``pc`` itself, on the machine it runs on, whichever machine the daemon is on.

  .. code-block:: shell

    pc instructions robot                         # robot.pdf: this assembly's own steps
    pc instructions -t html -r -b -O docs/ robot  # every step and every part made, as HTML

********************
Interacting with IDE
********************

Putting an object in front of a person, in one of two windows -- the IDE's own **PartCAD Viewer**
(``pc ide view``), or **another application** on this machine (``pc ide open``, which is also what the editor
extension's "Open in..." menu runs) -- and asking the IDE what it is showing (``pc ide state``). None of them
leaves anything new in the package: that is what ``pc export`` and ``pc render`` are for. They used to be ``pc inspect`` and ``pc open``. Those names still work, are left out
of ``pc --help``, and print a note on stderr saying what to type instead.

``pc ide view``
  View a part, assembly, or scene in the PartCAD Viewer. Use ``-V`` for a verbal (text) description instead of a visual
  one, and ``-p <name>=<value>`` to set parameters.

``pc ide state``
  Print what the PartCAD IDE on this machine is showing, as YAML (the default) or ``--json``::

    pc ide state                 # YAML
    pc ide state --json          # the same document, for a program to read

  One document, one entry per view:

  * ``explorer`` -- what is selected in the PartCAD Explorer: each row's ``kind`` (``part``, ``assembly``,
    ``package``, ...), its full ``path`` (``//pub/examples:cube``, or a package's own path), what it is declared
    as and the file it is read from.
  * ``inspector`` -- the object the PartCAD Inspector shows: its properties, every parameter it declares with
    what the field holds **now** (``value``), and what the object was last shown with (``applied``). The two
    differ when a value has been typed and Update not pressed. ``live: false`` says the Inspector's panel could
    not be asked -- it is collapsed -- and the values are the applied ones.
  * ``viewer`` -- the PartCAD Viewer: the ``tab`` and ``subTab`` on screen (``design``/``2d``), what every tab
    strip offers and which tabs are disabled, and for **each sub-tab** its ``filters`` -- what it would send
    ``pc render --filter``, or ``null`` for the whole object -- and its ``selections``: the boxes ticked in its
    tree, the port overlays on the 2D tab, and the value of every control in its pane (format, drawing package,
    switches). They differ by sub-tab, which is why each has its own entry. ``screenshot`` is the path of a PNG of
    the sub-tab on screen, written by the IDE into its temporary directory (``/tmp/partcad-viewer-design-2d-<time>.png``
    on Linux); when one cannot be taken -- the panel is closed, or hidden behind another editor --
    ``screenshotError`` says why.

  The IDE is asked over the socket ``pc ide view`` shows things on, so this needs no daemon and no workspace,
  and runs where the IDE does. The 3D view's text callouts are drawn over the canvas rather than in it, so they
  are not in its screenshot. With two VS Code windows open on Linux, the kernel hands the question to one of
  them; ``window.workspaceFolders`` says which one answered.

``pc ide open``
  Open a file in a third-party application, on this machine::

    pc ide open cube.step                       # in a locally installed FreeCAD
    pc ide open --use-docker cube.step          # or in a container, when there is none
    pc ide open --with blender cube.stl         # a mesh, in Blender
    pc ide open --with blender cube.step        # a solid, converted to STL for Blender first
    pc ide open --with gazebo warehouse.world   # a scene, in Gazebo (from partcad-sim-gazebo)
    pc ide open --with mujoco stack.xml         # a scene, in MuJoCo (from partcad-sim-mujoco)
    pc ide open --with kicad Arduino_Nano.step  # a board, in KiCad

  ``--with`` names the application: ``freecad`` (the default), ``blender`` and ``kicad`` for a board are the
  ones PartCAD itself ships. ``gazebo`` and ``mujoco`` come from the plugin package for that engine
  (`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_,
  `partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_), beside the reader, the exporter and
  the simulator for its scene format, so they are offered in a workspace that imports one and are an unknown
  application anywhere else. A locally installed one is always
  used when there is one: the command looks on the ``PATH``, in ``/Applications`` on macOS, under
  ``Program Files`` on Windows, and for a flatpak on Linux. Gazebo is looked for under all three of the names
  it has had (``gz sim``, ``ign gazebo``, ``gazebo``), and whichever the machine has is the one used.

  **``pc ide open`` waits for the application to close**, and then brings back what was done in it. Each application
  declares what it opens, best first (``formats:`` in its ``open:`` entry -- FreeCAD's is ``fcstd``, ``step``,
  ``brep``, ``iges``, ``stl``, ``obj``; Blender's is ``blend`` and the meshes it imports). A file already in one of
  them is opened as it is. Any other is converted to the first one PartCAD can write, and the application is
  given that: a STEP file, a CadQuery script or a 3MF mesh reaches Blender as STL, and a build123d script
  reaches FreeCAD as STEP. Converting is the one thing ``pc ide open`` asks the PartCAD daemon for, because turning
  a solid into a mesh is CAD work; the window still opens on the machine the command was run on. The converted
  copy is written under this workspace's own directory (never beside your file), named after the object it
  came from, and reused until that object changes. ``--type`` says what the file holds when its name does not
  -- a ``.py`` is a CadQuery script, a build123d one or an SDF one -- and the VS Code extension passes the
  declared type of the object you clicked.

  When the application closes, the file it was given is compared with what it was before:

  * **Unchanged** -- nothing happens, and ``No changes.`` says so.
  * **Changed, and opened as it is** -- the edit is already in your file.
  * **Changed, and converted first** -- the edited copy is converted back into the object's own format and
    written over its source, when that source is a file PartCAD can write (``step``, ``brep``, ``stl``, ``3mf``,
    ``obj``, ``iges``, ``gltf``). A script is not: its edit is kept where it was made and the path is printed,
    because overwriting the program that generates a part with its output would destroy the program.

  An application that saves beside what it opened -- KiCad -- has its whole directory compared rather than
  the one file. Interrupting ``pc ide open`` (``Ctrl+C``) stops the wait and leaves the application open; what is
  saved in it from then on is not brought back.

  MuJoCo reads MJCF and no other model format, and a scene that is not already one is **not** converted here.
  That is not an omission: MJCF is written by ``partcad-sim-mujoco``'s exporter and a Gazebo world is read by
  ``partcad-sim-gazebo``'s reader, and a file handed to ``pc ide open`` has no package around it to reach either
  through. So such a file is refused with the export that does work rather than converted wrongly. An
  application's ``open:`` entry names the extensions its own format is stored in (``sceneExtensions``), which
  is how a file that already is one goes straight over without any conversion at all.

  An object that only means something inside a package -- an ASSY file, a URDF -- has nothing to convert
  ad-hoc, and is refused with that for the same reason: export it to a mesh first (``pc export -t stl``), or
  a scene to its engine's format (``pc export -S -t sim-mujoco:mjcf``), and open that.

  KiCad is handed the board rather than the file named, when the two are not the same: a ``kicad`` part *is*
  the STEP file KiCad's command line writes out of the board, so ``pc ide open --with kicad`` on it opens the
  ``.kicad_pro`` (or ``.kicad_pcb``, or ``.kicad_sch``) beside it. Nothing is created here and nothing is
  rendered -- a file with no board beside it is handed over as it is. Every application but Blender is given
  the file it was pointed at, whatever it holds.

  With ``--use-docker``, a machine that has no local installation runs the application in a container instead,
  started the way PartCAD starts every container (see :ref:`useDockerRemote <use-docker-remote>`): named
  ``partcad-open-<application>-<tag>-<identity>``, labelled so that ``pc system prune`` removes it, replaced
  rather than reused when what it was created from has changed, and running PartCAD's own container service,
  through which the application is launched. The image is the one the application's ``open:`` entry declares
  under ``container:`` (``--docker-image`` overrides it): FreeCAD's is ``linuxserver/freecad:latest``, since the
  FreeCAD project publishes no image of its own, Blender's is ``linuxserver/blender:latest`` for the same
  reason, KiCad's is the ``ghcr.io/partcad/partcad-container-kicad`` image PartCAD already builds for
  ``kicad`` parts, and an engine's is whatever its plugin package declares. The application's own settings
  live in a volume of their own (``partcad-open-<application>-home``), so they outlast the container. Without
  ``--use-docker``, a machine with neither the application nor Docker is told so rather than being left with a
  command that quietly did nothing.

  The file reaches the container one of two ways, and ``useDockerRemote`` chooses:

  * **mount** (the default) -- the directory holding the file is mounted at the path it has on the host, so one
    path means the same thing on both sides, and the application saves straight into it. In a dev container
    holding the host's Docker socket, each directory is bound from where the host's daemon keeps it -- the
    workspace's bind, ``/tmp``'s volume -- at the path it has in the dev container, which is how the ``docker``
    Python sandbox binds them too. A file on none of the dev container's mounts is refused with the ways out
    (mount it, ``PC_DOCKER_MOUNT_SOURCES``, or ``useDockerRemote``). Outside any workspace, only the file's own
    directory is mounted -- not the directory the command was run from.
  * **upload** (``useDockerRemote: true``, or ``PC_USE_DOCKER_REMOTE=true``) -- nothing is mounted. The file (or,
    for KiCad, its directory) is sent with the request that launches the application, and what it is when the
    application closes is sent back and written here. This is what a Docker daemon on another machine needs.
    A ``fileArgs`` template that quotes the path inside a script (``{path_repr}``) cannot be sent this way and is
    refused; ``{path}``, the path as an argument of its own, can.

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

  One of them is about this repository rather than the host: ``AgentSkills`` compares the AI agent skills
  installed here against the PartCAD running, and reports the ones an older release wrote. ``pc upgrade``
  replaces PartCAD and leaves them where they are, so without this an agent goes on reading instructions for a
  CLI that has moved -- silently, since a stale skill looks exactly like a current one. ``--fix`` reinstalls
  them, for the agents that had them and no others.

``pc search``
  Search for objects by keyword. Subcommands: ``all``, ``parts``, ``sketches``, ``assemblies``,
  ``scenes``, ``interfaces``, and ``packages``. ``-P`` names the package to search, the root package by
  default; ``-P <package>...`` searches the packages below it too (see :ref:`recursive-names`).

  ``pc search parts`` and ``pc search assemblies`` also take ``-i``/``--interface``, which searches by what
  an object *connects by* rather than by what its declaration says: ``pc search parts -i m4-thru`` finds
  every part with a 4mm through hole, and finds the ones that implement ``m4-thru-3`` or any other interface
  derived from it, because a part with a 3mm-thick 4mm through hole is a part with a 4mm through hole. An
  abstract interface is therefore the most useful thing to search by -- it is the name a whole family is
  known by. A bare name is the interface this package declares, and ``//package:name`` is any other.

  The answer comes from the declarations -- ``implements:``, and an assembly's ``map:`` -- so nothing is
  built and nothing is instantiated to produce it; the interfaces named in those declarations are resolved
  once per package and kept for the rest of the run. ``--keyword`` and ``--interface`` may be given together,
  and then both have to hold.
