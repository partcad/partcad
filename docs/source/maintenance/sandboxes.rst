##########
Sandboxes
##########

PartCAD imports no CAD kernel of its own, and runs no part script in its own interpreter. Every script --
a CadQuery part, a Chili3D part, an importer reading a STEP file, an exporter writing one -- runs in a
**sandbox**: an environment PartCAD provisions, holding the interpreter that script asked for and the
dependencies its package declared.

That is dependency management first and isolation second. Two packages can want different versions of
build123d, or a Node.js a decade apart, and both have to work in one command without either one's
dependencies reaching the other or reaching PartCAD itself. A sandbox is how a package brings its own
dependency tree without polluting yours -- which is also why anything built in one is cached under the
environment that built it (see :doc:`/maintenance/caching`), so moving a package to another interpreter re-renders
rather than serving what the previous one produced.

There are two, because there are two languages a part can be written in.


.. _python-sandbox:

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

**A script is forked rather than started**, on Linux, in the sandboxes whose
interpreter runs on this machine (``venv``, ``conda`` and ``none``). Starting an
interpreter and importing the CAD stack into it takes seconds -- build123d alone
is five or more -- and running a small part takes a few hundredths of one, so
PartCAD keeps one interpreter per sandbox environment that has done those
imports, and each script runs in a copy of it, made with ``fork``. A copy is
made from an interpreter that has run nothing, so no script can see what
another one did, and one that crashes takes only itself with it. The
interpreter is started once an environment has had a second script to run --
the scripts before it is ready start as they always did -- and is replaced
whenever anything is installed into the environment, by this PartCAD or by any
other. It holds a few hundred megabytes while it waits, and goes after ten
minutes without a script. It is not used on macOS or Windows, nor in the
``docker``, ``remote`` and ``pypy`` sandboxes, and ``pythonSandboxZygote:
false`` (``PC_PYTHON_SANDBOX_ZYGOTE=false``) turns it off on Linux too. It is
only ever a shortcut: a script it cannot take, or an environment whose
interpreter refused to be one (something it imported left a thread running,
say), is started the ordinary way.

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

"Can actually provide" also includes the **filesystem**. The container gets your
directories bind-mounted into it, and that only means anything if the daemon
being asked is on the same filesystem as PartCAD. Two ordinary arrangements
where it is not: a dev container with the host's ``/var/run/docker.sock`` bound
into it, and ``DOCKER_HOST`` pointing at another machine. There the daemon
resolves your paths against a filesystem of its own, Docker creates whatever is
missing -- empty, and owned by root -- and the container starts perfectly well
with directories that are not yours. Nothing announces that; the first symptom
is a permission error on a directory you can write to. So PartCAD asks the
daemon directly, once: it writes a file and has a throwaway container look for
it. A daemon *inside* this container -- Docker in Docker -- shares the filesystem
and is fine.

A dev container is usually fine too. When the file is not found and PartCAD is
running in a container *of that daemon*, it reads that container's mounts --
the workspace bound in from the host, a volume -- and binds each directory from
where the daemon keeps it, at the path it has inside, then asks again. This
repository's own dev container keeps ``~/.partcad`` and ``/tmp`` on volumes for
exactly this reason. ``PC_DOCKER_MOUNT_SOURCES`` (``here=there`` pairs, separated
by ``;``) says the same by hand. Only when there is no such answer -- a
``DOCKER_HOST`` on another machine, or a directory the sandbox needs on none of
the container's mounts -- is the daemon one this sandbox cannot use, and PartCAD
says so and uses conda or a virtual environment, both of which stay on this
machine.

.. _use-docker-remote:

**A daemon that cannot see your files at all** -- ``DOCKER_HOST`` on another
machine, shared by a team -- is what ``useDockerRemote`` is for:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    useDockerRemote: true

(``PC_USE_DOCKER_REMOTE=true`` in the environment.) Nothing is bind-mounted
then. Every file a command reads is sent to the container with the command, and
every file it writes is sent back with the answer; a sandbox's environment lives
in a Docker volume on the daemon's side, built once and reused. It applies to
every container PartCAD starts -- the ``docker`` sandbox, KiCad imports, a
plugin's ``container:`` and an application ``pc ide open`` runs in a container
alike -- and off by default, because sending a package
costs time that a shared filesystem does not. What is sent is sent once: each
container keeps the files it has been given, by their content, so a command
sends only what it does not have yet -- PartCAD's own wrappers once per
container, a package once and then whatever changed in it. It needs no
service in between: that is the difference from the ``remote`` sandbox below,
which reaches containers through ``partcad-service-remote-docker`` and never
talks to Docker itself.

