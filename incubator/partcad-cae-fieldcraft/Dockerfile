# The runtime the FieldCraft analyses run in, where a container is how PartCAD runs them.
#
# Nothing needs it today: FieldCraft is one self-contained executable that
# `fieldcraft_common.py` fetches by itself, and gmsh is a pip wheel on every
# platform FieldCraft publishes for. What it buys is a pinned runtime with no
# fetch at run time -- for the machine whose PartCAD prefers the `docker`
# sandbox, and for CI -- and it is what a `dockerImage:` pin in `partcad.yaml`
# would name once this package has a repository that publishes it.
#
# It carries FieldCraft's command line, nothing else of FieldCraft's (the
# desktop app beside it in the release archive is left out), and the Python
# requirements stay in `partcad.yaml`: PartCAD installs them into the
# environment it creates. It does NOT carry this package's code; PartCAD mounts
# the package at run time.
#
# amd64 only: FieldCraft publishes no Linux arm64 build (its Nix flake builds
# one from source, which is the way to an arm64 image if one is ever wanted).
ARG PYTHON_VERSION=3.11
ARG ARCH=amd64

FROM ghcr.io/partcad/partcad-container-python:py${PYTHON_VERSION}-${ARCH}

LABEL partcad.image="1"
LABEL org.opencontainers.image.source="https://github.com/partcad/partcad-cae-fieldcraft"

USER root

# The release `fieldcraft_common.FIELDCRAFT_VERSION` pins, checked against the
# SHA-256 its `SHA256SUMS.txt` states. It links only glibc (2.35 or later).
ARG FIELDCRAFT_VERSION=0.8.1
ARG FIELDCRAFT_SHA256=987be64ed96f168d6e7224a8b3ddcac02aa3c17f448f6490c88b3868378e1708
RUN set -eu; \
    archive="fieldcraft-${FIELDCRAFT_VERSION}-linux-x86_64.tar.gz"; \
    python3 -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
      "https://github.com/tangency-labs/fieldcraft/releases/download/v${FIELDCRAFT_VERSION}/${archive}" "/tmp/${archive}"; \
    printf '%s  %s\n' "${FIELDCRAFT_SHA256}" "/tmp/${archive}" > /tmp/fieldcraft.sha256; \
    sha256sum -c /tmp/fieldcraft.sha256; \
    rm /tmp/fieldcraft.sha256; \
    mkdir -p /opt/fieldcraft/bin; \
    tar -xzf "/tmp/${archive}" -C /opt/fieldcraft/bin --strip-components=2 \
      "fieldcraft-${FIELDCRAFT_VERSION}-linux-x86_64/bin/fieldcraft-cli"; \
    rm "/tmp/${archive}"; \
    ln -s /opt/fieldcraft/bin/fieldcraft-cli /usr/local/bin/fieldcraft-cli

# Headless, on the CPU, and quiet: no GPU is looked for, no update is checked.
ENV FIELDCRAFT_GPU=cpu \
    FIELDCRAFT_SOLVE_BACKEND=cpu \
    FIELDCRAFT_TELEMETRY=0

# What a caller may run, extending the base image's allowlist rather than
# replacing it.
ENV PC_CONTAINER_ALLOWED_COMMANDS='{"python": "/usr/local/bin/python3", "fieldcraft-cli": "/usr/local/bin/fieldcraft-cli"}'

# Two checks: the base image's own, for the contract PartCAD talks to a
# container through; and this package's, which solves a cantilever with the
# command line in *this* image and compares it with its known answer.
COPY verify_image.py /tmp/verify_image.py
RUN python3 /pc/verify.py \
  && python3 /tmp/verify_image.py /usr/local/bin/fieldcraft-cli \
  && rm /tmp/verify_image.py

USER pc
