# The CalculiX runtime container

What `//pub/feature/cae/calculix` runs in when it cannot run in a Python sandbox.

## Why this exists

A PartCAD implementation normally runs in a Python sandbox, and a Python sandbox can only bring what pip can
install. The CalculiX analyses need two things pip cannot supply everywhere:

* **`ccx`**, the solver, which is a native executable and not a Python package at all; and
* **gmsh**, the mesher, which publishes four wheels per release — macOS x86_64, macOS arm64, manylinux x86_64
  and win_amd64 — and **no linux aarch64 wheel and no source distribution**, in every release from 4.12 through
  4.15. On 64-bit ARM Linux there is nothing to install and nothing to build from.

Debian builds both, for amd64 and arm64 — confirmed by the first build of this image, which located
`calculix-ccx` and `python3-gmsh` and failed only on `python3-trimesh`, which Debian does not package. trimesh
and flask-jsonrpc therefore come from pip: both are pure Python, which is precisely why they *can*, and gmsh
cannot.

There is a third thing, and it is not the analysis's own: **OpenCASCADE**, as the `cadquery-ocp` wheel. PartCAD
sends geometry as a serialized BREP and the sandbox rebuilds it before the implementation's first line runs
(`wrappers/ocp_serialize.py`), so a sandbox with no OCCT cannot read its own input. It is pinned to the version
`pyproject.toml` pins, so that a container and a Python sandbox decode the same way. That wheel does publish for
both architectures, and the `lib*` names in the Dockerfile are what it `dlopen()`s and does not bundle — OCCT
links GL, X and fontconfig even where nothing is ever drawn.

That puts **two** OpenCASCADE builds in the image — Debian's, which `python3-gmsh` links against, and the one in
the wheel — and an analysis loads both into one process. `verify.py` exercises exactly that, in the order the
wrapper does it; see below.

So the plugin brings its own dependencies by bringing this image,
which is what makes "the analysis could not run" a failure of the implementation rather than a fact of life:
once a plugin carries what it needs, the only thing left that can stop it is a machine with no container
runtime at all.

## What it does not carry

The plugin's code. PartCAD sends the implementing package and the wrapper as directories at run time, so this
image stays a *runtime*. An image carrying the code would be a release of `partcad-cae-calculix` under another
name, and the two would have to move in lockstep — a user fetching a newer version of the package would still
get the code baked in here.

## The allowlist

`PC_CONTAINER_ALLOWED_COMMANDS` names what the RPC server will run: the interpreter, and `ccx` for anything
that wants to reach the solver directly. That allowlist is the whole of the server's isolation, which is why it
is set here, in the image, and read once at start-up — a request cannot widen it.

## Architectures

Built for **linux/amd64 and linux/arm64**. Single-architecture would be a plugin that has not brought its
dependencies on half the machines it claims to support, and under `pc test`'s rules that reads as the
implementation failing — which it would be.

## The tag

Every other image here is tagged with PartCAD's version. This one is tagged with **a hash of what it is built
from**, printed by `image-tag.sh`, because the thing that pulls it is a plugin in its own repository that cannot
name a version of PartCAD. The tag being content-derived buys three things: it is immutable, so a plugin's pin
keeps working after this image is next edited; a branch that edits the image publishes a *new* tag rather than
replacing the one everything else is using; and a branch and its merge build the same tag, so nothing has to be
re-pinned when it lands.

To change the image and re-point the plugin at it: edit, run `tools/containers/calculix/image-tag.sh`, push (the
`Build Docker Containers` job publishes it), then set that tag in the plugin's `container:` declaration.

## Verifying it

The build proves the image before it can be published, and `verify.py` says what each check is for. The first is
the one that is not obvious: OCCT builds a box, writes it as a STEP file, and gmsh reads that file back and
meshes it — two OpenCASCADE libraries in one process, in the order an analysis loads them, on a shape that goes
all the way through. (That the shape travels through a *file* is deliberate on both sides: `mesh_shape()` in the
CalculiX package writes STEP for exactly this reason, since handing gmsh an in-memory shape would put a shape
belonging to one OCCT into the other.) Then numpy and trimesh, then `ccx`.

An image that cannot decode, mesh or solve fails to build rather than failing later in front of a user who had
every reason to think their machine was equipped.
