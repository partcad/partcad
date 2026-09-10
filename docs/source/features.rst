Additional Features
###################

============================
Visual Studio Code extension
============================

The PartCAD extension for Visual Studio Code is the primary graphical interface to PartCAD. It adds a PartCAD
workbench with an Explorer view for browsing packages and an Inspector view for viewing objects and editing
their parameters. Install it from the
`VS Code marketplace <https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad-official>`_. See
the :doc:`tutorial <tutorial>` for a step-by-step walkthrough.

The extension exposes the following actions from the Explorer view and the command palette:

Packages
--------

- **Initialize new package** — Create a ``partcad.yaml`` package in the current workspace (a custom-path
  variant is also available).
- **Open package** — Open an existing package.
- **Reload the package** and **Restart PartCAD** — Refresh the view or restart the PartCAD backend after a
  change.
- **Update PartCAD** — Update the PartCAD installation used by the extension.

Objects
-------

- **Add** a part, assembly, scene, sketch, or interface.
- **Import** a part, assembly, scene, or sketch from an existing file.
- **Display** (inspect) a part, assembly, scene, sketch, or interface in the ``PartCAD Viewer``; parts can
  also be opened for display and editing together, or their source edited directly.
- **Test** a part, assembly, or scene.
- **Open in >** — Open the object's own source file in the application that made it: **FreeCAD** or
  **Blender** for a part or an assembly, **Gazebo** for a scene of type ``world``, **KiCad** for a part of
  type ``kicad``. This runs
  on your machine rather than on the daemon: the extension runs ``pc open`` (see :doc:`cli`), which starts an
  application installed here, or runs one in a container when there is none and ``partcad.open.useDocker``
  is on. Blender reads meshes, so an object that is not one is converted to STL on the way.

The Explorer also lists the ``software`` a package ships. Selecting one shows its path and its ``fileHash``
in the Inspector and leaves the ``PartCAD Viewer`` as it is: software is a file, not geometry, so there is
nothing to render.

The PartCAD Viewer
------------------

Displaying an object opens the ``PartCAD Viewer``, which is a strip of tabs over that one object rather than
a bare canvas. Which tabs appear depends on what is being shown, and the 3D view is always the first:

- **3D** — the shape itself, tessellated by PartCAD and drawn here. Always present.
- **Bill of Materials** — for an assembly or a scene: every part it is made of, recursively, counted.
- **Instructions** — for an assembly that declares its steps: the assembly guide, step by step.
- **FEA** and **CFD** — for a part: the analysis :ref:`pc cae <cae>` runs, and what it found.
- **Supply** — what the objects in view can be bought from, and a quote per supplier.

The 3D view arrives over the viewer protocol from whichever ``partcad`` asked for the shape to be shown; the
other tabs are questions put to the PartCAD daemon, fetched the first time the tab is looked at and cached
until the next object is shown. An object that belongs to no package gets the 3D view alone.

The two analysis tabs are the exception to "questions": looking at one *runs* the analysis. A field over the
model names which implementation runs it — pre-filled with the configured default, and editable, so a machine
whose solver is elsewhere is one line away from an answer rather than stuck on an error. The model is drawn
according to the format the implementation chose: a 3D result is turned and zoomed, a 2D one is panned and
zoomed as a picture. Any findings are listed under it; a part with nothing to report gets the whole pane.

Export
------

Objects can be exported directly from the extension to any of the following formats: **SVG**, **PNG**,
**JPEG**, **STEP**, **STL**, **3MF**, **ThreeJS**, **OBJ**, **IGES**, and **glTF**. A scene can also be
exported as a **Gazebo world** (SDFormat).

.. _engineering-analysis:

====================
Engineering analysis
====================

A part can say what holds it and what it carries, and PartCAD can put that
question to a solver: ``pc cae fea`` for a finite element analysis, ``pc cae
cfd`` for computational fluid dynamics. The conditions live on the part, in a
section named after the analysis, because they are a property of the part rather
than of whoever analyses it -- a bracket is bolted down at the same holes
whichever solver is asked about it:

.. code-block:: yaml

  # partcad.yaml

  parts:
    bracket:
      type: build123d
      path: bracket.py
      fea:
        fix:
          - m3-screw        # every instance of this interface is held still
        load:
          hook: 5 kg        # every instance of this one carries this
          rail:
            left: 30 N      # or one named instance at a time
            right: 30 N

