FROM mcr.microsoft.com/devcontainers/typescript-node:1-22-bookworm

RUN set -eux; \
  apt-get update; \
  apt-get install --yes --no-install-recommends \
  gosu=1.14-1+b10; \
  rm -rf /var/lib/apt/lists/*
RUN \
  --mount=type=bind,source=./conda.sh,target=/tmp/conda.sh \
  gosu node /tmp/conda.sh
