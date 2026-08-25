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
sketch or interface is inspected. PartCAD tessellates the shape in a sandboxed
runtime, and sends the result to the extension as compressed glTF over a socket
on ``127.0.0.1:9137``. The Python side of that connection is the
``partcad_ide_client`` package, which ships inside ``partcad`` itself -- so
``pip install partcad`` is all that is needed, and there is nothing separate to
install.

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
