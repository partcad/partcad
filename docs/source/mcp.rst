##########
MCP server
##########

``pc mcp`` serves the `Model Context Protocol <https://modelcontextprotocol.io>`_ (MCP) on stdio. It is how an
AI agent drives PartCAD without a shell: any MCP client -- Claude Code, Claude Desktop, Cursor, Visual Studio
Code and the rest -- starts it as a subprocess and calls its tools to see what a package holds, read an
object's declaration, look at it, test it and write it out, and to reach everything else PartCAD's daemon can
do.

The server is a client of the workspace's daemon, exactly like the other ``pc`` commands: it starts the daemon
if none is running, and the daemon loads the packages, runs the CAD scripts in their sandboxes and renders. So
an agent needs nothing installed but PartCAD, and the agent's renders, tests and exports come from the same
warm context as the ones you run in a terminal.

The agent still writes and edits ``partcad.yaml`` and the CAD scripts with its own file tools; the daemon
reloads what changed. The MCP server is for everything after that -- looking at the result and checking it.

********
Starting
********

.. code-block:: shell

  pc mcp                                   # serves the package in the current directory
  pc -p packages/robot mcp                 # or the one -p names
  PC_PATH=packages/robot pc mcp            # the same, from the environment
  uvx partcad mcp                          # without installing PartCAD first

Nothing is started until the first tool call that needs the daemon, so a server started in a directory that
is not a package yet still starts, and says so when it is asked to do something. Its log goes to stderr, which
MCP clients show in their server logs; stdout is the protocol.

*******************
Setting up a client
*******************

Claude Code
===========

The ``pc`` plugin (see the README's *Plugin for Claude Code*) brings the server along with the skills, and
``pc init`` adds it to the ``.mcp.json`` of the repository it sets up. Anywhere else:

.. code-block:: shell

  claude mcp add partcad -- pc mcp
  claude mcp add --scope project partcad -- pc -p packages/robot mcp

Cursor
======

``pc init`` adds it to ``.cursor/mcp.json``. By hand:

.. code-block:: json

  {
    "mcpServers": {
      "partcad": { "command": "pc", "args": ["-p", "${workspaceFolder}", "mcp"] }
    }
  }

Visual Studio Code
==================

The PartCAD extension registers one server for every workspace folder that holds a ``partcad.yaml``, using the
``pc`` it found or downloaded -- there is nothing to configure. Without the extension, in ``.vscode/mcp.json``:

.. code-block:: json

  {
    "servers": {
      "partcad": { "type": "stdio", "command": "pc", "args": ["-p", "${workspaceFolder}", "mcp"] }
    }
  }

Claude Desktop
==============

Claude Desktop starts servers from no particular directory, so name the package with an absolute path, in
``claude_desktop_config.json``:

.. code-block:: json

  {
    "mcpServers": {
      "partcad": { "command": "pc", "args": ["-p", "/home/me/robot", "mcp"] }
    }
  }

The MCP Registry
================

The server is listed in the `MCP Registry <https://registry.modelcontextprotocol.io>`_ as
``io.github.partcad/partcad``, which is what clients that install servers from the registry find. Such a client
runs it as ``uvx partcad mcp``, and offers ``PC_PATH`` for the package to serve.

*****
Tools
*****

Each tool is one daemon method, with the parameters the ``pc`` command it mirrors sends. The ones that name an
object -- ``info``, ``render``, ``export``, ``test``, ``bom`` and ``instructions`` -- take ``params``, the values of
the object's own parameters by name, which is ``-p <name>=<value>`` on the command line (see
:ref:`parameter-values`).

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Tool
     - Mirrors
     - What it does
   * - ``list_objects``
     - ``pc list``
     - The packages, parts, sketches, assemblies, scenes, interfaces, materials or software of a package.
   * - ``info``
     - ``pc info``
     - An object's configuration, parameters and properties, or the package's.
   * - ``render``
     - ``pc render``
     - Renders one object and returns the picture: PNG (the default) or JPEG as an image, SVG as text.
   * - ``export``
     - ``pc export``
     - Writes one object to a file in the workspace: STEP, STL, 3MF, OBJ, glTF, BREP, PNG, SVG, ...
   * - ``test``
     - ``pc test``
     - Checks objects against the requirements and tests they declare.
   * - ``lint``
     - ``pc lint``
     - Checks a package's ``partcad.yaml``, ASSY files and scripts.
   * - ``bom``
     - ``pc bom``
     - What has to be bought or made to build an object.
   * - ``search``
     - ``pc search``
     - Finds objects or packages by keyword or by the interface they implement.
   * - ``instructions``
     - ``pc instructions``
     - The step-by-step build of an assembly, with this machine's Build vs Buy choices applied.
   * - ``version``
     - ``pc version``
     - The version of the server and of the daemon serving the workspace.
   * - ``list_methods``
     -
     - Every daemon method, with a one-line summary.
   * - ``execute``
     -
     - Runs any daemon method: CAE, CAM, simulations, ``add``, ``import``, ``convert``, ``install`` and the rest.

``execute`` takes a method name and its parameters as ``pc`` sends them; the workspace's context is added for
it. It refuses the few methods that act on something that is not the agent's: resetting, stopping or
reconfiguring the daemon every client of the workspace shares, and changing the user's own settings
(``list_methods`` marks them). A healthcheck that fixes the host is refused too.

Two resources are served as well: ``partcad://workspace`` (where the workspace is, which files the agent may
use, and its package tree) and ``partcad://methods`` (what ``list_methods`` returns).

*******************
Results and errors
*******************

Every tool returns one JSON text block: ``ok``; the daemon's ``result`` when there is one; ``errors``, the
error lines the daemon logged; and ``log``, everything else it logged while it worked. Most of PartCAD answers
by logging -- ``pc list`` prints a table -- so for ``list_objects``, ``info``, ``test`` and ``search`` the log
*is* the answer. A render's picture follows the text block as an image.

A failure is a result with ``ok`` false and the error in it, never a protocol error: an object that does not
build, a test that fails, a daemon that cannot be reached, a path outside the workspace. Only a malformed tool
call is refused by the protocol. When the connection to the daemon is lost in the middle of a call, the result
says the call may or may not have finished -- the server never sends it again on its own -- and the next call
reconnects.

The first render or test of an object builds it in its sandbox, which can take minutes; clients that ask for
progress are told what the daemon is working on.

*************************
Which files it may touch
*************************

A path an agent names -- where ``export`` writes, and every path parameter ``execute`` passes on -- has to be
inside the workspace, and not inside a hidden directory there (``.git``, ``.env``, an editor's settings). A
relative path is relative to the workspace, never to wherever the client started the server. Symbolic links
are followed before the check, so a link out of the workspace is outside it.

.. code-block:: shell

  pc mcp --allow-path ../shared-parts      # one more directory the agent may use (repeatable)
  pc mcp --allow-any-path                  # no limit

This is a limit on what the agent names, not a jail for PartCAD: the daemon still reads whatever a package's
own configuration points at.
