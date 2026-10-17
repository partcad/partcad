#!/usr/bin/env bash
#
# Start an X server, wait until it accepts connections, and print the display it
# serves (":99", say). The server goes on running after this script returns.
#
# Waited for, not assumed: "Xvfb :98 & export DISPLAY=:98" and then starting the
# editor straight away is a race the editor can win, and on a GitHub runner it
# does - "Missing X server or $DISPLAY" a fifth of a second in, and the smoke
# test fails over nothing the build did. '-displayfd' is the X server's own
# "ready" signal: it writes the display number to that descriptor once it is
# listening, which is the same moment 'xvfb-run' waits for. It also has the
# server pick a free display rather than be told one, so two of them in one job,
# or a stale lock left on the runner, cannot collide.
#
# Usage: start-xvfb.sh [<screen>]   (default 1280x1024x24)
#
# What the server prints goes to "$RUNNER_TEMP/xvfb.log" and is shown when it
# fails to start; nothing it writes reaches this script's standard output, so
# "display=$(start-xvfb.sh)" returns instead of waiting on the server.

set -euo pipefail

screen="${1:-1280x1024x24}"
dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
number="$(mktemp "${dir}/xvfb-display.XXXXXX")"
log="${dir}/xvfb.log"

Xvfb -displayfd 3 -screen 0 "${screen}" -nolisten tcp 3>"${number}" </dev/null >"${log}" 2>&1 &
server=$!

fail() {
  echo "::error::$1" >&2
  cat "${log}" >&2 || true
  kill "${server}" 2>/dev/null || true
  exit 1
}

# Thirty seconds. The number is written with its newline in one go; waiting for
# the newline rather than for any byte is what makes a half-read impossible.
for _ in $(seq 300); do
  if [ "$(wc -l <"${number}")" -ge 1 ]; then
    echo ":$(head -n 1 "${number}")"
    exit 0
  fi
  kill -0 "${server}" 2>/dev/null || fail "Xvfb exited before it served a display"
  sleep 0.1
done
fail "Xvfb did not serve a display within 30 seconds"
