Installation
############


==================
Command line tools
==================

PartCAD command line tools are implemented in Python and, in theory,
available on all platforms where Python is available. However, it is only
getting tested on Linux, macOS and Windows.

.. code-block:: shell

  $ python -m pip install -U partcad

.. note::

  One package is everything: the ``pc`` command line tool, the Python module, and
  the ``partcad-json-rpc`` service the editor extensions talk to. ``partcad-cli``
  used to be a separate package and is now a thin one that just pulls ``partcad``
  in, so ``pip install partcad-cli`` still works if you have it written down
  somewhere.

.. note::

  No Python on the machine, or no interest in maintaining a Python environment?
  Install the :ref:`standalone command line tools <standalone-cli>` instead. They are
  the same tools, shipped with their own interpreter. There is also a
  :ref:`snap package <snap-package>` for Linux, not published yet.

.. note::

  PartCAD works best when `conda <https://docs.conda.io/>`_ is installed.
  If that doesn't help (e.g. macOS+arm64) then try ``mamba``.
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
    upgrade      Upgrade PartCAD itself to the latest version
    config       Show the current user configuration
    system       PartCAD system commands (reset, set, status, telemetry)
    daemon       Manage the PartCAD background daemon (start, stop, status, reset, set)
    open         Open a file in a third-party application, on this machine

  Package commands:
    init         Create a new PartCAD package in the current directory
    install      Download everything the package needs to be built
    update       Force update all imported packages to their latest versions
    lint         Run linting checks on files within packages

  Object commands:
    list         List components (parts, sketches, assemblies, scenes, interfaces, mates,
                 providers, software, packages)
    search       Search for parts, sketches, assemblies, or scenes
    add          Add a dependency, sketch, part, assembly, scene, or software
    import       Import a dependency, sketch, part, or assembly
    test         Run tests on a part, assembly, or scene
    inspect      View a part, assembly, or scene visually
    info         Show detailed information about a part, assembly, or scene
    bom          Print the bill of materials of an assembly or a scene
    convert      Convert parts, sketches or assemblies to another format and update their type
    export       Export a 3D view of parts, assemblies, or scenes
    render       Render a 2D projection of parts, assemblies, or scenes onto a plane

  Workflow commands:
    supply       Manage the supply chain of the current project

  Other commands:
    adhoc        Ad-hoc operations that do not require a package
    healthcheck  Check the host system for known issues

Common options apply to every command, including ``-v``/``-q`` to raise or lower verbosity, ``--no-ansi`` for
plain-text logs, and ``-p PATH`` to select the package (a ``partcad.yaml`` file or a directory that contains
one). Run ``pc <command> --help`` to see the options for any command.

For a full command reference, see :doc:`cli`.


.. _standalone-cli:

=========================================
Standalone command line tools (no Python)
=========================================

The standalone build is the same ``pc`` and ``partcad`` commands, packaged with their own Python
interpreter and every dependency they need. Nothing is installed into a Python environment, because
no Python environment is involved: there is nothing to activate, nothing to keep on the right version,
and nothing to break the next time some other tool upgrades Python.

Use it if Python is not installed, if the Python that is installed belongs to the operating system and
should be left alone, or if PartCAD is simply a tool to run rather than a library to program against.
Use the wheels instead if you want to ``import partcad`` from your own scripts.

Install
=======

On Linux and macOS:

.. code-block:: shell

  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh

That downloads the bundle for the current operating system and architecture from the latest
`GitHub release <https://github.com/partcad/partcad/releases>`_, verifies its checksum, unpacks it into
``~/.local/share/partcad/<version>``, and links ``pc`` and ``partcad`` into ``~/.local/bin``.
Nothing else on the system is touched, and no ``sudo`` is asked for. If ``~/.local/bin`` is not on your
``PATH``, the installer says so and prints the line to add.

The bundle is around 180MB unpacked and 57MB to download on Linux x86_64, and about half that on macOS and
on Linux arm64, which carry no bundled OpenSCAD. It carries no CAD kernel: PartCAD builds every shape in a
conda sandbox it provisions itself, so ``conda`` (or ``mamba``) is a prerequisite here exactly as it is for
the wheels. ``pc healthcheck`` reports what this machine is missing.

Supported platforms are Linux on x86_64 and arm64, and macOS on Apple silicon. Windows is covered by the
``.zip`` archives under :ref:`manual installation <standalone-manual>`.

.. _standalone-os-versions:

