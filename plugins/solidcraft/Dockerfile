# The image this plugin's scripts run in where PartCAD's `docker` sandbox is in
# use, and the one `pc ide open --with solidcraft` runs SolidCraft in on a
# machine that has it nowhere else: PartCAD's own Python sandbox image with
# SolidCraft's command line tool and application on the PATH.
#
# It is an alternative, not a requirement. `partcad.yaml` names it as the
# package's `dockerImage`, which PartCAD uses when it can pull it and passes
# over when it cannot, and the scripts then fetch `solidcraft-cli` themselves
# (see `solidcraft_tool.py`). Nothing of this package is baked in: PartCAD
# mounts the package at run time, so an update of the package is never served
# stale by an old image.
#
# Build one per architecture, tagged with the suffix PartCAD looks for first,
# and keep SOLIDCRAFT_VERSION in step with `solidcraft_tool.py`:
#
#   docker build --build-arg ARCH=amd64 --build-arg SOLIDCRAFT_ARCH=x86_64 \
#     --build-arg SOLIDCRAFT_SHA256=b6dd545496a792897b87ba5679292db987853088d7cf13ccee64d94f0707f42b \
#     -t ghcr.io/partcad/partcad-plugin-solidcraft:0.16.1-amd64 .
#   docker build --build-arg ARCH=arm64 --build-arg SOLIDCRAFT_ARCH=aarch64 \
#     --build-arg SOLIDCRAFT_SHA256=639fea1b84b2b6e95b78203a044090450a539b3b341201eb2720d59329a71934 \
#     -t ghcr.io/partcad/partcad-plugin-solidcraft:0.16.1-arm64 .

ARG PARTCAD_VERSION=0.8.215
ARG PYTHON_VERSION=3.11
ARG ARCH=amd64
FROM ghcr.io/partcad/partcad-container-python:${PARTCAD_VERSION}-py${PYTHON_VERSION}-${ARCH}

ARG SOLIDCRAFT_VERSION=0.16.1
ARG SOLIDCRAFT_ARCH=x86_64
ARG SOLIDCRAFT_SHA256=b6dd545496a792897b87ba5679292db987853088d7cf13ccee64d94f0707f42b

LABEL partcad.image="1"
LABEL partcad.plugin="solidcraft"
LABEL org.opencontainers.image.description="PartCAD's Python sandbox with SolidCraft ${SOLIDCRAFT_VERSION}"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# What the application opens at run time rather than links: a display (X11 or
# Wayland), a renderer (Vulkan, with Mesa's software one for a container that
# has no GPU) and D-Bus for its file dialogs. The command line tool needs none
# of it.
# hadolint ignore=DL3008
RUN apt-get update \
  && apt-get install --yes --no-install-recommends \
    curl \
    libdbus-1-3 \
    libegl1 \
    libvulkan1 \
    libwayland-client0 \
    libwayland-egl1 \
    libx11-xcb1 \
    libxcb1 \
    libxcursor1 \
    libxi6 \
    libxkbcommon-x11-0 \
    libxkbcommon0 \
    libxrandr2 \
    mesa-vulkan-drivers \
  && rm -rf /var/lib/apt/lists/*

RUN curl --fail --silent --show-error --location --output /tmp/solidcraft.tar.gz \
    "https://github.com/bherbruck/solidcraft/releases/download/v${SOLIDCRAFT_VERSION}/solidcraft-${SOLIDCRAFT_VERSION}-linux-${SOLIDCRAFT_ARCH}.tar.gz" \
  && echo "${SOLIDCRAFT_SHA256}  /tmp/solidcraft.tar.gz" | sha256sum --check - \
  && mkdir -p /opt/solidcraft \
  && tar -xzf /tmp/solidcraft.tar.gz -C /opt/solidcraft --strip-components=1 \
  && rm /tmp/solidcraft.tar.gz \
  && ln -s /opt/solidcraft/bin/solidcraft /opt/solidcraft/bin/solidcraft-cli /usr/local/bin/ \
  && solidcraft-cli --version

USER pc
