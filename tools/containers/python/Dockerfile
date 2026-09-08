# The runtime the `docker` Python sandbox is built in, and the image a plugin
# that needs something pip cannot install builds `FROM`.
#
# It carries an interpreter and the service that runs commands in it, and
# deliberately nothing else. The CAD stack is NOT baked in: PartCAD creates a
# virtual environment in a directory it mounts and installs into that, so what a
# package renders against is the package's own `pythonRequirements` at the
# version it asked for, not whatever was frozen into an image months ago. An
# image that carried the stack would also have to be rebuilt for every change to
# it, and would be a gigabyte before anybody added anything.
#
# What that leaves here is the floor under every derived image, which is why it
# is `python:*-slim` and not a dev container: the `docker` sandbox is the default
# where a container runtime answers, and a default that costs more to provision
# than conda does is one people turn off.
#
# See `tools/containers/README.md` for the contract this promises and a derived
# image inherits.
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

# Repeated because an ARG before FROM is out of scope after it.
ARG PYTHON_VERSION=3.11
ARG PARTCAD_VERSION=dev

# What `pc system prune` recognises. Without these an image cannot be told from
# the rest of what a machine has installed, and cleaning up after ourselves would
# mean deleting somebody else's images. Third-party images are asked to carry
# them too; see the README.
LABEL partcad.image="1"
LABEL partcad.version="${PARTCAD_VERSION}"
LABEL partcad.python="${PYTHON_VERSION}"

ENV DEBIAN_FRONTEND=noninteractive

# The `lib*` names are what an OpenCASCADE wheel dlopen()s and does not bundle:
# OCCT is a visualization toolkit as much as a modelling one, so it links GL, X
# and fontconfig even where nothing is ever drawn. They are named here rather
# than left to chance because the failure without them is an ImportError deep
# inside a sandbox rather than a missing package a user could act on -- and
# every CAD sandbox PartCAD builds installs OCP, so this is not a niche case.
#
# `git` is here because a package may name a dependency by repository, and pip
# shells out to it.
#
# glib is asked for twice because it is named differently on the two Debian
# releases this matrix spans: the images for the older Python versions are built
# on bookworm, the newer ones on trixie, and trixie's 64-bit `time_t` transition
# renamed the package to `libglib2.0-0t64`. Asking for the new name and falling
# back is what lets one Dockerfile serve every version, rather than a
# conditional on a base image that will move again.
RUN apt-get update \
  && apt-get install --yes --no-install-recommends \
    ca-certificates \
    git \
    libgl1 \
    libglu1-mesa \
    libgomp1 \
    libfontconfig1 \
    libfreetype6 \
    libice6 \
    libsm6 \
    libx11-6 \
    libxext6 \
    libxrender1 \
  && (apt-get install --yes --no-install-recommends libglib2.0-0t64 \
      || apt-get install --yes --no-install-recommends libglib2.0-0) \
  && rm -rf /var/lib/apt/lists/*

# Not root. What the sandbox writes goes into mounted directories and has to
# stay usable outside the container -- and on Linux PartCAD runs the container
# as the host's own uid, which needs a home directory that is not `/root`.
RUN useradd --create-home --uid 1000 --shell /bin/bash pc

RUN mkdir -p /dot-partcad && chown pc:pc /dot-partcad
ENV PC_INTERNAL_STATE_DIR=/dot-partcad

WORKDIR /pc
COPY _common/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY _common/pc-container-json-rpc.py ./

# What a caller may run. The whole of the RPC service's isolation, and per-image
# on purpose: a caller names a command and the image decides whether it exists.
# A derived image adding a native tool of its own adds it here.
#
# It does not gate the `docker` sandbox, which reaches the interpreter through
# `docker exec` -- that is PartCAD running a command on its own machine, in a
# container it started, and there is no boundary there to enforce.
ENV PC_CONTAINER_ALLOWED_COMMANDS='{"python": "/usr/local/bin/python3"}'

# Kept in the image rather than removed after the build, unlike the check the
# CalculiX runtime runs: a derived image is supposed to run this to find out it
# broke the contract, and it cannot do that if the build that produced its base
# deleted it.
COPY python/verify.py ./verify.py
RUN python3 verify.py

EXPOSE 5000

USER pc
CMD ["python3", "pc-container-json-rpc.py"]