There is one build per supported *operating system version*, not one per operating system. A frozen bundle
links against the C library and the system frameworks of the machine that built it, so it runs there and on
anything newer, and on nothing older -- a single "Linux" build would quietly mean "whichever Linux the
builder happened to be". Every release publishes a manifest, ``platforms.json``, saying which builds it
carries; the installer reads it, works out which of them this machine can run, and downloads that:

.. code-block:: text

  Linux, x86_64 and arm64     built on Ubuntu 22.04 and on Ubuntu 24.04
  macOS, Apple silicon        built on macOS 15 and on macOS 26
  Windows, x86_64             built on Windows Server 2022

The Ubuntu names are not a requirement to run Ubuntu. Any Linux distribution can run these bundles; what
differs between the two is the minimum glibc, and a machine the installer cannot identify as Ubuntu is
offered the 22.04 build, which has the lower floor. Pass ``--platform`` to install a specific one.

Windows is one build rather than one per Windows version, because there is nothing to choose between: the
split exists so that a machine can be compared against it, and Windows offers no such comparison -- nor the
glibc-style floor that would make one matter. It runs on Windows 10 and later.

Releases made before ``platforms.json`` existed cannot be resolved this way: there is no way to know from
this machine which builds such a release carries. Install the latest release, or name the build with
``--platform``.

Options
=======

Options go after ``sh -s --``:

.. code-block:: shell

  # A specific version rather than the latest release
  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh -s -- --version 0.7.146

  # Somewhere else entirely
  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | \
      sh -s -- --install-dir /opt/partcad --bin-dir /usr/local/bin

  # What else is there
  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh -s -- --help

============================== ================================ ==========================================
Option                         Environment variable             Default
============================== ================================ ==========================================
``--version <version>``        ``PARTCAD_VERSION``              the latest release
``--install-dir <dir>``        ``PARTCAD_INSTALL_DIR``          ``${XDG_DATA_HOME:-~/.local/share}/partcad``
``--bin-dir <dir>``            ``PARTCAD_BIN_DIR``              ``~/.local/bin``
``--base-url <url>``           ``PARTCAD_BASE_URL``             the GitHub release for the version
``--repository <owner/name>``  ``PARTCAD_REPOSITORY``           ``partcad/partcad``
``--platform <id>``            ``PARTCAD_PLATFORM``             detected from this machine
``--ide``                      ``PARTCAD_IDE``                  off, the command line tools alone
``--app-dir <dir>``            ``PARTCAD_APP_DIR``              macOS, with ``--ide``: ``/Applications``
                                                                when it is writable, ``~/Applications``
                                                                otherwise
============================== ================================ ==========================================

Installing several versions side by side is fine: each one unpacks into its own directory, and the
last install wins the ``pc`` and ``partcad`` links. Installing an already installed version replaces it.

Upgrade and uninstall
=====================

Upgrading is installing again: re-run the same command.

.. code-block:: shell

  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh -s -- --uninstall

Uninstalling removes the bundle and the two links, and only the links that point at the bundle, so a
``pc`` installed from a wheel is left alone. The PartCAD cache and configuration in ``~/.partcad`` are kept;
delete that directory as well to leave nothing behind.

Installing a development build
==============================

The installer is a file in the repository, so any branch, tag, or pull request has its own copy of it, and
the URL selects which one runs. To install using the script as it exists on the ``devel`` branch:

.. code-block:: shell

  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/devel/install.sh | sh

For a pull request, use the branch it comes from, or its head commit:

.. code-block:: shell

  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/<branch-or-commit>/install.sh | sh

.. note::

  The URL only decides which *installer* runs. By default that installer still downloads the bundle of the
  latest release, because bundles are published per release, not per commit. To install the bundle a branch
  or pull request actually built, take it from the ``Standalone`` workflow run of that branch or pull
  request: open the run on GitHub, download the ``partcad-standalone-<platform>`` artifact, unzip it, and
  point the installer at the directory holding the archive. Name that build with ``--platform``: an
  artifact holds the one build it is named after and no ``platforms.json``, so there is no manifest there
  for the installer to resolve this machine against.

  .. code-block:: shell

    $ unzip partcad-standalone-ubuntu-24.04-x86_64.zip -d /tmp/partcad-build
    $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/devel/install.sh | \
        sh -s -- --version <version> --platform ubuntu-24.04-x86_64 \
                 --base-url "file:///tmp/partcad-build"

  ``--base-url`` accepts any URL, so a bundle published anywhere else (an internal mirror, a file server)
  installs the same way.