Containers on another machine are reached on a port that daemon publishes on
every interface, protected by a token of each container's own -- **in plain
HTTP**. Unlike the ``remote`` sandbox below, which refuses to send a request off
this machine unencrypted, this does not encrypt yet: the token and the files
sent with each command can be read by anyone on the network between here and
that daemon, and ``DOCKER_HOST=ssh://`` does not change that, because SSH then
carries Docker's own API and not the containers' ports. PartCAD says so once per
daemon. Until it is encrypted, use it only on a network you trust -- and treat a
daemon shared this way as you would any Docker daemon on a network: anybody who
can reach the daemon itself can do anything on that host.

That fallback is only ever for a choice PartCAD made. Say ``pythonSandbox:
docker`` yourself and it is obeyed: an image that cannot be had, or a daemon
that cannot see your files, is then a failure, because being unable to do what
was asked is not a reason to quietly do something else.

.. _docker-sandbox:

The ``docker`` sandbox
======================

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

The container is named after its image and everything it is created with -- how
files reach it, its mounts and volumes, its environment, what it may run, the
user it runs as, the interpreter PartCAD's service runs on, and the source of
that service (``partcad-sandbox-<tag>-<identity>``). So it outlives the process
that started it: the next ``pc`` command with the same mounts finds it warm
rather than paying to start one, and a new image tag -- every release has its
own -- another mount set, or a change to the service is a different container. It carries PartCAD's labels, so ``pc system prune`` clears out the
ones a machine has stopped needing.

Because the state directory is mounted rather than copied, ``pip`` installs
persist across container restarts and the environment locking, the install
guards and the cache all work unchanged. Sandbox environments are named after
the image that built them, so a package rendered against one image never reuses
what another installed -- what ``pip`` resolves and compiles depends on the
native libraries underneath it, and two images do not have the same ones.

.. _remote-sandbox:

The ``remote`` sandbox
======================

``remote`` makes no assumption that the container can see your disk. The
directories a command needs are sent to it, and the files it wrote are sent
back. That costs a copy -- of each file once per container, since the container
keeps what it has been sent and is asked for nothing it already has -- and it
buys a sandbox that can be anywhere: another machine, another architecture, a
build farm.

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

A client and a service need not be the same release: the client asks the
service what it speaks before its first request, and talks to one from before
that question the way it always did -- with every file sent on every command.
The intent beyond that is a filesystem the container mounts and pulls files
through one at a time, at which point ``remote`` becomes as cheap as ``docker``
and stops being a trade.




.. _javascript-sandbox:

The JavaScript sandbox
======================

A ``chili3d`` part is an ES module, so it runs in Node.js rather than in Python, and it gets a sandbox of
its own: ``javascriptSandbox``, with its own two values.

======================= ====================================================================
``none``                The Node.js already on this machine.
``conda``               A Node.js conda provisions, for a machine that has none.
======================= ====================================================================

The default is ``none`` where the host has a ``node``, and ``conda`` where it does not but conda can supply
one. That asymmetry with Python is deliberate rather than an oversight. PartCAD's own interpreter is the
wrong one to render a Python part in, so a Python sandbox always has to be provisioned; a host Node.js, by
contrast, is simply used when there is one, because it costs nothing to use and it is not the interpreter
that has to be isolated. **The dependency tree is**, and that is provisioned either way: a package's
``javascriptRequirements`` are installed into a tree of its own, keyed like every other sandbox, whichever
of the two values is in force.

``javascriptVersion`` asks for a major version of Node.js, per package or per part, the way
``pythonVersion`` asks for a Python. Under ``conda`` that is provisioned; under ``none`` a host Node.js that
does not match is reported rather than silently used.

.. code-block:: yaml

  # partcad.yaml
  javascriptVersion: 22
  javascriptRequirements:
    - chili3d@0.5.0

Set it the way every other option is set -- in ``~/.partcad/config.yaml``, or as ``PC_JAVASCRIPT_SANDBOX``
in the environment (see :doc:`/maintenance/automation`):

.. code-block:: yaml

  javascriptSandbox: conda



Containers PartCAD manages
==========================

Every image PartCAD builds is labelled as its own, and ``pc system prune``
removes the images and containers carrying those labels -- never anything else
on the machine. ``pc system prune --stale`` removes only what is out of date:
images from PartCAD releases other than this one, and containers nothing is
using.

Third-party images are asked, by convention, to carry the same labels. An image
that does not is still usable; it simply cannot be told apart from the rest of
what you have installed, so ``pc system prune`` leaves it alone.
