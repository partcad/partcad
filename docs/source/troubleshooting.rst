Troubleshooting
###############

============
Command Line
============

The command line interface is
the most basic (though not the most convenient) way to troubleshoot PartCAD
configuration, model declarations and definitions.

Status
------

The status of PartCAD context can be evaluated using the ``system status`` command.

  .. code-block:: shell

    pc system status

Pay attention to any exception or error message produced by the
``status`` command.

The same command has two more reports, for the two things that most often turn
out to be the answer -- what the configuration actually resolved to, and what
the environment actually said:

  .. code-block:: shell

    pc system status config
    pc system status env

They are worth reading together. The first says what an option resolved to once
the configuration file, the ``PC_*`` environment and the command line had all
been applied; the second says what the environment asked for. They disagree
whenever a command-line option won, a variable was misspelled, or a value was
rejected -- which covers most of the cases where somebody runs either of them.
Variables whose names say they carry a credential are listed but printed as
``<scrubbed>``, so the output is something you can attach to a bug report.

If the work is being done by a daemon -- which it is for most commands -- ask
the daemon the same two questions:

  .. code-block:: shell

    pc daemon status
    pc daemon status config
    pc daemon status env

A daemon is warm and shared per workspace, so the configuration and environment
it reports are whatever its own environment held when something first started
it, possibly days ago and possibly from a VS Code window. Your command does not
run under them -- every command hands the daemon its own resolved configuration
-- but the daemon's own copy is what it falls back on, and the environment it
inherited is not something this side can reconstruct any other way.

Health Check
------------

The ``healthcheck`` command can also be used to verify if the PartCAD environment
on your workstation is setup correctly.

  .. code-block:: shell

    pc healthcheck

Please, follow the instructions provided by the ``healthcheck`` command to fix
any issues it detects.

Use ``--dry-run`` option to see what healthcheck tests can be executed.

  .. code-block:: shell

    pc healthcheck --dry-run

The ``healthcheck`` command also can take a ``--fix`` option to automatically
fix the issues it detects if possible.

  .. code-block:: shell

    pc healthcheck --fix

In order to selectively execute only a subset of the healthchecks tests, the ``healthcheck`` command can be used with the ``--filters`` option that accepts a comma-separated list of test tags.

  .. code-block:: shell

    pc healthcheck --filters python,windows

Most of what ``healthcheck`` finds is reported as a warning and the command
still succeeds, because most of it is a machine missing something it can do
without. There is one exception, and it is about sandboxes.

Can this machine render anything?
---------------------------------

PartCAD imports no CAD kernel of its own. Every part is produced by a script
run in a sandbox, and there are two mechanisms that can provide one on a
machine that starts with nothing: conda, which installs an interpreter and the
CAD stack beside it, and a container runtime, which carries both already. Three
checks report on this, and they share the ``sandbox`` tag:

  .. code-block:: shell

    pc healthcheck --filters sandbox

* ``CondaAvailable`` -- a warning when conda or mamba cannot be found. PartCAD
  builds a virtual environment instead, which works wherever the host has a
  usable Python.
* ``DockerAvailable`` -- a warning when no container runtime answers. Note that
  a Docker daemon running *Windows* containers counts as none here: every image
  PartCAD uses is a Linux image. Set ``useDocker: false`` (or
  ``PC_USE_DOCKER=false``) on a machine that has a daemon and should not use it,
  and the check stops looking.
* ``SandboxAvailable`` -- an **error**, and the only check that makes
  ``pc healthcheck`` exit non-zero.

A stated ``pythonSandbox`` is obeyed, and that is most of what
``SandboxAvailable`` does. "Is there conda or a container" is the right
question only when nobody has said which sandbox to use, because that is when
PartCAD is the one choosing between them. If you wrote ``pythonSandbox: venv``
-- a CI job that builds a virtual environment from the interpreter it already
has, an air-gapped machine, a container image with no conda in it -- nothing is
misconfigured, and the check passes:

  .. code-block:: shell

    pythonSandbox: venv       # in ~/.partcad/config.yaml
    PC_PYTHON_SANDBOX=venv    # or in the environment

A declared sandbox is then checked against what *it* needs and nothing else:
``conda`` needs a conda, ``docker`` needs a container runtime, and ``venv``,
``pypy`` and ``none`` need only the Python PartCAD is running under.
(``remote`` needs a reachable ``partcad-service-remote-docker``, which is a
network address this check does not ping.) Asking for ``conda`` on a machine
that has none is a failure -- being unable to do what was asked is not a reason
to quietly do something else.

Three things need a container specifically, and say so when they are reached
rather than in advance: an implementation whose package declares ``container:``,
importing a KiCad PCB (``useDockerKicad``), and the ``docker`` Python sandbox
when it was asked for by name. If ``pc render``, ``pc export`` or ``pc inspect``
reports that no container runtime is available, start Docker or take the other
route the message names -- for KiCad that is installing KiCad on this machine
and setting ``useDockerKicad: false``.

Typical problems
----------------

When running `pc ...` commands, getting: "pc is not a recognized command..."

