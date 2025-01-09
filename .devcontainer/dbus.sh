#!/usr/bin/env bash

set -euxo pipefail

# TODO: Avoid hardcoding
USER_NAME=node  # $(id -un)
USER_GROUP=node # $(id -gn)

mkdir -pv "$XDG_RUNTIME_DIR"
chmod -c 700 "$XDG_RUNTIME_DIR"
# chown -c "$(id -un):$(id -gn)" "$XDG_RUNTIME_DIR"
chown -c "${USER_NAME}:${USER_GROUP}" "$XDG_RUNTIME_DIR"