``fix:`` and ``load:`` name :ref:`interfaces <interfaces>` the part implements,
so the same declaration that says where a part connects also says where it is
held and pulled. A ``load`` is a force: write a number and a unit, or a bare
number for a mass in kilograms, which PartCAD weighs into newtons at 9.8 N/kg.
``cfd:`` takes the same two keys with the same meaning.

PartCAD ships no solver. The analysis is run by an implementation package,
declared in a ``cae:`` section exactly as an export or a render implementation is
declared in its own (see :ref:`cae-section`), and named by the
``caeFeaImplementation`` / ``caeCfdImplementation`` user configuration options --
``//pub/feature/cae/calculix:fea`` and ``//pub/feature/cae/calculix:cfd`` by
default, which are `CalculiX <https://www.calculix.de/>`_ (see
`partcad-cae-calculix <https://github.com/partcad/partcad-cae-calculix>`_ for
what it needs and what every parameter means -- it names a ``dockerImage``
carrying its solver and mesher, so a container runtime is all it asks of a host
that has neither installed). ``pc cae fea --implementation`` overrides it for one run, and so does
the field over the model in the IDE's FEA tab.

A part may also name its own, which is what it was written against:

.. code-block:: yaml

    fea:
      implementation: //pub/feature/cae/calculix:fea
      fix: [m3-screw]
      load: {hook: 5 kg}

That sits between the other two: ``-i`` on the command line wins, then the part,
then the user configuration. It is how a package ships an analysis that works
for whoever opens it, without every reader first pointing their own
configuration at the right place.

A **relative** package name here -- ``calculix:fea`` rather than
``//pub/feature/cae/calculix:fea`` -- means the package this one imported under
that name, and is resolved from the package the declaration is written in. That
is not where a name a *user* types is resolved from: ``pc cae fea -i
calculix:fea`` means the ``calculix`` beside the user, like every other name a
command line carries. The difference matters under ``pc test -r`` over a tree of
packages, which runs with the tree's root current while every part in it sits one
or more packages below.

What comes back is two things: the model, written to
``<part>.<analysis>.<extension>`` in whichever format the implementation chose,
and the **findings** -- a JSON array of what the analysis has to say about the
part. ``pc test`` gains an ``fea`` and a ``cfd`` check that fail a part whose
analysis produced any finding, and they apply only to a part that declares the
matching section, so a package of bolts pays nothing for them. There is one way to pass -- the
analysis ran and reported nothing -- and everything else **fails**: a malformed
section, a plugin that cannot be resolved (not a dependency, misspelt, declaring
no such file type), a plugin that resolves and cannot run (no mesher, no solver,
a sandbox that will not build, a crash), and an analysis that ran and found
something.

Not running is deliberately not a skip. A skip says the question does not apply
here; a part that declares ``fea:`` has asked, and a plugin that was asked and
delivered nothing has failed. The consequence is the point: declaring ``fea:``
in a shared package makes ``pc test`` fail for everyone who has not installed
what that implementation needs. A package that does not want that should not
declare the section. What the failure carries is *why* -- the implementation's
own sentence, plus which implementation was asked and which machine it did not
work on, because "gmsh is not installed" is a puzzle and the same sentence under
``//pub/feature/cae/calculix:fea on Linux-aarch64`` is an answer.

There is **one** excuse, and it is the case where the implementation was never
given the environment it says it needs. An implementation naming a ``container:``
or a ``dockerImage`` is stating that a container is how what pip cannot install
arrives; on a machine with no container runtime that statement has nowhere to
land, nothing was ever asked, and the check skips with a ``WARNING`` carrying the
whole report rather than failing. It is narrow in both directions. An
implementation that names no image gets no excuse at all -- it said it runs in an
ordinary sandbox, and a machine with a working sandbox is a machine it was
supposed to work on. And a container runtime that *is* here removes the excuse
entirely: a registry that cannot be reached, an image that will not start, a
solver missing from the image are all things somebody can fix, and calling them
"unavailable" would hide exactly the failures a plugin's own CI exists to catch.

A Docker daemon running **Windows** containers does not count as a container
runtime for this, or for choosing a sandbox. Every image PartCAD builds, pulls or
documents is a Linux image, and such a daemon answers a ping and then fails every
pull with ``no matching manifest for windows/amd64``.

