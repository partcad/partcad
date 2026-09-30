#!/usr/bin/env bash
#
# Runs on the HOST, before the dev container is created or started.
#
# Resolves the host sockets this workspace wants to reach through, into fixed
# paths devcontainer.json can bind. Two of them:
#
#   docker.sock     -- for the hosts whose Docker daemon is not at
#                      /var/run/docker.sock: rootless Docker, a unix://
#                      DOCKER_HOST, Colima. devcontainer.json binds the standard
#                      path directly -- it is the only one Docker Desktop
#                      understands on macOS and Windows -- and binds the link
#                      this script writes as a second candidate, which the
#                      container side falls back to.
#
#   ssh-agent.sock  -- the running SSH agent, so that a git clone over SSH from
#                      inside the container authenticates with the host's keys
#                      and the private half never enters the container. The
#                      VS Code Dev Containers extension forwards the agent by
#                      itself; `devcontainer up` does not, which is why an agent
#                      opened this way -- an agent in CI, or one in a terminal
#                      following AGENTS.md -- had no agent at all.
#
# Docker resolves each link host-side, so the container receives the socket
# itself.
#
# Nothing here may fail: a failing initializeCommand aborts `devcontainer up`,
# and a host with no daemon and no agent at all is a supported way to open this
# workspace. So every step that can fail gives up quietly instead, leaving no
# link behind and the container with nothing to fall back to.

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -o pipefail: Exit on pipe failures
set -euo pipefail

# Kept in step with the "-v" sources in devcontainer.json, which spell the same
# path with ${localEnv:USER}. Per user, because /tmp is shared: a fixed name is
# a link somebody else on this host could have planted first, and it would be
# bind-mounted into a privileged container as if it were the Docker socket.
link_dir="/tmp/partcad-devcontainer-${USER:-}"

mkdir -p "${link_dir}" 2>/dev/null || exit 0
# Somebody else's directory of the same name: leave it alone, and leave the
# container to the standard path.
[[ -O "${link_dir}" ]] || exit 0
chmod 700 "${link_dir}" 2>/dev/null || exit 0

# Points "${link_dir}/$1" at the first of the remaining arguments that is a
# socket, and at nothing at all if none of them is.
link_first_socket() {
  local link="${link_dir}/$1"
  shift

  rm -f "${link}" 2>/dev/null || return 0

  local candidate
  for candidate in "$@"; do
    if [[ -S "${candidate}" ]]; then
      ln -s "${candidate}" "${link}" 2>/dev/null || true
      return 0
    fi
  done

  # Nothing of this kind on this machine, so no link. devcontainer.json binds
  # this path with "-v", which creates an empty directory rather than failing
  # the way a "mounts" entry would, and the container side reads that as "not
  # here".
  return 0
}

docker_candidates=()
# An explicit DOCKER_HOST wins, but only a local socket can be bind-mounted:
# a tcp:// or ssh:// daemon is somebody else's machine.
if [[ "${DOCKER_HOST:-}" == unix://* ]]; then
  docker_candidates+=("${DOCKER_HOST#unix://}")
fi
# Rootless Docker.
if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
  docker_candidates+=("${XDG_RUNTIME_DIR}/docker.sock")
fi
if [[ -n "${HOME:-}" ]]; then
  # Docker Desktop with the default socket turned off, and Colima.
  docker_candidates+=("${HOME}/.docker/run/docker.sock")
  docker_candidates+=("${HOME}/.colima/default/docker.sock")
fi
# Last, the standard path -- already bound directly, so reaching it here only
# means the fallback duplicates the primary, which costs nothing.
docker_candidates+=("/var/run/docker.sock")

link_first_socket docker.sock "${docker_candidates[@]}"

# The agent has one candidate and no conventional path: SSH_AUTH_SOCK is where
# it says it is, and an unset one means no agent is running for this session.
ssh_candidates=()
if [[ -n "${SSH_AUTH_SOCK:-}" ]]; then
  ssh_candidates+=("${SSH_AUTH_SOCK}")
fi

link_first_socket ssh-agent.sock "${ssh_candidates[@]+"${ssh_candidates[@]}"}"

exit 0
