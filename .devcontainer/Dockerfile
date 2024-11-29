FROM ghcr.io/hadolint/hadolint:v2.12.1-beta-debian as hadolint

FROM mcr.microsoft.com/devcontainers/python:3.10-bookworm

# https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#labelling-container-images
LABEL org.opencontainers.image.source "https://github.com/partcad/partcad/"
LABEL org.opencontainers.image.description "Dev Container for PartCAD"
LABEL org.opencontainers.image.licenses "Apache 2.0"

COPY --from=hadolint /bin/hadolint /usr/local/bin/hadolint

RUN \
  --mount=type=bind,source=./apt.txt,target=/tmp/apt.txt \
  --mount=type=bind,source=./apt.sh,target=/tmp/apt.sh \
  /tmp/apt.sh