``examples/feature_cae`` is the pair of cases to check an implementation against
— a cantilever and a pipe, each with a closed-form answer to compare the solver
with. Against CalculiX the cantilever reads 0.1655 mm where the model predicts
0.16-0.18 mm. The pipe declares no ``cfd:`` section: CalculiX's CFD solver
diverges on it, a part that declares a section has asked a question, and an
example that ships a check nothing can turn green is one readers learn to scroll
past. The declaration is written out beside the part, and that example's
``README.md`` has the measurement.

See :ref:`pc cae <cae>` for the command and the units it accepts.

=============================
Procurement and Manufacturing
=============================

PartCAD currently supports two types of providers (entities that can provide
parts and assemblies): ``store`` and ``manufacturer``.
``store`` can be used to quote and order parts from existing lists:
by ``vendor`` and ``SKU``.
``manufacturer`` can be used to quote and order parts by using their 3D model
(for example, by 3D printing them).

.. code-block:: yaml

  # partcad.yaml

  parts:
    existing_part:
      vendor: homedepot # for example
      sku: ...
      count_per_sku: 25 # if it's sold in packs of 25
      ...
    new_part:
      manufacturing:
        method: additive
      parameters:
        color: black
        material: //pub/std/manufacturing/material/plastic:pla
      ...

Assemblies that are sold in an assembled state are declared the same way, using
``vendor`` and ``sku`` on the assembly itself.

See :ref:`procurement` for more information about declaring purchasable objects,
and :ref:`providers` for more information about the providers and how PartCAD
selects them.

In the future, PartCAD will support ``assembler``, which is supposed to produce
an assembly given assembly instructions and using parts ordered from
``store``-s and ``manufacturer``-s.

Currently, the provider has to be explicitly specified in the quote or order
request, or explicitly specified as one of the suppliers in the package where
the parts are declared:

.. code-block:: yaml

  suppliers:
    myGarage:                     # a provider of this package
    ../provider_store:myGarage:   # one next door
    //vendor/store:myGarage:      # one anywhere

A supplier is written from the point of view of the package that lists it, and
is resolved against that package the way every other reference it makes is: a
bare name is one of its own providers, while a qualified one lets it buy from a
provider defined elsewhere instead of declaring one of its own. In the future PartCAD will be able to select providers
based on the location and preferences of the requester, while leaving the
possibility to enforce the use of a specific provider for corresponding parts
(for example, for parts that are using a patented design).

.. _python-sandbox:

==================
The Python sandbox
==================

Every CAD script PartCAD runs -- a ``cadquery`` or ``build123d`` part, the
importer that reads a ``STEP`` file, a ``render:`` or ``cam:`` implementation --
runs in a sandbox rather than in the interpreter PartCAD itself is running on.
That is what lets one package render against build123d 0.11 while another wants
0.9, and what keeps a CAD stack out of the environment you work in.

``pythonSandbox`` chooses how that sandbox is built:

==================== =========================================================================
``docker``           A container, with your files mounted into it. The default wherever a
                     container runtime answers, because it is the only one whose result does
                     not depend on what the host happens to have: the interpreter, the
                     compilers and the native libraries all come from an image somebody
                     built once and published. It is also the only sandbox a package can
                     bring **non-Python** dependencies to, by naming its own image -- see
                     :ref:`docker-sandbox` below.
``conda``            An environment conda provisions, **interpreter included**. The default
                     where there is no container runtime and conda or mamba is installed --
                     and in the :ref:`standalone tools <standalone-cli>`, the
                     :ref:`snap <snap-package>` and the :ref:`PartCAD IDE <partcad-ide>`,
                     which carry a conda of their own and use yours in preference to it when
                     you have one. What it provisions depends on your channels, your package
                     cache and your platform, which is why it is no longer the first choice
                     where a container is available.
``venv``             A plain virtual environment of PartCAD's own, one per interpreter
                     version, under the internal state directory. The default when neither a
                     container runtime nor conda is installed. Built from whichever Python
                     the host has, so a package asking for a version the host does not have
                     is rendered on the host's and told so -- and so not something the
                     standalone tools can fall back to, since the machine they exist for is
                     the one with no Python.
``remote``           A container that does **not** share a filesystem with PartCAD: the
                     inputs are sent to it and the outputs are sent back. This is what a
                     sandbox on another machine needs. Chosen rather than fallen back to,
                     and it needs ``remoteSandbox`` to say where the service is. See
                     :ref:`remote-sandbox` below.
