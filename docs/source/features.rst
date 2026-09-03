Additional Features
###################

============================
Visual Studio Code extension
============================

The PartCAD extension for Visual Studio Code is the primary graphical interface to PartCAD. It adds a PartCAD
workbench with an Explorer view for browsing packages and an Inspector view for viewing objects and editing
their parameters. Install it from the
`VS Code marketplace <https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad>`_. See
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
- **Supply** — what the objects in view can be bought from, and a quote per supplier.

The 3D view arrives over the viewer protocol from whichever ``partcad`` asked for the shape to be shown; the
other tabs are questions put to the PartCAD daemon, fetched the first time the tab is looked at and cached
until the next object is shown. An object that belongs to no package gets the 3D view alone.

Export
------

Objects can be exported directly from the extension to any of the following formats: **SVG**, **PNG**,
**JPEG**, **STEP**, **STL**, **3MF**, **ThreeJS**, **OBJ**, **IGES**, and **glTF**. A scene can also be
exported as a **Gazebo world** (SDFormat).

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
``conda``            An environment conda provisions, **interpreter included**. The only one
                     that can give a package the Python version it asks for, so it is the
                     default wherever conda or mamba is installed -- and in the
                     :ref:`standalone tools <standalone-cli>`, the :ref:`snap <snap-package>`
                     and the :ref:`PartCAD IDE <partcad-ide>`, which carry a conda of their
                     own and use yours in preference to it when you have one.
``venv``             A plain virtual environment of PartCAD's own, one per interpreter
                     version, under the internal state directory. The default when conda is
                     not installed. Built from whichever Python the host has, so a package
                     asking for a version the host does not have is rendered on the host's
                     and told so -- and so not something the standalone tools can fall back
                     to, since the machine they exist for is the one with no Python.
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
