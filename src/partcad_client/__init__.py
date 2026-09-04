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
* :mod:`~partcad_client.lint` -- checking the files this process was handed,
  including content an editor has not saved yet.
* :mod:`~partcad_client.external` -- opening one of those files in a third-party
  CAD application: the one installed here, or a container this machine can run.
* :mod:`~partcad_client.object_types` -- which PartCAD object types are meshes,
  which is what decides whether a file has to be converted before an application
  that reads nothing else can open it.

None of it belongs to a daemon. A daemon can be remote, where "update PartCAD"
would mean updating somebody else's installation and "stop the local daemons"
would mean stopping somebody else's; and a daemon that went looking for its
neighbours would be racing every client on the machine. A client is one process,
acting on the machine it runs on, which is what makes stopping every local daemon
before an update a sane thing to do rather than a distributed algorithm. Checking
a file joins them for the same reason: it is the client's file, sometimes not
even on disk, and it needs nothing a daemon has. So does opening one in FreeCAD:
the window belongs on the screen of whoever ran the command, and a remote daemon
has neither that screen nor that file.

Converting one is the counter-example, and it is why `external` takes a callback
rather than doing it: making a mesh out of a solid so that Blender can open it
drives a CAD wrapper, which is exactly the work a daemon exists for. So the
decision -- is this already a mesh? -- is here, in tables cheap enough for a
process with no CAD kernel in it, and the conversion is `pc open`'s to ask for.

`partcad-utils` holds what both ends share (logging, telemetry, user config, and
the client/daemon rendezvous: framing and workspace addressing). The CLI is the
reference caller; the VS Code extension reaches the same code by running `pc`
rather than by reimplementing it in TypeScript.
"""

__version__ = "0.8.49"