.. _standalone-manual:

Manual installation
===================

The archives are attached to every `GitHub release <https://github.com/partcad/partcad/releases>`_ next to
the wheels, together with a ``.sha256`` file each:

* ``partcad-<version>-ubuntu-22.04-x86_64.tar.xz``, ``partcad-<version>-ubuntu-22.04-arm64.tar.xz``
* ``partcad-<version>-ubuntu-24.04-x86_64.tar.xz``, ``partcad-<version>-ubuntu-24.04-arm64.tar.xz``
* ``partcad-<version>-macos-15-arm64.tar.xz``, ``partcad-<version>-macos-26-arm64.tar.xz``
* ``partcad-<version>-windows-2022-x86_64.zip``

Pick the newest one your machine is not older than -- see :ref:`the note above <standalone-os-versions>` on
why there is more than one. When in doubt, the oldest build of your operating system runs everywhere the
newer one does.

Each one unpacks into a single ``partcad/`` directory holding ``pc``, ``partcad``, and everything they
need. Put that directory anywhere and run the commands from it, or add it to ``PATH``. On Windows, unpack
the ``.zip`` and add the resulting directory to ``PATH`` -- there is no shell script installer for Windows.

The ``tar`` on macOS and on every Linux distribution reads xz without being told to, which is why the command
below passes no compression flag. A very small Linux system may need the ``xz`` utility installed for it
(``xz-utils`` on Debian and Ubuntu, ``xz`` on Fedora and Alpine); ``install.sh`` says so by name if it is
missing.

.. code-block:: shell

  $ tar -xf partcad-<version>-ubuntu-22.04-x86_64.tar.xz -C ~/.local/share
  $ ~/.local/share/partcad/pc version

.. note::

  On macOS, downloading the archive with a browser marks it as quarantined, and Gatekeeper then refuses to
  run the unpacked commands. Installing with ``install.sh``, or downloading with ``curl``, avoids that.
  To clear it after the fact: ``xattr -dr com.apple.quarantine <directory>``.

What is included, and what is not
=================================

The bundle carries the optional extras that the wheels leave to the user, because a frozen bundle cannot be
extended afterwards: the Python linter (``lint``) is in it, ready to run.

What it does **not** carry is a CAD kernel. The bundle is three console programs, not a library to import, and
every shape those programs build, render, export or tessellate is produced in the conda sandbox PartCAD
provisions and comes back as geometry the commands never open themselves. So ``conda`` (or ``mamba``) is as
much a prerequisite here as it is for the wheels, and leaving OpenCASCADE out is most of why the bundle is
around 180MB rather than around 1GB.

On Linux x86_64 and on Windows it also carries **OpenSCAD**, which PartCAD runs as an external program to
build ``.scad`` parts. The bundled copy is used in preference to any OpenSCAD installed on the machine, so that the
bundle behaves the same everywhere rather than depending on which version a given host happens to have. Two
consequences worth knowing:

* A newer OpenSCAD installed on the machine is *not* used by default. To use the host's OpenSCAD instead of
  the bundled one, pass ``--ignore-bundled-openscad`` or set ``IGNORE_BUNDLED_OPENSCAD=1`` in the
  environment. (Outside the standalone build there is no bundled OpenSCAD, so the option does nothing.)
* On Linux the bundled OpenSCAD is the upstream AppImage, which resolves a few libraries from the host
  (``libGL``, ``libX11``, ``libxcb``, ``fontconfig``, ``freetype``, ``glib``, ``harfbuzz``). Desktop
  installations have these; a stripped-down container or a minimal server may not, and there the bundled
  OpenSCAD will not start -- pass ``--ignore-bundled-openscad`` to fall back to a host OpenSCAD if you have
  one.

The macOS bundles carry no OpenSCAD: the last OpenSCAD release predates Apple silicon and ships an
Intel-only build, which would quietly require Rosetta 2. The Linux arm64 bundles carry none for the same
reason -- upstream publishes that release for x86_64 only. On both, install OpenSCAD yourself and PartCAD
will use it.

Two other things are deliberately not in the bundle, because PartCAD runs them as external programs rather
than importing them, exactly as the wheels do:

* **git**, used to fetch package repositories.
* **conda** (or **mamba**), used to build the sandbox in which PartCAD runs CAD scripts.

Run ``pc healthcheck`` to see what is missing on the current machine.

