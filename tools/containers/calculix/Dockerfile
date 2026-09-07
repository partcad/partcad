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
#
# The `lib*` names are what the OCP wheel installed below dlopen()s and does not
# bundle: OpenCASCADE is a visualization toolkit as much as a modelling one, so
# it links GL, X and fontconfig even where nothing is ever drawn. They are named
# here rather than left to chance because the failure without them is an
# ImportError deep in a sandbox, not a missing package a user could act on.
RUN apt-get update \
  && apt-get install --yes --no-install-recommends \
    calculix-ccx \
    python3 \
    python3-gmsh \
    python3-numpy \
    python3-flask \
    python3-pip \
    libgl1 \
    libglu1-mesa \
    libgomp1 \
    libfontconfig1 \
    libfreetype6 \
    libglib2.0-0 \
    libice6 \
    libsm6 \
    libx11-6 \
    libxext6 \
    libxrender1 \
  && rm -rf /var/lib/apt/lists/*

# What Debian does not have. All three are what the analysis is handed rather
# than what it computes with:
#
#   * `cadquery-ocp` is OpenCASCADE's Python binding, and it is here because of
#     how an implementation receives its shape. PartCAD sends geometry as a
#     serialized BREP and the sandbox rebuilds it (`wrappers/ocp_serialize.py`),
#     so a sandbox with no OCCT cannot read its own input -- the wrapper fails
#     before the implementation's first line runs. Pinned to the version the
#     repository pins in `pyproject.toml`, so that what a container decodes and
#     what a Python sandbox decodes are the same OCCT.
#   * trimesh writes the glTF the analysis answers with.
#   * flask-jsonrpc is what serves this image (see `pc-container-json-rpc.py`).
#
# All three publish wheels for both architectures -- which is exactly why they
# can come from pip while gmsh and `ccx` cannot.
RUN pip install --no-cache-dir --break-system-packages \
    cadquery-ocp==7.9.3.1.1 \
    trimesh \
    flask-jsonrpc

# Prove the image is what it claims before it is ever published -- that it can
# decode a shape, mesh it and solve it. `verify.py` says what each check is for
# and why the first one is not as redundant as it looks. It is run here and
# removed in the same layer: it is a check on the build, not a part of the
# image.
COPY calculix/verify.py /tmp/verify.py
RUN python3 /tmp/verify.py && rm /tmp/verify.py

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
