#!/usr/bin/env bash
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Prepare a checkout to build and test PartCAD *without* the dev container.
#
# The dev container is the supported environment and this does not replace it:
# it has the pinned toolchain, the `pre-commit` hooks, a Docker socket and a
# `conda`, and none of that is reproduced here. What this is for is the machine
# that cannot start it -- a cloud agent session with no Docker daemon, a bare CI
# runner -- where the alternative is not "use the container" but "give up".
#
# What it does, and why each step is not just `poetry install`:
#
#   1. `poetry install`, which is the same command the container runs.
#   2. Repairs the file two wheels overwrite each other on. `poetry install`
#      installs in parallel, `cadquery-ocp` and `cadquery-ocp-novtk` both write
#      `OCP/OCP.cpython-*.so`, and a machine slow enough to lose that race ends
#      up with a blend of the two: `import OCP` then takes SIGSEGV inside the
#      dynamic loader, and since a test module imports build123d at import time
#      that is the whole pytest *collection* dying with no message.
#      `check_installed_files.py` explains this at length.
#   3. Says what is missing and what it costs, rather than letting a suite fail
#      thirty minutes later for a reason that has nothing to do with the change
#      under test.
#
# Usage, from the repository root:
#
#     ./dev-tools/setup-native.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v poetry >/dev/null 2>&1; then
  echo "poetry is not on PATH. Install it first: https://python-poetry.org/docs/#installation" >&2
  exit 1
fi

echo "==> poetry install"
poetry install

# Must run under the environment's own interpreter: it reads that
# environment's `site-packages`, and repairs it with that environment's pip.
echo "==> checking for files two wheels wrote at once"
poetry run python dev-tools/check_installed_files.py --fix

echo "==> what this machine has"

# Reported, never installed. Which of these is worth having depends on what is
# being changed, and how to get one is the platform's business, not this
# script's -- `apt-get install openscad` on a Debian, a cask on a Mac.
report() {
  # $1: the thing, $2: how to see whether it is here, $3: what its absence costs
  if eval "$2" >/dev/null 2>&1; then
    echo "    yes  $1"
  else
    echo "    NO   $1 -- $3"
  fi
}

report "OpenSCAD" "command -v openscad" \
  "every '.scad' part fails rather than skips (tests/partcad/unit/test_convert_part.py and friends)"
report "a Docker daemon" "docker info" \
  "the KiCad example is skipped; nothing else needs it"
report "conda" "command -v conda || command -v mamba" \
  "the Python sandbox falls back to 'venv', which cannot provision an interpreter version but is otherwise fine"

echo "    ---"
echo "    Python sandbox in use: $(poetry run python -c 'from partcad_utils.user_config import UserConfig; print(UserConfig().python_sandbox)')"

cat <<'NOTE'

Done. Run the suites with:

    poetry run pytest tests cad/freecad -x -p no:error-for-skips -p no:warnings --dist no
    poetry run behave

The first run that renders a scripted part is slow whatever the sandbox: it
builds the CAD environment under ~/.partcad/sandbox and pip-installs the stack
into it, which is minutes of work and several GB of disk, once.

`pre-commit` is not installed by any of this -- it comes from the dev container's
image, and the hooks it runs (pytest, behave, shellcheck, hadolint) are the gates
CI re-runs anyway. Committing here does not run them, so run what they run.
NOTE

exit 0