The bundle provides the command line tools only. The ``partcad`` Python module for CAD-as-code scripts is
a wheel: ``python -m pip install -U partcad``.


.. _snap-package:

============
Snap (Linux)
============

On Linux, the standalone tools are also packaged as a `snap <https://snapcraft.io/docs>`_, for x86_64 and
arm64. It is the same bundle as the ``ubuntu-24.04`` archives above, so everything said about those applies
here too -- what it carries, what it still expects from the machine, the bundled OpenSCAD. What the snap adds
is the packaging: snapd installs it, keeps it up to date, and removes it cleanly.

.. note::

  **The snap is not published yet.** It is built by CI, but it is not on the Snap Store and it is not attached
  to GitHub releases, so ``snap install partcad`` does not work today. Publishing needs Snap Store credentials
  and, because the snap is classic, a manual store review; both are still to come.

  To try it now, download the ``partcad-snap-amd64`` (or ``partcad-snap-arm64``) artifact from a run of the
  ``Standalone`` workflow on GitHub, unzip it, and install the ``.snap`` inside as below.

.. code-block:: shell

  $ sudo snap install --dangerous --classic partcad_<version>_amd64.snap
  $ sudo snap alias partcad.pc pc
  $ pc version

Two flags need explaining:

* ``--classic`` is the confinement. PartCAD works on your own files -- it reads and writes CAD projects
  anywhere on disk, clones git repositories, builds conda sandboxes and runs CAD scripts in them, and serves
  a daemon over a socket that the Visual Studio Code extension connects to. A strictly confined snap could do
  none of that.
* ``--dangerous`` says the package is not signed by the Snap Store, which a downloaded file is not. It stops
  being necessary once the snap is published.

``snap alias`` is there because a snap only gives the bare command name to the app named after the snap
itself. Without it, the commands are ``partcad``, ``partcad.pc`` and ``partcad.json-rpc``.

Where it keeps its state
========================

Everywhere else, PartCAD keeps its cache, its conda sandboxes and its git clones in ``~/.partcad``. The snap
does not write them there. It sets ``PC_INTERNAL_STATE_DIR`` to the per-user directory snapd gives it, so all
of that lives in ``~/snap/partcad/common`` instead, and ``sudo snap remove --purge partcad`` takes it away
with the snap.

Your configuration file is the exception, on purpose: ``~/.partcad/config.yaml`` is read from the home
directory as usual, so one configuration keeps applying whether you installed PartCAD from the snap, the
standalone bundle, or a wheel.

The telemetry id is kept next to it, for the same reason in reverse: it identifies you, and an id that moved
with the state directory would count one machine as several.

conda and git
=============

A snap does not carry your shell environment, so a conda installed under your home directory -- the usual
place -- is not visible to it, and neither is a git outside the standard system prefixes. This is expected
and accepted rather than worked around: PartCAD notices, falls back to running Python scripts without a
sandbox (``pythonSandbox: none``), and reports both as missing. Packages imported from git repositories are
still cloned, through ``libgit2`` as everywhere else; what the snap cannot see is your git *configuration*
(see :ref:`git-configuration`).

.. code-block:: shell

  $ pc healthcheck

If you need the conda sandbox, or your own git configuration, use the :ref:`standalone bundle
<standalone-cli>` or the wheels, which run with your own environment.

To remove the snap, including its data:

.. code-block:: shell

  $ sudo snap remove --purge partcad


.. _partcad-ide:

==================================
PartCAD IDE (no Python, no editor)
==================================

The PartCAD IDE is one application that holds all of it: the editor, the PartCAD extension, the
extensions that go with it, and the same command line tools as the standalone build above. Nothing to
configure, no Python to install, no list of extensions to work through. It opens in the PartCAD
workbench.

Use it if PartCAD is what you want to do rather than something you want to add to an editor you already
have. If you already work in Visual Studio Code, install
:ref:`the extension <vscode-extension>` there instead.

Install
=======

On Linux and macOS:

.. code-block:: shell

  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh -s -- --ide

The same installer as the command line tools, with the same options: everything described for the
:ref:`standalone command line tools <standalone-cli>` applies here too. On Linux it unpacks into
``~/.local/share/partcad/<version>-ide`` and adds an entry to the applications menu. On macOS it puts
``PartCAD IDE.app`` into ``/Applications``, or into ``~/Applications`` when the first is not writable;
``--app-dir`` chooses. Either way ``partcad-ide`` is linked into ``~/.local/bin``, along with ``pc`` and
``partcad`` from the copy inside the IDE -- so the command line tools are installed too, without a second
download.

