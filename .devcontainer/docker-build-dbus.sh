#!/usr/bin/env bash

set -euxo pipefail

# TODO(clairbee): rename to partcad
USER_NAME=vscode
USER_GROUP=vscode

mkdir -pv "$XDG_RUNTIME_DIR"
chmod -c 700 "$XDG_RUNTIME_DIR"
chown -c "${USER_NAME}:${USER_GROUP}" "$XDG_RUNTIME_DIR"
