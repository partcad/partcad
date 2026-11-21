# The PartCAD image

`ghcr.io/partcad/partcad` -- PartCAD itself, for whoever would rather `docker run` it than install it: the `pc`
command line, the MCP server (`pc mcp`), the daemon and `partcad-service-remote-docker`, with conda and OpenSCAD.

```shell
docker run --rm -it \
  -v partcad-home:/home/pc/.partcad -v "$PWD:$PWD" -w "$PWD" \
  ghcr.io/partcad/partcad render my_part
```

How to run it -- the volume, the workspace, the host's Docker socket, an MCP client, CI -- is documented for users
under "Docker" in `docs/source/installation.rst`. This file is about how it is built and why it is built that way.

It is not one of the images beside it. Those are images PartCAD pulls *for itself*, to run something in, and
replaces on its own; this one is pulled by a person, and PartCAD never pulls it. Hence:

* **Plain tags**, one multi-architecture manifest each: `<version>`, `<major>.<minor>` and `latest`. The `-<arch>`
  suffix the sandbox images carry is for `docker_image.candidates` to append, not for a person to type.
* **`partcad.app`**, which `pc system prune` reads as "leave this alone" (`docker_prune.LABEL_APP`). It is built on
  the sandbox base and so inherits `partcad.image`, which no derived image can take away.
* **Its own CI subject**, `app-image` in `.github/actions/changed-scopes`: a change here builds and tests this image
  and leaves the eleven sandbox images alone.

## What is in it

* The GStreamer flavour of the Python base image (`../python`), for the default Python version: the shared libraries
  an OpenCASCADE wheel needs, the prebuilt `pycairo` wheel, cadmpeg, GStreamer for video, a non-root `pc` user.
  Everything a sandbox needs to render *inside* this container.
* The `partcad` wheel with its `lint` extra -- the very file the release uploaded to PyPI, from a build context of
  its own (`wheels`), never a second build of the source.
* **micromamba**, the release the standalone bundles carry, on `PATH`. PartCAD finds it there
  (`partcad_utils.conda.PATH_NAMES`) and so chooses the `conda` sandbox, which provisions whatever Python version a
  package asks for. `venv` would build every sandbox from the image's own 3.11.
* OpenSCAD (Debian's, as `dev-tools/setup-native.sh` installs it, because it exists for both architectures),
  `git-lfs`, `curl`, and `tini` as PID 1, which reaps the daemon `pc` starts and passes `docker stop`'s SIGTERM on.

## Two ways to run, one image

**Without the Docker socket** every CAD script runs in a conda sandbox inside this container. The container is the
isolation, which is the point for an AI agent's MCP server: what the agent's scripts can reach is the workspace and
the volume. What it cannot do is start containers: KiCad, a plugin's `container:`, a package's own `dockerImage`.

**With the host's socket** (`-v /var/run/docker.sock:/var/run/docker.sock`) PartCAD finds a daemon, chooses the
`docker` sandbox, and starts KiCad and plugin containers as siblings of this one. It reaches them in **`upload`
mode**, which the image turns on (`PC_USE_DOCKER_REMOTE=true`), and that is not optional:

* In `mount` mode PartCAD binds its own installation into every container -- the wrappers are mounted, never baked
  into an image (see "Why the wrappers are mounted" in `../README.md`). In this image that installation is in the
  image layer. The host's daemon binds from the *host's* filesystem, and `daemon_mounts` can map a container's
  volumes and binds back to it, but not its image layer. So `mount` mode would fail the probe, the `docker` sandbox
  would quietly be passed over for conda, and KiCad would fail.
* `upload` mode binds nothing: what a command reads is sent with it (by digest, so the wrappers go once per
  container), and the sandbox's environment lives in a volume on the daemon's side. It does not care where the
  daemon is -- Docker Desktop's VM, rootless Docker, Podman, a `DOCKER_HOST` elsewhere.

The sibling containers are reached at their address on Docker's bridge network, which `containers._candidates`
already tries after the published port, so nothing about the network has to be configured.

The socket hands the container control of the host's Docker, which is root on the host in all but name. That is
why nothing PartCAD writes -- not `pc init`'s MCP entry, not the MCP Registry's -- passes it on a person's behalf.

## The entrypoint

`entrypoint.sh` decides what to run and as whom, and is the only reason the image starts as root:

* `docker run <image> render my_part` is `pc render my_part`: a first argument that is one of `pc`'s commands (the
  installed wheel's own list, written at build time), an option, or nothing is handed to `pc`. Anything else runs as
  it is, which is what a CI system starting a shell in the image expects.
* A PartCAD command started as root runs as the **owner of the working directory** (or `PC_UID`/`PC_GID`), with the
  socket's group added when there is a socket -- so the files it writes belong to whoever owns the workspace on the
  host. An MCP client starts the image from a JSON file, where `--user "$(id -u)"` and
  `--group-add "$(stat -c %g /var/run/docker.sock)"` cannot be written. `--user`, and a root-owned working
  directory, leave it alone.
* `/home/pc` and its `.partcad` are `1777`, like the base's `/dot-partcad`, so whichever uid that is can use them; a
  new named volume takes that mode.

Nothing it does writes to standard output, which is `pc mcp`'s.

## Building and testing it

```shell
dev-tools/ci/build-partcad-image.sh                                  # this tree, this machine, as partcad:local
PC_IMAGE=partcad:local PC_SOCKET=true dev-tools/ci/test-partcad-image.sh
```

`build-partcad-image.sh` is the only thing that builds it: the "Container (PartCAD)" job in `test.yml` builds and
tests it with it, and `publish-image` in `deploy.yml` builds and publishes it with it, from the release's wheel.
`verify.sh` runs during the build and checks the pieces are there; `test-partcad-image.sh` runs the image the way a
person does -- a render without the socket, `pc mcp` over `docker run -i`, and with the socket a render in the
`docker` sandbox and the KiCad example's board. `tests/dev_tools/test_partcad_image.py` holds the Dockerfile to the
Python it has to agree with.

## Publishing

`publish-image` in `deploy.yml`: rehearsed on every version tag (both architectures built, nothing kept), and
published on `main` after the PyPI upload is approved, and before the MCP Registry entry that names its tag. A version
already in the registry is never rebuilt, so `latest` cannot move backwards.

The first publish creates the package on GHCR, and GHCR creates a package private. The job checks that the image
can be pulled without credentials and fails, naming the settings page, until somebody makes it public -- once.
