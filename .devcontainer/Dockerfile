FROM mcr.microsoft.com/devcontainers/python:3.10-bookworm
# Skipping wheel cadquery_ocp-7.7.2-cp310-cp310-manylinux_2_35_x86_64.whl as this is not supported by the current environment
# FROM mcr.microsoft.com/devcontainers/python:3.10-bullseye

RUN set -eux; \
  apt-get update; \
  apt-get install --yes --no-install-recommends \
  shellcheck \
  bash-completion \
  cmake \
  libcairo2-dev \
  pkg-config \
  python3-dev \
  ffmpeg \
  libsm6 \
  libxext6 \
  openscad \
  pypy3 \
  pypy3-dev \
  graphviz \
  time; \
  rm -rf /var/lib/apt/lists/*
