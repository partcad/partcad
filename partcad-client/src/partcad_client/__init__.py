#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a PartCAD *client* needs, and a PartCAD daemon must not have.

Three things live here, and they are one idea: the operations that act on **this
machine and its own installation**, from the process running out of it.

* :mod:`~partcad_client.daemon` -- discovering the daemon serving a
  workspace, checking it is alive, stopping it and waiting for it to be gone,
  and enumerating the daemons running locally.
* :mod:`~partcad_client.client` -- starting a daemon if none is running and
  speaking framed JSON-RPC to it.
* :mod:`~partcad_client.selfupdate` -- replacing this installation of
  PartCAD, whether it is the Python wheels or the standalone bundle.

None of it belongs to a daemon. A daemon can be remote, where "update PartCAD"
would mean updating somebody else's installation and "stop the local daemons"
would mean stopping somebody else's; and a daemon that went looking for its
neighbours would be racing every client on the machine. A client is one process,
acting on the machine it runs on, which is what makes stopping every local daemon
before an update a sane thing to do rather than a distributed algorithm.

`partcad-utils` holds what both ends share (logging, telemetry, user config, and
the client/daemon rendezvous: framing and workspace addressing). The CLI is the
reference caller; the VS Code extension reaches the same code by running `pc`
rather than by reimplementing it in TypeScript.
"""

__version__ = "0.7.163"
