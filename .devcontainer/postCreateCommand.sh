#!/usr/bin/env bash

set -euxo pipefail

git config --global --add safe.directory /workspaces/partcad

cd /workspaces/partcad
pre-commit install
poetry self add poetry-plugin-export
