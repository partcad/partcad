#!/usr/bin/env bash
#
# Runs INSIDE the dev container, on every start.
#
# The host's Docker daemon arrives as one of two bind mounts: the standard
# /var/run/docker.sock, which is the only path Docker Desktop understands on
# macOS and Windows, and whatever host-sockets-init.sh resolved for a Linux
# host that keeps its daemon elsewhere. Either may be an empty directory rather
# than a socket -- that is what Docker leaves when the source does not exist.
# This picks whichever is real, puts it where every Docker client looks for it,
# /var/run/docker.sock, and makes it reachable by the container user, so that
# `docker` and PartCAD's Docker sandboxes (the KiCad one, for one) can start
# containers on the host.
#
# What it does not do is chown the mounted socket. That inode belongs to the
# host: changing its owner here changes it there too, taking Docker away from
# everyone else on the host who reaches it through the `docker` group, until
# the daemon restarts and puts it back.

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -o pipefail: Exit on pipe failures
set -euo pipefail

socket=/var/run/docker.sock

host_socket=""
for candidate in /var/run/docker-host.sock /var/run/docker-host-alt.sock; do
  if [[ -S "${candidate}" ]]; then
    host_socket="${candidate}"
    break
  fi
done

# Neither is a socket: this machine has no Docker daemon to expose. Nothing to
# do, and nothing worth complaining about -- Docker clients in here will report
# that they cannot connect, if anything ever asks.
[[ -n "${host_socket}" ]] || exit 0

if [[ -w "${host_socket}" ]]; then
  # Already ours to use. The well-known path only has to point at it.
  sudo ln -sfn "${host_socket}" "${socket}"
  exit 0
fi

if command -v socat >/dev/null 2>&1; then
  # Proxy it instead of touching its permissions: the listening socket is ours
  # to own, and the host's stays exactly as the host left it.
  #
  # "-t 86400": how long socat keeps a connection after one direction of it
  # has ended. The default is half a second, and that is fatal to "docker exec
  # -i": the client closes its stdin as soon as it has written the request --
  # at once, when there is none -- and half a second later socat dropped the
  # whole connection, output stream included. The client then reported exit 0
  # while the command went on running in the container: PartCAD's Docker
  # sandbox was told "-m venv" had succeeded while pip was still being
  # installed, and failed every install after it ("No module named pip"). Only
  # where this proxy is in use, which is wherever the host's socket is not ours
  # to write -- GitHub's runners, and not a typical workstation -- and so for a
  # long time only in CI (#727). Docker ends the stream when the command ends,
  # so a long timeout costs nothing; it is a bound on a connection whose other
  # side has gone, not a wait.
  sudo pkill -f "UNIX-LISTEN:${socket}" || true
  sudo rm -f "${socket}"
  sudo nohup socat -t 86400 \
    "UNIX-LISTEN:${socket},fork,mode=660,user=$(id -u),group=$(id -g)" \
    "UNIX-CONNECT:${host_socket}" </dev/null >/dev/null 2>&1 &
  disown

  # socat needs a moment to bind before anything can connect.
  for _ in $(seq 1 50); do
    if [[ -S "${socket}" ]]; then
      exit 0
    fi
    sleep 0.1
  done
  echo "docker-socket-start.sh: socat did not create ${socket}" >&2
  exit 0
fi

# No socat in this image: fall back to handing the container user the socket's
# group. Supplementary groups are resolved when a session starts, so the shells
# opened after this point are the ones that get it.
group_id="$(stat -c %g "${host_socket}")"
if [[ "${group_id}" != "0" ]]; then
  group_name="$(getent group "${group_id}" | cut -d: -f1)"
  if [[ -z "${group_name}" ]]; then
    group_name=docker-host
    sudo groupadd -g "${group_id}" "${group_name}"
  fi
  sudo usermod -aG "${group_name}" "$(id -un)"
fi
sudo ln -sfn "${host_socket}" "${socket}"
