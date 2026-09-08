# The Python base images

`ghcr.io/partcad/partcad-container-python` — what the `docker` Python sandbox runs in, and what a package
that needs something pip cannot install builds `FROM`.

One image per supported Python version and architecture:

```
ghcr.io/partcad/partcad-container-python:<release>-py<version>-<arch>    # immutable, pin this
ghcr.io/partcad/partcad-container-python:py<version>-<arch>              # moving, test against this
```

`<version>` is 3.10 through 3.14, `<arch>` is `amd64` or `arm64`. PartCAD appends the architecture itself
(see `docker_image.candidates`), so a package names the tag without one and gets whichever it needs.

## What is in it, and what is not

An interpreter, the JSON-RPC service that runs commands in it, and the shared libraries an OpenCASCADE wheel
`dlopen()`s. That is all.

**The CAD stack is not baked in**, and that is the design rather than an omission. PartCAD creates a virtual
environment in a directory it mounts into the container and installs into that, so a package renders against
its own `pythonRequirements` at the version it asked for — not against whatever was frozen into an image
months ago. Baking the stack in would also mean rebuilding every image for every change to it, and would put
a gigabyte under every derived image before its author added anything.

Which is why the base is `python:*-slim` rather than the dev container this used to build on. The `docker`
sandbox is the default wherever a container runtime answers, and a default that costs more to provision than
conda does is a default people turn off.

## Building on it

```dockerfile
FROM ghcr.io/partcad/partcad-container-python:0.8.58-py3.11

RUN apt-get update \
  && apt-get install --yes --no-install-recommends calculix-ccx \
  && rm -rf /var/lib/apt/lists/*

# What your scripts may run, if you added a native tool.
ENV PC_CONTAINER_ALLOWED_COMMANDS='{"python": "/usr/local/bin/python3", "ccx": "/usr/bin/ccx"}'

# Say so, so `pc system prune` can clean up after you.
LABEL partcad.image="1"

RUN python3 /pc/verify.py
```

That last line is the point of `verify.py` being kept in the image rather than deleted after the build: it
checks the contract in `../README.md` and says, for each thing it checks, what breaks when it is wrong. Run
it in your own build and find out you moved the interpreter before your users do.

Then name it from your package:

```yaml
dockerImage: ghcr.io/you/your-image:1a2b3c4d
```

and keep declaring `pythonRequirements` beside it. The image says where your package runs *best*; a host that
already has the native pieces installed runs the same package in a conda or venv sandbox, and only a package
that declares both works in either.

## Building one here

```shell
docker build \
  --build-arg PYTHON_VERSION=3.11 \
  --build-arg PARTCAD_VERSION=0.8.58 \
  -t partcad-container-python:3.11 \
  -f tools/containers/python/Dockerfile tools/containers
```

The build context is `tools/containers`, not the repository root: the image takes `pc-container-json-rpc.py`
and its requirements from `_common/`, which every image here shares.

CI builds the matrix in the `Build Docker Containers` job of `test.yml`.