On Windows, download ``partcad-ide-<version>-windows-x86_64-setup.exe`` from the
`GitHub release <https://github.com/partcad/partcad/releases>`_ and run it. It installs for the current
user without asking for administrator rights, into ``%LOCALAPPDATA%\Programs\PartCAD IDE``, and offers
"for all users" as a choice. It adds a Start menu entry, and -- unless you turn the option off -- puts
``partcad-ide`` and ``pc`` on your ``PATH``. Uninstall it from "Apps & features" like any other
application.

The installer is not signed, so SmartScreen shows a warning: choose "More info", then "Run anyway".

``partcad-ide-<version>-windows-x86_64.zip`` is published next to it, for unpacking somewhere and running
``partcad-ide.exe`` without installing anything.

It unpacks to around 500MB: an editor, a Python interpreter, the command line tools and the extensions, all
in one archive. Like the standalone bundle inside it, it carries no CAD kernel -- shapes are built in a conda
sandbox, so ``conda`` (or ``mamba``) is still expected on the machine.

The first start
===============

There is nothing to set up after installing. The first time the IDE starts, it runs ``pc init`` in
``~/.partcad/projects/start`` -- ``%USERPROFILE%\.partcad\projects\start`` on Windows -- and opens that
folder as the workspace, so the window you get has a package in it rather than an empty editor. A welcome
window opens beside it with the six things worth doing first: add a part, look at it in 3D, render the
package, use ``pc`` in the terminal.

The package is an ordinary one in an ordinary folder. It is under ``~/.partcad`` rather than inside the
application, so ``pc`` in any terminal works with the same package, and uninstalling the IDE does not take
it with it. Move it, put it in git, or leave it and make your own with ``pc init`` somewhere else.

The editor asks whether you trust the authors of a folder before it runs anything from it, and this folder
is no exception -- the answer for the one it just made for you is yes.

This happens once. Afterwards the IDE opens where you left it, like any editor:

* ``PartCAD IDE: Open the starter package`` in the Command Palette opens the package again, and creates it
  if it is not there.
* ``PartCAD IDE: Welcome`` opens the welcome window again.
* ``partcadIde.createStarterPackage``, in the settings, turns the whole thing off for a fresh installation:
  the IDE then starts in an empty window.

Opening the IDE on a folder of your own -- from "Open with PartCAD IDE", or by starting it with a path --
skips it too. It never takes over a window that already has something in it.

What is inside
==============

* The editor: `VSCodium <https://vscodium.com/>`_, the freely licensed build of the same source Visual
  Studio Code is built from, with its extensions coming from `Open VSX <https://open-vsx.org/>`_.
* The PartCAD extension -- which carries the PartCAD Viewer itself -- and the extensions PartCAD works
  with: Python, YAML and the rest of the list in ``.vscode/extensions.json``.
* The PartCAD command line tools, the same ones the standalone bundle installs, including OpenSCAD on
  Linux and Windows.

Pylance is not among them: it is proprietary and licensed for use only with Microsoft's products.
Open-source type checking for Python is included in its place.

The IDE keeps its settings, its state and any extension you install in ``~/.partcad-ide``, so it shares
nothing with a Visual Studio Code or VSCodium on the same machine. PartCAD's own cache and configuration
stay in ``~/.partcad``, shared with the command line tools, so a package installed in a terminal is
there in the IDE.

On macOS, ``partcad-ide-<version>-macos-arm64.dmg`` is published as well: open it and drag the
application to Applications, the usual way.

.. note::

  The macOS application is signed ad-hoc rather than notarized. ``install.sh`` clears the quarantine
  flag on the copy it installs; if you unpack the archive by hand instead, macOS refuses to open it
  until you do the same:
  ``xattr -dr com.apple.quarantine "/Applications/PartCAD IDE.app"``.

Upgrade and uninstall
=====================

Upgrading is installing again. Uninstalling is the same command as for the command line tools, and
removes the application, the links and the menu entry:

.. code-block:: shell

  $ curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh -s -- --uninstall

The IDE does not update itself. It is built from a VSCodium release rather than being one, and its
update server is deliberately absent -- a self-update would replace the PartCAD extension and tools
inside it with a plain editor.


=====================================
Latest Development Version of PartCAD
=====================================

You can install the latest development version of PartCAD from the ``devel`` branch on
`PartCAD <https://github.com/partcad/partcad>`_. First, create an isolated Python environment
and ensure ``pip``, ``setuptools``, and ``wheel`` are upgraded, then:

