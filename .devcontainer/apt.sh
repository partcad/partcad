#!/usr/bin/env bash

set -exuo pipefail

apt-get update

# shellcheck disable=SC2046
apt-get install --yes --no-install-recommends $(cat /tmp/apt.txt)

rm -rf /var/lib/apt/lists/*
