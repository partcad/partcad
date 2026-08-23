#!/usr/bin/env bash
#
# Runs on the HOST, before the dev container is created or started.
#
# Covers the hosts whose Docker daemon is not at /var/run/docker.sock: rootless
# Docker, a unix:// DOCKER_HOST, Colima. devcontainer.json binds that standard
# path directly -- it is the only one Docker Desktop understands on macOS and
# Windows -- and binds the link this script writes as a second candidate, which
# the container side falls back to. Docker resolves the link host-side, so the
# container receives the socket itself.
#
# Nothing here may fail: a failing initializeCommand aborts `devcontainer up`,
# and a host with no daemon at all is a supported way to open this workspace.
# So every step that can fail gives up quietly instead, leaving no link behind
# and the container with nothing to fall back to.

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -o pipefail: Exit on pipe failures
set -euo pipefail

# Kept in step with the "-v" source in devcontainer.json, which spells the same
# path with ${localEnv:USER}. Per user, because /tmp is shared: a fixed name is
# a link somebody else on this host could have planted first, and it would be
# bind-mounted into a privileged container as if it were the Docker socket.
link_dir="/tmp/partcad-devcontainer-${USER:-}"
link="${link_dir}/docker.sock"

mkdir -p "${link_dir}" 2>/dev/null || exit 0
# Somebody else's directory of the same name: leave it alone, and leave the
# container to the standard path.
[[ -O "${link_dir}" ]] || exit 0
chmod 700 "${link_dir}" 2>/dev/null || exit 0
rm -f "${link}" 2>/dev/null || exit 0

candidates=()
# An explicit DOCKER_HOST wins, but only a local socket can be bind-mounted:
# a tcp:// or ssh:// daemon is somebody else's machine.
if [[ "${DOCKER_HOST:-}" == unix://* ]]; then
  candidates+=("${DOCKER_HOST#unix://}")
fi
# Rootless Docker.
if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
  candidates+=("${XDG_RUNTIME_DIR}/docker.sock")
fi
if [[ -n "${HOME:-}" ]]; then
  # Docker Desktop with the default socket turned off, and Colima.
  candidates+=("${HOME}/.docker/run/docker.sock")
  candidates+=("${HOME}/.colima/default/docker.sock")
fi
# Last, the standard path -- already bound directly, so reaching it here only
# means the fallback duplicates the primary, which costs nothing.
candidates+=("/var/run/docker.sock")

for socket in "${candidates[@]}"; do
  if [[ -S "${socket}" ]]; then
    ln -s "${socket}" "${link}" 2>/dev/null || true
    exit 0
  fi
done

# No daemon on this machine, so no link. devcontainer.json binds this path with
# "-v", which creates an empty directory rather than failing the way a "mounts"
# entry would, and the container side reads that as "no Docker".
exit 0
