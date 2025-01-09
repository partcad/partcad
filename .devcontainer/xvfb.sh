#!/usr/bin/env bash

set -euxo pipefail

sudo apt-get update
sudo apt-get install --yes \
  libnss3 \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libcups2 \
  libdrm2 \
  libgtk-3-0 \
  libgbm1 \
  libasound2

sudo apt-get install --yes \
  xvfb

# TODO: Those might be not needed
sudo apt-get install --yes \
  libxext6 \
  libx11-xcb1 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-randr0 \
  libxcb-render-util0 \
  libxcb-xinerama0 \
  libxcb-xkb1
