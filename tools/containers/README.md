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
it, and the requirements it needs.

## Base image contract

A derived image is talked to exactly the way a base image is, so what the base guarantees is what PartCAD is
entitled to assume. Change any of it and PartCAD cannot run scripts in your image.

| | |
| --- | --- |
| **Service** | `pc-container-json-rpc.py` runs as the entrypoint and serves JSON-RPC on **port 5000** at `/jsonrpc`. |
| **Working directory** | `/pc`, holding the service. |
| **State** | `PC_INTERNAL_STATE_DIR` is set and writable by the running user. |
| **Commands** | `PC_CONTAINER_ALLOWED_COMMANDS` maps a name to an absolute executable path. A caller names `python`; the image decides what that is. A name the image does not list cannot be run — this is the whole of the service's isolation. |
| **Sandbox root** | `PC_CONTAINER_SANDBOX_ROOT` (default `/pc-sandbox`) is where the `remote` sandbox's environments are mounted. The service also accepts a command that *is* the `bin/python` of an environment under it, because an environment built at run time carries a Python version the allowlist could not have named. Nothing else there may be run, and the file has to exist. |
| **User** | Not `root`. The mounted directories are the user's own files, and files the sandbox creates have to stay usable outside it. |
| **Mounts** | The home directory, the temporary directory, the context root, the internal state directory and PartCAD's own installation, mounted at the paths they have on the host (drive-letter-mapped on Windows, where identical paths are not possible) and all writable. Nested paths are dropped, so on an ordinary machine the home directory covers the other three and there is one mount. Nothing may occupy those paths in the image. The container is named after the image alone, so it is reused across contexts and across runs; only a new version or tag makes a new one. |
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
