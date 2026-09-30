#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Run a PartCAD command in CI with a bound on how long it may hang, and make it
# say where it hung when it does.
#
#     dev-tools/ci/bounded.sh coverage run ... -m partcad_cli.click.command ...
#
# Why this exists. On 2026-09-01 the "Examples (PartCAD)" job on
# 'ubuntu-24.04-arm' stopped producing output two minutes into 'pc test' and
# said nothing for the next seventy-one, until the job's own 'timeout-minutes'
# killed it. A job killed that way is reported as *cancelled*, so the whole CI
# run came out "cancelled" rather than "failure" -- indistinguishable, on the
# runs page, from one somebody superseded with another push -- and the log ended
# mid-sentence with no indication of what the process was doing. Every
# version-bump run on 'devel' had been ending that way for days.
#
# Two things change here, and neither of them fixes the hang itself:
#
#  * The bound is per command rather than per job, and it is shorter, so the
#    step fails as a failure with time left to report instead of being cancelled
#    with none.
#
#  * The signal is SIGABRT rather than SIGTERM, and PYTHONFAULTHANDLER is set.
#    Python's fault handler answers SIGABRT by writing the stack of *every*
#    thread to stderr -- which, for a command run with '--threads-max 4', is the
#    difference between "it hung" and knowing which lock four workers are
#    waiting on. SIGTERM would have been handled by the interpreter and told us
#    nothing.
#
# Windows is deliberately left alone: signal delivery from MSYS 'timeout' to a
# native Python process does not reach the fault handler, so the wrapper would
# turn a hang into a kill with no traceback and cost the honest reporting of the
# exit code for nothing. Same when 'timeout' is not on PATH at all. In both
# cases the command runs exactly as it did before this file existed.
#
# PC_CI_HANG_TIMEOUT is the bound, in seconds. The default is 40 minutes: the
# whole of this step measures 24-32 minutes on Linux and about 55 on Windows,
# spread over three commands, so no healthy command comes near it.

set -eu

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <command> [argument ...]" >&2
  exit 2
fi

TIMEOUT="${PC_CI_HANG_TIMEOUT:-2400}"

case "$(uname -s 2>/dev/null || echo unknown)" in
MINGW* | MSYS* | CYGWIN* | Windows_NT)
  exec "$@"
  ;;
esac

if ! command -v timeout >/dev/null 2>&1; then
  exec "$@"
fi

# '--kill-after' is the backstop for a process that ignores SIGABRT or dies
# inside the fault handler: SIGKILL a minute later, so the step still ends.
started=$(date +%s)
PYTHONFAULTHANDLER=1 timeout --signal=ABRT --kill-after=60 "${TIMEOUT}" "$@" && status=0 || status=$?
elapsed=$(( $(date +%s) - started ))

# Whether *this wrapper* stopped the command, decided by the clock as well as by
# the exit status, because the status alone cannot carry that.
#
# 'timeout' answers 124 when it fires and 137 when '--kill-after' had to
# escalate to SIGKILL -- but it also passes a command's own status straight
# through, and those two values are not reserved. A render killed by the OOM
# killer exits 137 with no timeout involved, which on this workload is a real
# possibility rather than a hypothetical (see the '--threads-max 4' note in
# "test.yml"); a command that chooses to exit 124 is rarer but no less
# misleading. Either would otherwise be announced as "produced no result within
# 2400s" thirty seconds into a run.
#
# So the clock has to agree. It settles the other direction too: 134 here is a
# command that aborted by itself -- a C extension calling abort(), a glibc
# assertion, OpenCASCADE giving up -- and is passed through with everything else.
#
# One second of slack, because 'timeout' fires at the boundary and 'date'
# resolves to the second.
timed_out=""
if [ "${elapsed}" -ge $(( TIMEOUT - 1 )) ]; then
  case "${status}" in
  124 | 137) timed_out="yes" ;;
  esac
fi

if [ -n "${timed_out}" ]; then
  echo "::error::'$1' produced no result within ${TIMEOUT}s and was aborted." >&2
  echo "The traceback above, if there is one, is every thread's stack at that moment." >&2
elif [ "${status}" -ne 0 ]; then
  # Said plainly, so that a status this wrapper did *not* cause is not read as
  # one it did.
  echo "'$1' exited ${status} after ${elapsed}s; it was not stopped by this wrapper." >&2
fi

exit "${status}"
