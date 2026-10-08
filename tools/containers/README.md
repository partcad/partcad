# Container images

Two kinds of image live here, and they are not the same kind of thing.

* **The Python base images**, `partcad-container-python`. One per supported Python version and
  architecture. These are what the `docker` sandbox runs by default, and what a third-party package builds
  `FROM` when it needs something pip cannot install. Everything in the *Base image contract* below is a
  promise these make and that a derived image inherits.
* **Application images** -- `partcad-container-kicad`. A tool PartCAD drives rather than an interpreter it
  runs scripts in.

A plugin's runtime image belongs in the plugin's own repository, not here: an image built here would make a
release of PartCAD carry a release of somebody else's runtime, and the two do not move together. The CalculiX
runtime was built here and now is not — see `partcad/partcad-cae-calculix` for what that looks like.

`_common/` holds what both share: `pc-container-json-rpc.py`, the service that accepts a command and runs
it. It is a byte-for-byte copy of `src/partcad_utils/container_service.py`, kept identical by a test, and it
imports only the standard library -- `requirements.txt` beside it is empty on purpose.

## How PartCAD runs a container

Every container PartCAD starts -- the `docker` sandbox's, KiCad's, a plugin's `container:`, the
`partcad-service-remote-docker` pool's -- is started by `partcad_utils.containers`, one way:

* **Named after what it is**, `partcad-<role>-<tag>-<identity>`: the role (`sandbox`, `kicad`,
  `plugin-<name>`, `remote`), the image's tag, and a digest of everything fixed at creation -- the image,
  the mounts, the environment, the allowlist, the user, and the service's own source. Two callers needing the
  same container share it; two needing different ones never touch each other's. The digest is also a
  `partcad.identity` label, and a container answering to the name with another identity, or running an
  image other than the one its tag resolves to now, is replaced rather than trusted.
* **Labelled** `partcad.container`, `partcad.version`, `partcad.role`, `partcad.identity` and
  `partcad.mode`, so `pc system prune` finds every one of them.
* **Running PartCAD's service, not the image's.** The service is copied into the container after it is
  created and before it starts, and is its command (`python3 /.partcad-service/container_service.py`).
  So the protocol spoken is always the running PartCAD's own, whatever copy -- if any -- the image carries.
  The one thing an image needs for this is a `python3` on `PATH`.
* **Reached on a published port** -- loopback when the daemon is this machine, every interface when it is
  another (`DOCKER_HOST`) -- or on its own network address from a dev container on the same daemon, and only
  once its service answers. Every container gets a token of its own, which every request must carry.

Files reach it one of two ways, chosen by the `useDockerRemote` option (`PC_USE_DOCKER_REMOTE`):

* **`mount`** (the default) -- the directories under *Mounts* below are bind-mounted at the paths they have
  here, and commands name files by those paths.
* **`upload`** -- nothing from this machine is mounted. The files a command reads travel with the request
  (`input_files`, `input_dirs`) and what it writes comes back with the answer (`output_files`,
  `output_dirs`). A sandbox's environment lives in a named volume on the daemon's side. This is what a
  daemon that cannot see this machine's files needs.

## Base image contract

A derived image is talked to exactly the way a base image is, so what the base guarantees is what PartCAD is
entitled to assume. Change any of it and PartCAD cannot run scripts in your image.

| | |
| --- | --- |
| **Service** | PartCAD runs its own copy of the service in every container and does not use the image's entrypoint (see above). An image may still carry `pc-container-json-rpc.py` as its entrypoint, serving JSON-RPC on **port 5000** at `/jsonrpc`, for anybody running it by hand. What the image must have is a `python3` on `PATH`. |
| **Working directory** | `/pc`, holding the service. |
| **State** | `PC_INTERNAL_STATE_DIR` is set and writable by the running user. |
| **Commands** | `PC_CONTAINER_ALLOWED_COMMANDS` maps a name to an absolute executable path, or to `null` for "wherever `PATH` finds it". A caller names `python`; the image decides what that is. PartCAD adds what a container needs on top of the image's own list when it creates the container, and a path the image pins is never unpinned by a `null`. A name not listed cannot be run. |
| **Sandbox root** | `PC_CONTAINER_SANDBOX_ROOT` (default `/pc-sandbox`) is where the `remote` sandbox's environments are mounted. The service also accepts a command that *is* the `bin/python` of an environment under it, because an environment built at run time carries a Python version the allowlist could not have named. Nothing else there may be run, and the file has to exist. |
| **User** | Not `root`. The mounted directories are the user's own files, and files the sandbox creates have to stay usable outside it. |
| **Mounts** | The home directory, the temporary directory, the context root, the internal state directory and PartCAD's own installation, mounted at the paths they have on the host (drive-letter-mapped on Windows, where identical paths are not possible) and all writable. Nested paths are dropped, so on an ordinary machine the home directory covers the context root, the state directory and the installation, leaving it and the temporary directory -- two mounts, or one on Windows, where the temporary directory is inside the user profile. Nothing may occupy those paths in the image. The container is named after the image and the mount set, so it is reused across contexts and across runs that need the same mounts; a new version, a new tag or another mount set makes a new one. None of this applies in `upload` mode, which mounts nothing. |
| **Interpreter** | The `python` entry in the allowlist is a real CPython of the version the tag names, with `pip` available. PartCAD installs a package's requirements into a mounted environment, so the interpreter must be able to install and import from a directory that did not exist when the image was built. |

