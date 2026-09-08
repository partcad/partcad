# Container images

Two kinds of image live here, and they are not the same kind of thing.

* **The Python base images**, `partcad-container-python`. One per supported Python version and
  architecture. These are what the `docker` sandbox runs by default, and what a third-party package builds
  `FROM` when it needs something pip cannot install. Everything in the *Base image contract* below is a
  promise these make and that a derived image inherits.
* **Application images** -- `partcad-container-kicad`, and the CalculiX runtime that lives in its own
  repository now. A tool PartCAD drives rather than an interpreter it runs scripts in.

`_common/` holds what both share: `pc-container-json-rpc.py`, the service that accepts a command and runs
it, and the requirements it needs.

> **Status.** The base image contract below is what the `docker` sandbox is being built against. The image
> matrix, the architecture suffixes and the labels are landing with it; `python/Dockerfile` today builds a
> single 3.12 image on the dev container and predates all of this. Do not read this file as a description of
> what is published right now.

## Base image contract

A derived image is talked to exactly the way a base image is, so what the base guarantees is what PartCAD is
entitled to assume. Change any of it and PartCAD cannot run scripts in your image.

| | |
| --- | --- |
| **Service** | `pc-container-json-rpc.py` runs as the entrypoint and serves JSON-RPC on **port 5000** at `/jsonrpc`. |
| **Working directory** | `/pc`, holding the service. |
| **State** | `PC_INTERNAL_STATE_DIR` is set and writable by the running user. |
| **Commands** | `PC_CONTAINER_ALLOWED_COMMANDS` maps a name to an absolute executable path. A caller names `python`; the image decides what that is. A name the image does not list cannot be run — this is the whole of the service's isolation. |
| **User** | Not `root`. The mounted directories are the user's own files, and files the sandbox creates have to stay usable outside it. |
| **Mounts** | The context root and the internal state directory are mounted at the paths they have on the host (drive-letter-mapped on Windows). Nothing may occupy those paths in the image. |
| **Interpreter** | The `python` entry in the allowlist is a real CPython of the version the tag names, with `pip` available. PartCAD installs a package's requirements into a mounted environment, so the interpreter must be able to install and import from a directory that did not exist when the image was built. |

What a derived image is expected to change: the packages installed in it, and nothing else. Add your apt
packages, add wheels that need compiling, leave the service, the port, the working directory, the user and
the allowlist alone. Adding an entry to the allowlist is fine and is how a package exposes a native tool to
its own scripts; removing `python` is not.

## Labels

Every image PartCAD builds carries:

```
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

```
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
`calculix/verify.py`, in the CalculiX plugin's repository, builds a solid with OpenCASCADE, meshes it and
solves a deck, which is the whole pipeline in twenty lines.

The base image ships a conformance check for the contract above; run it in your own build to find out that
you broke the service before your users do.

## Size

The base image is the floor under every derived image, and it is the reason the `docker` sandbox can be the
default rather than an option — a sandbox that costs more to provision than conda does is one people turn
off. Keep additions to what is actually imported at run time, drop apt lists in the same layer that creates
them, and prefer a wheel to a toolchain.
