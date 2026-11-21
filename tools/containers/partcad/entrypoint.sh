#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The entrypoint of the PartCAD image: decides what to run, and as whom.
#
# What to run. `docker run <image> render my_part` is `pc render my_part`: a
# first argument that is one of `pc`'s commands, or an option, or nothing at all,
# is handed to `pc`. Anything else is run as it is -- `sh`, `bash`, `micromamba`,
# `partcad-json-rpc` -- which is what a CI system that starts a shell in the
# image expects. The list of commands is the installed wheel's own, written at
# build time, so `install` means `pc install` and not coreutils' `install`.
#
# As whom. PartCAD writes into the directory it works in, and the files it
# leaves there have to belong to whoever owns that directory on the host, not to
# root and not to whatever uid this image happened to be built with. So a
# PartCAD command started as root runs as the owner of the working directory --
# 'PC_UID' and 'PC_GID' say otherwise -- and, when the host's Docker socket is
# mounted, with that socket's group added, so that the sandboxes and KiCad can
# start containers. That is the whole reason this starts as root: an MCP client
# starts the image from a JSON file, where `--user "$(id -u)"` and
# `--group-add "$(stat -c %g /var/run/docker.sock)"` cannot be written.
#
# It does not change users for anything else, and does nothing at all when the
# image is started with `--user`. A working directory owned by root (the user is
# root, or Docker created the directory because nothing was mounted there) keeps
# root, which is who owns what PartCAD writes there anyway.
#
# Nothing here writes to standard output: `pc mcp` speaks the protocol there.

set -eu

COMMANDS=/usr/local/share/partcad/commands

if [ "$#" -eq 0 ]; then
  set -- pc --help
else
  case "$1" in
  -*) set -- pc "$@" ;;
  *)
    if grep -qx -- "$1" "${COMMANDS}" 2>/dev/null; then
      set -- pc "$@"
    fi
    ;;
  esac
fi

case "$1" in
pc | partcad | partcad-json-rpc | partcad-service-remote-docker) ;;
*) exec "$@" ;;
esac

if [ "$(id -u)" != "0" ]; then
  exec "$@"
fi

uid="${PC_UID:-$(stat -c %u .)}"
gid="${PC_GID:-$(stat -c %g .)}"
if [ "${uid}" = "0" ]; then
  exec "$@"
fi

groups="${gid}"
socket="${DOCKER_HOST:-unix:///var/run/docker.sock}"
socket="${socket#unix://}"
if [ -S "${socket}" ]; then
  socket_gid="$(stat -c %g "${socket}")"
  if [ "${socket_gid}" != "${gid}" ]; then
    groups="${groups},${socket_gid}"
  fi
  # Asked as that user rather than worked out from the mode bits: ACLs, and a
  # rootless daemon's socket owned by one particular user, answer differently.
  if ! setpriv --reuid="${uid}" --regid="${gid}" --groups="${groups}" -- \
    test -r "${socket}" -a -w "${socket}"; then
    echo "partcad: uid ${uid} cannot use the Docker socket ${socket}, so PartCAD will not start containers." \
      "Run with PC_UID=0 to use it as root, or make it usable by that uid." >&2
  fi
fi

# Without a passwd entry for an arbitrary uid, these are what anything asking
# "who am I" reads first (Python's getpass among them).
USER="${USER:-pc}"
LOGNAME="${LOGNAME:-pc}"
export USER LOGNAME

exec setpriv --reuid="${uid}" --regid="${gid}" --groups="${groups}" -- "$@"