``none``             No environment at all: scripts run on the host's own interpreter and
                     their dependencies are installed **into it**. Fast and shares whatever
                     is already there, at the price of writing the CAD stack into the Python
                     you work with -- and unusable where that Python is not writable.
``pypy``             A conda environment built around PyPy.
==================== =========================================================================

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    pythonSandbox: venv

The equivalents everywhere else are ``PC_PYTHON_SANDBOX`` in the environment and
``--python-sandbox`` on the command line, in the usual order of precedence.

Which one is chosen for you, when you have said nothing, is the first of
``docker``, ``conda`` and ``venv`` that this machine can actually provide. A
continuous integration runner with no container runtime therefore keeps
provisioning with conda exactly as before, and needs no configuration to say so.

"Can actually provide" includes the image. A container runtime answering says a
container could be started; it says nothing about whether the image to start it
from can be pulled, and on a machine that is offline, behind a firewall, or
simply not permitted to reach the registry those are different answers. So
PartCAD checks, once, and falls through to ``conda`` or ``venv`` with a warning
rather than failing every part against a registry you never asked it to talk to.

That fallback is only ever for a choice PartCAD made. Say ``pythonSandbox:
docker`` yourself and it is obeyed: an image that cannot be had is then a
failure, because being unable to do what was asked is not a reason to quietly do
something else.

.. _docker-sandbox:

The ``docker`` sandbox
----------------------

The container is a place to run the interpreter, not a place to keep your work.
What it can see is whatever PartCAD bind-mounts into it, and that list is kept
as short as it can be -- on an ordinary machine, two directories:

* your **home directory**, which already contains most of the rest;
* the **temporary directory**, because things land there without asking to be
  mounted -- an ad-hoc command's generated package, a factory's intermediate --
  and one fixed mount is simpler than arranging for nothing to be temporary;
* the **context root** -- the package tree the command is working on;
* **the internal state directory** (``~/.partcad`` by default), which is where
  the sandbox environments, the caches and the fetched dependencies live;
* **PartCAD's own installation**, because the interpreter over there is handed
  PartCAD's scripts by path and has to be able to open them.

Nested directories are mounted once, by the outermost of them, since two views
of one directory leave it undecided which a write lands in. So when the package,
``~/.partcad`` and the installation are all under your home directory -- which
is the usual arrangement -- those three collapse into it, leaving the home
directory and the temporary one. On Windows even that is a single mount, since
the temporary directory lives inside the user profile; on Linux and macOS it
does not, so there are two. The rest are still named because they are not
always under either: a package on another volume, a system-wide installation, a
file an ad-hoc command was pointed at somewhere else.

That is not tidiness. A mount set that does not vary from one context to the
next is a container that never has to be replaced, which is what lets one
container serve every package you work on and keep serving it after ``pc``
exits.

Everything is mounted **writable**, your home directory included. Mounting the
installation read-only was tried and taken back out: it bought little -- a
wrapper is read and executed, and what it writes goes to the cache or back over
its own protocol -- and cost one more thing that could differ between two
containers of one image. The isolation worth having here is the container; the
mounts exist so that a path a wrapper is handed means something on the other
side, and that is a stopgap rather than a security boundary.

On a POSIX host all of them are mounted **at the same paths they have
outside**, so a path in a log, in an error, in a cached artifact or in a
``.frd`` a solver wrote means the same thing on both sides and nothing has to
be rewritten.

That is not available on Windows and never was: ``C:\Users\you\.partcad``
is not a path a Linux container can have, so a drive letter is mapped the way
Docker Desktop maps it (``C:\Users\you`` becomes ``/c/Users/you``) and
PartCAD rewrites the command line on the way in. So identical paths are a
property of POSIX hosts rather than of the design, and translating them is
machinery PartCAD already has rather than a line it will not cross -- worth
knowing before treating "the paths must match" as a constraint on some future
change to how the mounts are chosen.

The container is named after the **image** and nothing else, so it outlives the
process that started it: the next ``pc`` command finds it warm rather than
paying to start one, and only a new version or image tag makes it a different
container. It carries PartCAD's labels, so ``pc system prune`` clears out the
ones a machine has stopped needing.

Because the state directory is mounted rather than copied, ``pip`` installs
persist across container restarts and the environment locking, the install
guards and the cache all work unchanged. Sandbox environments are named after
the image that built them, so a package rendered against one image never reuses
what another installed -- what ``pip`` resolves and compiles depends on the
native libraries underneath it, and two images do not have the same ones.

