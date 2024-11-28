Troubleshooting
###############

============
Command Line
============

The command line interface is
the most basic (though not the most convenient) way to troubleshoot PartCAD
configuration, model declarations and definitions.

The status of PartCAD context can be evaluated using the ``status`` command.

  .. code-block:: shell

    pc status

Pay attention to any exception or error message produced by the
``status`` command.


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

==============
OCP CAD Viewer
==============

If the PartCAD vscode extension does not work for you then it is possible to
troubleshoot PartCAD using the ``OCP CAD Viewer`` vscode extension alone.

Any part or assembly can be displayed in ``OCP CAD Viewer`` by running
``pc inspect <part>`` or ``pc inspect -a <assembly>`` in a terminal.

  .. code-block:: shell

    # Create a temporary folder
    mkdir /tmp/inspect && cd /tmp/inspect

    # Initialize a package with the default dependency on public PartCAD repository
    pc init

    # Display the part in 'OCP CAD Viewer'
    pc inspect /pub/std/metric/cqwarehouse:fastener/hexhead-iso4014