What a derived image is expected to change: the packages installed in it, and nothing else. Add your apt
packages, add wheels that need compiling, leave the service, the port, the working directory, the user and
the allowlist alone. Adding an entry to the allowlist is fine and is how a package exposes a native tool to
its own scripts; removing `python` is not — it is the name the `remote` sandbox builds its environment with,
and an image without it serves no sandbox at all.

## Why the wrappers are mounted and not baked in

PartCAD hands the interpreter in your image its wrapper scripts by path, out of the installation mounted above.
An obvious-looking alternative is to bake them into the base image, where they would cost nothing to reach --
and the reason not to is that **your** image is the one that would carry them.

A derived image is built `FROM` some base, once, at whatever PartCAD release its author built against, and is
then pinned by the packages that use it for as long as it works. Baked-in wrappers would make that image carry
that release's wrappers for ever, and PartCAD would run them against today's wrapper protocol -- a silently
wrong answer where a mount can only ever produce a missing file. It would also mean that editing a wrapper in a
checkout changed nothing until an image was rebuilt, in the sandbox that is the default.

So the wrappers a container runs are always the running PartCAD's own, and an image is only ever asked for an
interpreter. Nothing about this is a burden on a derived image: the mount is PartCAD's to make, and all your
image has to do is leave those paths alone, as the contract above already says.

## Labels

Every image PartCAD builds carries:

```text
partcad.image=1                  # this is a PartCAD-managed image
partcad.version=<release>        # the PartCAD release it was built for, if any
```

`pc system prune` removes images and containers carrying `partcad.image`, and **only** those — a user's
unrelated images are never touched. `pc system prune --stale` narrows that to images whose `partcad.version`
is not the running one, plus containers nothing is using.

Third-party images are asked to carry the same labels, with `partcad.version` omitted or set to your own
version. It costs two lines and it is the difference between an image `pc system prune` can clean up and one
that accumulates until somebody notices the disk is full. An unlabelled image still works.

## Architecture in the tag

PartCAD appends the machine's architecture before pulling, and falls back to the bare name:

```text
ghcr.io/example/solver:1a2b3c4d5e6f-arm64      # tried first
ghcr.io/example/solver:1a2b3c4d5e6f            # used if that does not exist
```

So publish `-amd64` and `-arm64` tags and let packages pin the bare name. The fallback exists so that a first
experiment works before its author has heard of any of this; the public index does not accept a package whose
image has only the bare tag, because that is a package that works on one machine.

A manifest list under the bare tag also works and needs nothing from PartCAD, but it needs `buildx` and a
registry that supports it — the suffixes are the path that always works.

## Checking your image

`verify.py` beside a Dockerfile is run at build time and fails the build rather than publishing something
broken. Write one that imports what your scripts import and exercises the tool you added —
`verify_image.py` in the CalculiX plugin's repository meshes a box and runs the solver, which is the whole
pipeline in twenty lines.

The base image ships a conformance check for the contract above; run it in your own build to find out that
you broke the service before your users do.

## Size

The base image is the floor under every derived image, and it is the reason the `docker` sandbox can be the
default rather than an option — a sandbox that costs more to provision than conda does is one people turn
off. Keep additions to what is actually imported at run time, drop apt lists in the same layer that creates
them, and prefer a wheel to a toolchain.

## How a change here is tested, published, and released

Three different moments, and the gap between the first two cost a fortnight of red CI.

**Tested — every run.** Every CI job that renders on Linux gets this image under the tag PartCAD resolves,
through `.github/actions/sandbox-image`, and outside a push to `devel` or `main` it gets it by **building
this tree**. That is what makes a change here provable: `resolve_image` uses a name already present locally
without asking a registry, so the sandbox runs in the image this commit describes. Before that, those jobs
pulled the published tag — so a fix here could not be shown to work and a regression here could not be
caught, and "green" meant the last publish had been good.

**Published — the version bump on `devel`.** `build-containers` pushes `<release>-py<X>-<arch>`, once, from
the run whose head commit is `Version updated from … to …`. That is what makes the version tag the immutable
thing a package's pin can mean. It used to be re-pushed by every nightly, which is to say the tag documented
as immutable was rewritten daily with whatever `devel` held. A `workflow_dispatch` publishes too, as the
recovery path for a bump whose push failed — it publishes whatever tree it runs on, so dispatch it at the
bump commit and nowhere else.

**Released — the same version reaching `main`.** The moving tag `py<X>-<arch>`, which is what a third-party
plugin builds `FROM` and what that plugin's CI tests against, is pointed at the version tag by
`docker buildx imagetools create`. No rebuild: the Dockerfile would be the same but `apt-get` and `pip`
resolve against the day they run, so a rebuild would hand plugin authors an image nothing had tested. The
retag copies the manifest, so the two tags name the same bytes. This too used to happen nightly, which
pointed every plugin's CI at an unreleased `devel` build.

On a push to `devel` or `main` the rendering jobs **pull** the published tag instead of building, because
there the published image is the subject rather than a stand-in for it — and fall back to building if it is
not there yet, which is the ordinary case on the bump run itself, where the publish and the jobs that would
pull it are in the same run.
