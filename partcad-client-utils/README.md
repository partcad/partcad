# partcad-client-utils

Client-side utilities for the [PartCAD](https://github.com/partcad/partcad)
ecosystem: finding and talking to the daemon that serves a workspace, and
updating this installation of PartCAD.

Everything here acts on **this machine**, from the process running out of it.
That is what makes it a client package and not a shared one, and why none of it
belongs in the daemon:

- A daemon can be remote. "Update PartCAD" would then mean updating somebody
  else's installation, and "stop the local daemons" somebody else's daemons.
- A daemon that went looking for its neighbours would be racing every client on
  the machine. A client is a single process acting on its own machine, which is
  what makes stopping every local daemon before an update a sane thing to do
  rather than a distributed algorithm.

The CLI (`partcad-cli`) is the reference caller. The VS Code extension reaches
the same code by running `pc` — `pc daemon start` to find the daemon,
`pc daemon stop` to stop it, `pc upgrade` to upgrade the installation — rather than
reimplementing any of it in TypeScript, because a second copy of these rules is a
copy that can disagree.

## Contents

- `daemon` — where the workspace's daemon is, whether it is alive, stopping it
  and waiting until it is really gone, and enumerating the daemons running
  locally.
- `client` — starting a daemon if none is running, and speaking framed JSON-RPC
  to it (`connect`, `DaemonClient`).
- `selfupdate` — replacing this installation, whether it is the Python wheels or
  the standalone bundle (see below).

The address itself — which socket serves which workspace, and the liveness probe
— comes from `partcad-utils`, because it is the rendezvous the *daemon* has to
agree on too. `daemon` re-exports it, so a client has one import for everything
about daemons.

## Updating PartCAD itself

`selfupdate` is what `pc upgrade` runs, and — through `pc upgrade` — what the VS
Code extension's "Update PartCAD" runs. It is the only implementation of the
operation. (`pc update` is a different command: it refetches the packages a
package imports, and has nothing to do with this.)

It knows nothing about daemons, even though it sits beside the module that does.
A caller passes `before_install`, which runs once a newer version is confirmed
and before the first byte is written; `pc upgrade` uses it to stop every local
daemon and wait for them, because they are all executing the files about to be
replaced.

Nothing is ever written over the running installation. A new standalone bundle is
installed beside the old one, under `<install-dir>/<version>/`, which is what
lets a frozen `pc` update itself, is required on Windows (deleting a running
executable fails outright), and leaves a daemon that outlived the stop serving
from intact files. Superseded bundles are then removed — all of them: the idle
ones immediately, and the one this process is running out of by a detached reaper
that waits for the process to exit first.