.. _remote-sandbox:

The ``remote`` sandbox
----------------------

``remote`` makes no assumption that the container can see your disk. The
directories a command needs are packed up and sent to it, and the files it wrote
are sent back. That costs a copy per run, and it buys a sandbox that can be
anywhere -- another machine, another architecture, a build farm.

It is served by ``partcad-service-remote-docker``, which accepts those requests,
starts and reuses a container per image, multiplexes callers onto it and retires
it when nobody is using it. That service exists; run it with ``--host`` and
``--port`` to say where.

**It runs commands, so who may reach it matters.** A request names the image,
the requirements and the command, and the sandbox interpreter runs whatever
Python it is handed -- on a reachable address that is a shell for anybody who
can reach the port. So it binds loopback by default, and it **refuses to start**
on any other address without ``--token`` (or ``PC_REMOTE_SANDBOX_TOKEN``), which
every request must then carry as ``Authorization: Bearer <token>``. Refused at
start-up rather than warned about: somebody who passed ``--host 0.0.0.0`` is not
going to read the log of a service that came up and appeared to work. Prefer the
environment variable to the flag, since process arguments are readable by anyone
on the machine.

The service owns the environment, and that is the arrangement worth knowing. A
sandbox is a virtual environment on a disk, and for ``remote`` that disk cannot
be the caller's -- so the service builds it in a Docker volume, installs into it,
and prepends its interpreter to whatever was asked for. The client never learns
where it is. Guards saying "numpy is installed" belong on the same disk as the
numpy they describe.

Which directories a command needs are worked out from the command: any argument
naming a file on this machine contributes the directory it is in, because a
script needs the siblings it imports. What a command *writes* cannot be inferred
that way, so a caller producing a file names it, exactly as it does for a
container.

Point a client at it with ``remoteSandbox`` (or ``PC_REMOTE_SANDBOX``), as
``host:port``, and give it the service's token with ``remoteSandboxToken`` (or
``PC_REMOTE_SANDBOX_TOKEN``) where the service was started with one. There is no
default for either: guessing at a service that runs commands is not something to
do on somebody's behalf.

**Off this machine, that has to be encrypted.** Every request carries the token
and the package's own source, so PartCAD refuses to send one to an address that
is not loopback over plain HTTP. Two ways to satisfy it: put the service behind
a TLS-terminating proxy and write ``https://host:port``, or reach it through a
tunnel -- SSH, WireGuard, whatever the network already has -- and point
``remoteSandbox`` at the near end, which is loopback and stays plain. A
container PartCAD starts on this machine is loopback too, and a certificate
between a process and its own container would secure nothing.

Today the transfer is a whole directory at a time; the intent is to replace that
with a filesystem the container mounts and pulls files through one at a time, at
which point ``remote`` becomes as cheap as ``docker`` and stops being a trade.

Containers PartCAD manages
--------------------------

Every image PartCAD builds is labelled as its own, and ``pc system prune``
removes the images and containers carrying those labels -- never anything else
on the machine. ``pc system prune --stale`` removes only what is out of date:
images from PartCAD releases other than this one, and containers nothing is
using.

Third-party images are asked, by convention, to carry the same labels. An image
that does not is still usable; it simply cannot be told apart from the rest of
what you have installed, so ``pc system prune`` leaves it alone.

.. _caching:

=======
Caching
=======

PartCAD is capable of caching intermediate and final results of all model compilations.
This can be particularly useful when working with large models or when scripting languages
(like OpenSCAD, CadQuery, build123d, Chili3D or sdf) are used.

Anything PartCAD produces in a sandbox is cached under the environment that
produced it as well as under its own inputs: the interpreter version and the
versions of the CAD libraries installed alongside it. That covers parts and
sketches written as scripts, and equally parts read from CAD files, since the
importer that turns a ``STEP`` file into geometry is itself a script in a
sandbox. Moving a package to another Python or Node.js, or to another version of
Chili3D, therefore re-renders rather than serving what the previous environment
built. ``pc info`` reports that environment for the objects that have one; an
assembly does not, because it is composed from objects that each carry theirs.

At the moment code-CAD caching is experimental and can be enabled by using the following configuration:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    cacheDependenciesIgnore: True

Cache tiers
-----------

The cache is a hierarchy of tiers, each with its own switch, because what is
worth keeping in memory is not what is worth a file, and neither is what is
worth a network round trip:

