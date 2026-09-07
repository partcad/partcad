# The CalculiX runtime container

What `//pub/feature/cae/calculix` runs in when it cannot run in a Python sandbox.

## Why this exists

A PartCAD implementation normally runs in a Python sandbox, and a Python sandbox can only bring what pip can
install. The CalculiX analyses need two things pip cannot supply everywhere:

* **`ccx`**, the solver, which is a native executable and not a Python package at all; and
* **gmsh**, the mesher, which publishes four wheels per release — macOS x86_64, macOS arm64, manylinux x86_64
  and win_amd64 — and **no linux aarch64 wheel and no source distribution**, in every release from 4.12 through
  4.15. On 64-bit ARM Linux there is nothing to install and nothing to build from.

Debian builds both, for amd64 and arm64. So the plugin brings its own dependencies by bringing this image,
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

## Verifying it

The build proves the image before it can be published: it imports gmsh, initializes it, imports numpy and
trimesh, and locates `ccx`. An image that cannot mesh or solve fails to build rather than failing later in
front of a user who had every reason to think their machine was equipped.