.. code-block:: shell

   $ python -m pip install --upgrade git+https://github.com/partcad/partcad.git@devel

That is the whole thing. It used to be two commands naming two subdirectories, in
the right order, because the repository shipped several packages that pinned each
other; it ships one now.

=============
Python module
=============

PartCAD provides Python modules that can be used in CAD as code scripts
(such as ``CadQuery``, ``build123d`` and ``sdf``). They come with the same package
as the command line tools, so there is nothing extra to install.

.. code-block:: shell

    $ python -m pip install -U partcad
    $ python
    ...
    >>> import partcad as pc
    >>> ctx = pc.init()

=======
Linting
=======

The linter used by ``pc lint`` to check Python files is optional. Install the
``lint`` extra to enable it:

.. code-block:: shell

    $ python -m pip install -U 'partcad[lint]'

Without the extra, linting Python files reports an error naming the package to
install. Everything else in PartCAD, including linting of YAML files, works
without it.

=====================
Shared caching tiers
=====================

Beyond memory and the local filesystem, PartCAD can keep its cache of built
geometry on a memcached server shared by a team or a CI fleet
(``cacheRemote``), and in an S3 bucket that outlives both (``cacheS3``). Both
clients are imported only when their tier is switched on.

``cacheRemote`` needs nothing installed: its client (``aiomcache``) is an
ordinary dependency, so switching the tier on is all there is to it.

``cacheS3`` is an extra, because its client pulls in ``botocore``, which is
larger than the rest of PartCAD put together:

.. code-block:: shell

    $ python -m pip install -U 'partcad[aws]'        # cacheS3

Enabling ``cacheS3`` without it reports an error naming the package to install
and leaves the remaining tiers working.

.. _vscode-extension:

============================
Visual Studio Code extension
============================

For an editor you already have. To get the extension, the tools and an editor in one download instead,
see :ref:`the PartCAD IDE <partcad-ide>`.

This extension is available through the VS Code marketplace.
The corresponding marketplace page is `here <https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad>`_.

Every `GitHub release <https://github.com/partcad/partcad/releases>`_ also carries the packaged extension as
``partcad-<version>.vsix``, next to the wheels and the bundles. Install it from the command line, or with
"Install from VSIX..." in the Extensions view:

.. code-block:: shell

  $ code --install-extension partcad-<version>.vsix

Use it to pin a particular version, to install where the marketplace is not reachable, or to try a release
before the marketplace has it. One package serves every platform: the extension is a JSON-RPC client with no
Python and nothing compiled in it.

If you installed the extension before it moved
==============================================

The extension used to be published as ``OpenVMP.partcad``. It is ``PartCAD.partcad`` now, which the marketplace
treats as a separate extension rather than as a rename.

There is nothing to do. The old entry still exists and now depends on the new one, so it updates like any other
extension and brings the extension in its new home with it. Your settings, which live in your ``settings.json``
under the same ``partcad.*`` names, are untouched. You can remove ``PartCAD (moved)`` from the Extensions view
once it has done its job.

.. _freecad-addon:

==============
FreeCAD add-on
==============

The ``PartCAD`` workbench browses packages, parts and assemblies inside FreeCAD and imports them into the
open document. It lives in the ``cad/freecad`` directory of the repository; copy or link that
directory into FreeCAD's ``Mod`` folder as ``PartCAD`` and restart FreeCAD:

.. code-block:: shell

  $ git clone https://github.com/partcad/partcad.git
  $ ln -s "$PWD/partcad/cad/freecad" ~/.local/share/FreeCAD/Mod/PartCAD

The ``Mod`` folder is ``~/Library/Preferences/FreeCAD/Mod/`` on macOS and ``%APPDATA%\FreeCAD\Mod\`` on
Windows. No Python setup is needed: the add-on drives the standalone ``partcad-json-rpc`` service, using an
existing standalone installation if there is one and offering to download a bundle if there is not. See
``cad/freecad/README.md`` for what it does and which environment variables it reads.

=========================
Public PartCAD repository
=========================

The public PartCAD repository is hosted at `GitHub <https://github.com/partcad/partcad-index>`_.
If necessary, PartCAD tools are automatically retrieving the contents of this
repository and all other required repositories and packages. No manual action is needed to `install` it.

However, if you suspect that something is wrong with locally cached files,
use ``pc system status`` to investigate and to determine the location of the cached files.