- Make sure that Conda environment is activated in the current terminal, for example by running `conda info`
- With the :ref:`standalone build <standalone-cli>`, there is no environment to activate: the commands are
  linked into ``~/.local/bin``, which has to be on ``PATH``. Run ``~/.local/bin/pc version`` to confirm the
  installation itself is fine, then add the directory to ``PATH``.

Which one is running, the standalone build or a wheel?

- ``command -v pc`` says. A path under ``~/.local/share/partcad`` (or wherever ``--install-dir`` pointed) is
  the standalone build; a path inside a Python environment is the wheel. Having both installed is supported,
  but only the first on ``PATH`` runs.

Imports hang, or time out reaching a repository the browser can open:

- The network is very likely one where a proxy is the only route out. PartCAD reads ``HTTPS_PROXY``,
  ``HTTP_PROXY`` and ``NO_PROXY`` for everything it downloads -- git repositories, tarballs and
  ``fileFrom: url`` files alike -- so exporting them is usually the whole fix. See
  :ref:`proxy-configuration`.
- If a fetch fails to verify a certificate rather than hanging, the proxy is re-terminating TLS and its CA
  is not trusted here. Point ``SSL_CERT_FILE`` and ``REQUESTS_CA_BUNDLE`` at the proxy's CA bundle.

========================
PartCAD VSCode Extension
========================

The recommended way to use PartCAD is by using the Visual Studio Extension
called ``PartCAD``. Follow the extension documentation for instructions on how
to use this extension.

For troubleshooting purposes, the ``PartCAD`` terminal view output may not
suffice due to the ephemeral nature of some output in that view (many output
lines get overwritten). To get the complete and detailed error log, see the
``PartCAD`` output in the ``Output`` view.

Typical problems
----------------

Message in "Explorer" left panel: "PartCAD ... is not found"

 - Press "Install or update PartCAD" in the "Explorer" left panel and the
   extension downloads a standalone PartCAD for you. No Python is needed.
 - Or, if you would rather use your own Python environment, run
   ``pip install partcad`` in it: the extension finds the ``partcad-json-rpc``
   that puts on your ``PATH`` and uses that instead of downloading anything.
 - Reload PartCAD extension (by pressing "Reload" button in "Context" left panel)

"The PartCAD extension is being initialized..." in "Explorer" gets into infinite loop (and nothing happens in the corresponding terminal window)

 - Close and reopen VSCode

Error while loading part or assembly view: "Module ... not found"

 - Make sure that the extension version matches the PartCAD version in ``pc version`` command output

==============
PartCAD Viewer
==============

The ``PartCAD Viewer`` is a tab the extension opens when a part, assembly,
scene, sketch or interface is inspected. PartCAD tessellates the shape in a
sandboxed runtime, and sends the result to the extension as compressed glTF over
a socket on ``127.0.0.1:9137``. The Python side of that connection is the
``partcad_ide_client`` package, which ships inside ``partcad`` itself -- so
``pip install partcad`` is all that is needed, and there is nothing separate to
install.

Beside the 3D view the panel carries tabs for the questions that are about the
object rather than its shape -- **Bill of Materials**, **Instructions** and
**Supply**, each appearing where it applies. Those do not come over the socket
above: they are answered by the PartCAD daemon and fetched the first time the
tab is opened, so a failure in one of them is a daemon problem and says so in
the tab, while the 3D view keeps working.

Anything with a ``partcad`` that can reach that port can display into the same
viewer -- including a ``pc`` run in a plain terminal, as long as a window with
the extension is open. While the extension is active it puts the PartCAD command
line tools on the ``PATH`` of terminals opened in that window, so ``pc`` is there
without any further setup (``partcad.addToolsToTerminalPath`` turns that off):

  .. code-block:: shell

    # Create a temporary folder
    mkdir /tmp/inspect && cd /tmp/inspect

    # Initialize a package with the default dependency on public PartCAD repository
    pc init

    # Display the part in the 'PartCAD Viewer'
    pc inspect //pub/std/metric/cqwarehouse:fastener/hexhead-iso4014

Typical problems
----------------

``Failed to load "partcad_ide_client"`` in the PartCAD terminal view

 - The package ships inside ``partcad``, so this means the installation is
   damaged rather than incomplete. Reinstall with
   ``pip install --force-reinstall partcad``, or press "Update PartCAD" in the
   "Context" left panel.
 - On a PartCAD older than 0.8.0 it was a separate ``partcad-ide-client``
   distribution that was never published; upgrading is the fix.

``No PartCAD IDE with an open PartCAD Viewer detected``

 - Nothing is listening on the viewer port. Open a window with the PartCAD
   extension active; the extension starts listening when it activates.
 - If two windows are open, only one of them may own the port on platforms
   without ``SO_REUSEPORT``. The "PartCAD Viewer port ... is already in use"
   message in the ``PartCAD`` output view says which case this is.
 - Set ``PARTCAD_IDE_PORT`` to move a ``partcad`` process to a different port
   if 9137 is taken by something else on the machine.
