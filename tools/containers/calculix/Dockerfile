# The runtime the CalculiX analyses run in, and nothing else.
#
# This image carries what pip cannot: `ccx`, which is a native executable, and
# gmsh, which publishes no wheel for 64-bit ARM Linux and no source
# distribution -- four wheels per release, none of them aarch64, in every
# release from 4.12 through 4.15. Debian builds both for amd64 and arm64, which
# is what lets a plugin be responsible for its own dependencies on a platform
# where pip cannot be.
#
# It does NOT carry the plugin's code. PartCAD sends the implementing package
# and the wrapper as directories at run time (see `runtime.pack_directory()`),
# because an image that carried the code would be a release of somebody else's
# repository and would have to move in lockstep with it. This is a runtime; the
# code comes from whatever version of the package the user fetched.
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

# `ccx` is the solver; `python3-gmsh` is the mesher's Python API, which is a
# separate package from the `gmsh` application. Both are what this image exists
# for, and both are what pip cannot supply on 64-bit ARM Linux -- Debian builds
# them for amd64 and arm64 alike.
#
# numpy comes from Debian for the same reason: it is compiled, so a
# distribution package is one fewer thing built per architecture.
RUN apt-get update \
  && apt-get install --yes --no-install-recommends \
    calculix-ccx \
    python3 \
    python3-gmsh \
    python3-numpy \
    python3-flask \
    python3-pip \
  && rm -rf /var/lib/apt/lists/*

# trimesh and flask-jsonrpc are not Debian packages. Both are pure Python, so
# pip installs them identically on either architecture -- which is exactly why
# they are the ones that can come from pip while gmsh cannot.
RUN pip install --no-cache-dir --break-system-packages trimesh flask-jsonrpc

# Prove the image is what it claims before it is ever published. Every one of
# these is a thing this image exists to provide, and a silent absence would
# surface much later as an analysis that "did not run" on a machine the user
# had every reason to think was equipped. An image that cannot mesh or solve
# should fail to build, not fail in front of a user.
RUN python3 -c "import gmsh; gmsh.initialize(); gmsh.finalize(); print('gmsh ok')" \
  && python3 -c "import numpy, trimesh; print('numpy', numpy.__version__, 'trimesh', trimesh.__version__)" \
  && ( ccx -v || ccx --version || true ) \
  && command -v ccx

# What this image is for. The allowlist is the whole of the RPC server's
# isolation, and it is per-image on purpose: a caller names a command and the
# server decides whether it exists, so an image built to run PartCAD
# implementations allows its interpreter and nothing else.
ENV PC_CONTAINER_ALLOWED_COMMANDS='{"python": "/usr/bin/python3", "ccx": "/usr/bin/ccx"}'

RUN mkdir -p /dot-partcad
ENV PC_INTERNAL_STATE_DIR=/dot-partcad
RUN mkdir -p /pc
WORKDIR /pc
COPY _common/pc-container-json-rpc.py ./

EXPOSE 5000

CMD ["python3", "pc-container-json-rpc.py"]
