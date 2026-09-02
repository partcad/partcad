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
PYTHONFAULTHANDLER=1 timeout --signal=ABRT --kill-after=60 "${TIMEOUT}" "$@" && status=0 || status=$?

# Which statuses mean "this wrapper stopped it", and which mean "it stopped on
# its own". Getting this wrong is worse here than anywhere else: the whole point
# of the file is to say accurately why a command ended.
#
#   124  'timeout' fired. It reports this whatever signal it sent, so it is the
#        normal outcome of the SIGABRT above -- not 134, which is what the shell
#        would report for a process killed by SIGABRT if 'timeout' were not in
#        the way. Verified against GNU coreutils 9.x rather than assumed.
#   137  'timeout' fired, the command ignored SIGABRT, and '--kill-after' had to
#        SIGKILL it a minute later. Also this wrapper's doing.
#   134  the command aborted *by itself*, with no timeout involved -- a C
#        extension calling abort(), a glibc assertion, OpenCASCADE giving up.
#        Claiming a timeout here would send someone looking for a hang that
#        never happened, so it is passed through with everything else.
case "${status}" in
124 | 137)
  echo "::error::'$1' produced no result within ${TIMEOUT}s and was aborted." >&2
  echo "The traceback above, if there is one, is every thread's stack at that moment." >&2
  ;;
esac

exit "${status}"