======================= ============================================================ ==========
Tier                    Where it keeps things                                        Default
======================= ============================================================ ==========
``cacheMem``            This process's memory. Nearest, and lost on exit.            on
``cacheFiles``          A directory under the internal state directory. Local.       on
``cacheRemote``         A memcached server, shared by a team or a CI fleet.          off
``cacheS3``             An S3 bucket, which outlives all of the above.               off
======================= ============================================================ ==========

A read walks them in that order and stops at the first hit; a write offers the
entry to every tier whose size window accepts it. The two shared tiers are off
by default because they need an address that only a deployment can supply:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    cacheRemote: True
    cacheRemoteServer: memcached.example.com:11211

    cacheS3: True
    cacheS3Bucket: my-partcad-cache
    cacheS3Region: us-east-1

Each tier also takes ``...MaxEntrySize`` and ``...MinEntrySize`` to set the
window of object sizes it accepts, and the memcached tier takes
``cacheRemoteNamespace`` and ``cacheRemoteExpiration``. ``cacheS3`` additionally
accepts ``cacheS3Prefix`` and ``cacheS3EndpointUrl``, the latter for an
S3-compatible store that is not AWS.

``cacheRemote`` needs nothing installed. ``cacheS3`` needs the ``aws`` extra
(``pip install -U 'partcad[aws]'``); enabling it without that reports an error
naming the package to install and leaves the remaining tiers working. See
:doc:`installation` for both.

========
Security
========

As code-CAD is gaining popularity in the community, the topic of supply chain
security and the risk of running arbitrary third-party code is not sufficiently
addressed. PartCAD aims to close that gap for open-source software in a way
that exceeds anything commercial software has to offer at the moment.

PartCAD is capable of rendering scripted parts in sandboxed environments:
``CadQuery``, ``build123d`` and ``sdf`` use Python, and ``Chili3D`` uses
JavaScript.

At the moment it is only useful from a dependency management perspective
(it allows third-party packages to bring their Python and npm dependencies
without polluting your own environments),
in the future, PartCAD aims to achieve security isolation of the sandboxed
environments. That will fundamentally change the security implications of using
scripted models shared online.

=========
Telemetry
=========

Public Repositories
-------------------

By default PartCAD collects telemetry data to improve the user experience and to help
understand how the tool is being used. The data collected includes the
following:

- What commands are being run?
- How much time is consumed by each step?
- What errors and exceptions are being raised?

PartCAD uses `OpenTelemetry <https://opentelemetry.io/>`_ to collect telemetry data.
You can disable telemetry by setting the following configuration:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    telemetry:
      type: none

Alternatively, you can disable telemetry by setting the following environment variable:

  .. code-block:: bash

    PC_TELEMETRY_TYPE="none"

You can also change telemetry settings using CLI:

  .. code-block:: bash

    pc system set telemetry type none
    # or, if you want to collect data about PartCAD performance in your organization:
    pc system set telemetry type sentry
    pc system set telemetry env <you-org-name>
    pc system set telemetry sentryDsn <your-sentry-dsn>

Private Repositories
--------------------

If you are systemically using PartCAD in your organization then it makes sense
to collect your own telemetry data to understand how the tool is being
used in your organization, and to learn how to improve your organization performance.

The only OpenTelemetry backend provider currently supported is `Sentry <https://sentry.io/>`_.
Create an organization account on Sentry and obtain a DSN key.

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    telemetry:
      type: sentry
      sentryDsn: "<your-sentry-dsn>"

Other OpenTelemetry backend providers can be supported on request.

==================
Automation Support
==================

PartCAD allows you to set CLI options and override user configurations specified in
``~/.partcad/config.yaml`` using environment variables. This can be particularly
useful for setting configurations dynamically or in environments where modifying
configuration files is not feasible.

Generally, all of PartCAD's environment variables are prefixed with ``PC``.

For CLI options, the environment variable prefix depends on the command being
used. You can use the `--help` option to determine the corresponding environment
variable for each CLI option.

    Here are some examples:

      .. code-block:: bash

        # Equivalent to: pc add part --desc "testing" scad test.scad
        PC_ADD_PART_DESC="testing" pc add part scad test.scad

Note that, these environment variables will be overridden if the CLI option is specified.

For user configurations, the environment variables are of the format ``PC_`` followed by the
configuration option name in upper snake case (camelCase word boundaries become underscores).
For example, to override the ``pythonSandbox`` configuration, you would set the environment
variable ``PC_PYTHON_SANDBOX``.

Note that environment variable names are case-sensitive. Always use uppercase letters
for the ``PC`` prefix and the rest of the variable name, as shown in the examples above.

In this case, these environment variables will take precedence over the values specified in
``~/.partcad/config.yaml``.

.. _git-configuration:

==========================
Flexible Git Configuration
==========================

PartCAD imports packages from git repositories without the ``git`` command line tool:
it speaks the git protocols itself, through the ``libgit2`` library that ships with its
dependencies. Nothing has to be installed alongside it for imports to work.

By default, PartCAD uses the system's Git configuration when importing packages
using git, which it reads from ``~/.gitconfig`` whether or not git itself is installed.
If you want to override these configurations, you can add your
overrides in ``~/.partcad/config.yaml`` as shown below:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    git:
      config:
        "user.name": "John Doe"
        "user.email": "johndoe@example.com"
        ...

Cloning over SSH is faster and more reliable because it uses an efficient
protocol with lower overhead, supports compression, and maintains stable
connections via key-based authentication. SSH avoids HTTPS rate limits,
handles firewalls better, and eliminates credential prompts, making it
ideal for large repositories or frequent interactions.

Repositories reached over SSH are authenticated with the keys held by the running SSH
agent, and then with the default key files (``~/.ssh/id_ed25519``, ``~/.ssh/id_ecdsa``,
``~/.ssh/id_rsa``). A key protected by a passphrase only works through the agent, since
PartCAD never asks for one: a repository it cannot authenticate to fails with an error
rather than waiting for a prompt that nothing would answer.

If you have SSH keys configured then you can add the following
to the ~/.partcad/config.yaml:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    dependencies:
      overrides:
        url:
          "git@github.com:": "https://github.com/"

===================================
Personally Identifiable Information
===================================

The user section in ``~/.partcad/config.yaml`` defines the default personal
and contact details used throughout the system. These details include
the user's name, email, phone number, company, and address information.

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    user:
        firstName: <...>
        lastName: <...>
        email: <...>
        phone: <...>
        company: <...>
        line1: <...>
        line2: <(optional)>
        countryCode: US
        stateCode: <...>
        zipCode: <...>
        city: <...>

Address Configuration
---------------------

Users can override any details from the user section
by specifying shippingAddress and billingAddress separately.

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    user: # Default user details (includes firstName, lastName, email, phone, company, address, etc.)

    shippingAddress:  # Optional, overrides user details for shipping
        firstName: <(optional)>
        lastName: <(optional)>
        phone: <(optional)>
        company: <(optional)>
        line1: <(optional)>
        line2: <(optional)>
        countryCode: <(optional)>
        stateCode: <(optional)>
        zipCode: <(optional)>
        city: <(optional)>

    billingAddress:  # Optional, overrides user details for billing
        firstName: <(optional)>
        lastName: <(optional)>
        phone: <(optional)>
        company: <(optional)>
        line1: <(optional)>
        line2: <(optional)>
        countryCode: <(optional)>
        stateCode: <(optional)>
        zipCode: <(optional)>
        city: <(optional)>

**Override Behavior**

- If shippingAddress is not specified, the system will use the user details for shipping.
- If billingAddress is not specified, the system will use the user details for billing.
- If shippingAddress or billingAddress is provided, it completely replaces the corresponding fields from user.

This setup allows full customization of shipping and billing details,
supporting scenarios where items need to be sent to different recipients or addresses.


=======================
Parameter Configuration
=======================

The configuration file (``~/.partcad/config.yaml``) allows users to define
reusable parameters, which can be accessed dynamically within the provider configurations.

In ``~/.partcad/config.yaml``, parameters are stored under a parameters section.

Example:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    parameters:
      object_id:
        <parameter name>: <parameter value>


Object IDs are used to reference different
types of objects within a package, such as sketches, parts,
assemblies, scenes, interfaces, and providers.


Accessing Parameters in Providers
---------------------------------

In the providers section, parameters can be referenced dynamically
using a function ``get_from_config()``, ensuring that sensitive
or reusable values (e.g., API keys, URLs) do not need to be
hardcoded multiple times.

Example:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    providers:
      <provider name>:
        type: <store|manufacturer|enrich>
        url: <...>
        parameters:
          url:
            type: string
            default: {{ get_from_config() }}
