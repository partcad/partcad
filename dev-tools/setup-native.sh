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
#   1. Installs git-lfs and points this checkout at it. Without it the checkout
#      does not degrade, it silently writes the wrong thing -- see the step
#      itself for what that costs and which four files paid it.
#   2. `poetry install`, which is the same command the container runs.
#   3. Installs OpenSCAD, which `poetry install` cannot: it is not a Python
#      package. PartCAD treats it as part of the toolchain rather than as an
#      optional extra -- the standalone bundles carry one, `pc healthcheck`
#      asks after it, and a `.scad` part *fails* without it rather than
#      degrading -- so an environment without one is not set up, and this stops
#      rather than leaving that to be discovered by a test run.
#   4. Checks for a file two wheels both installed. `poetry install` installs in
#      parallel, so any two distributions shipping one path can have both
#      workers write it at once, and what lands is a blend of the two: an
#      `import` of a native module like that takes SIGSEGV inside the dynamic
#      loader, with no Python traceback anywhere. `check_installed_files.py`
#      explains it at length.
#   5. Says what else is missing and what it costs, rather than letting a suite
#      fail thirty minutes later for a reason that has nothing to do with the
#      change under test.
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

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  fi
fi

APT_UPDATED=""
apt_install() {
  # `update` first, and not as an optimisation: an image whose package lists
  # have gone stale resolves point releases that the archive has already
  # superseded, and the fetch 404s on them rather than falling back. Once per
  # run, though -- this has two callers now, and the second update is a minute
  # spent re-reading what the first one just read.
  if [ -z "$APT_UPDATED" ]; then
    $SUDO apt-get update
    APT_UPDATED="yes"
  fi
  $SUDO apt-get install -y --no-install-recommends "$@"
}

# Installed and *required*, for the reason OpenSCAD is below: without it this
# checkout does not degrade, it silently commits the wrong bytes.
# `.gitattributes` routes every `.png`, `.jpg` and `.svg` through the `lfs`
# filter, and git resolves a `filter=` attribute naming a driver that no config defines by
# storing the file verbatim -- no warning, no error, nothing in the commit to
# look at afterwards. So a commit made here without git-lfs puts raw image
# bytes at a path declared to hold a pointer, and the next person who *has*
# git-lfs configured gets "Encountered N files that should have been pointers,
# but weren't" and N files that `git checkout` cannot clean, because git keeps
# cleaning their real bytes into a pointer and comparing it against a raw blob.
# That is exactly how the four images under `examples/feature_render/images/`
# came to be stored the wrong way (since repaired), and this script is the kind
# of environment it happened in: no dev container, so nothing supplying git-lfs.
# Repairing such a file is `git add --renormalize <path>` and a commit.
echo "==> git-lfs"
if git lfs version >/dev/null 2>&1; then
  echo "    already installed: $(git lfs version 2>&1 | head -n 1)"
elif command -v apt-get >/dev/null 2>&1; then
  apt_install git-lfs
elif command -v brew >/dev/null 2>&1; then
  HOMEBREW_NO_AUTO_UPDATE=1 brew install git-lfs
else
  echo "    no apt-get and no brew here, so git-lfs has to be installed by hand:" >&2
  echo "    https://git-lfs.com/ -- then re-run this script." >&2
  exit 1
fi

# `--local` rather than the usual global install: this script prepares one
# checkout, and `.git/config` is the file that belongs to it -- which is also
# the one that survives a dev container being recreated, being in the
# bind-mounted workspace. It writes the filter driver and the hooks, and
# re-running it is a no-op.
git lfs install --local

if [ -z "$(git config --get filter.lfs.clean || true)" ]; then
  # An install can half-succeed, so ask the question that matters rather than
  # trusting the exit code above: it is the `clean` filter, and nothing else,
  # that stands between a commit here and a raw blob at a pointer's path.
  echo "    git-lfs is installed but 'filter.lfs.clean' is unset, so commits from" >&2
  echo "    this checkout would still store raw bytes where a pointer belongs." >&2
  exit 1
fi

# Best-effort, unlike everything above it: the objects are rendered output that
# no build here reads back, and a machine with no network or no LFS quota left
# is still a machine that can run the tests. Left unfetched they are pointer
# text files on disk, which is what every CI checkout in this repository has
# too -- none of them passes `lfs: true`.
if ! git lfs pull; then
  echo "    could not fetch the LFS objects; the files LFS tracks are pointer" >&2
  echo "    files on disk until 'git lfs pull' succeeds. Nothing here reads them." >&2
fi

echo "==> poetry install"
poetry install

echo "==> OpenSCAD"
if command -v openscad >/dev/null 2>&1; then
  echo "    already installed: $(openscad --version 2>&1 | head -n 1)"
elif command -v apt-get >/dev/null 2>&1; then
  apt_install openscad
elif command -v brew >/dev/null 2>&1; then
  # The snapshot cask, and not `openscad`: Homebrew disabled the latter in
  # September 2026 (the pinned 2021.01 release fails the macOS Gatekeeper
  # check), and 2021.01 ships an x86_64-only .dmg anyway, so on Apple silicon
  # it would need Rosetta. `.github/actions/setup-test/action.yml` says all of
  # this, and also what to do when the cask puts no binary on PATH.
  HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask openscad@snapshot
else
  echo "    no apt-get and no brew here, so OpenSCAD has to be installed by hand:" >&2
  echo "    https://openscad.org/downloads.html -- then re-run this script." >&2
  exit 1
fi

if ! command -v openscad >/dev/null 2>&1; then
  # A cask need not put a binary on PATH and an install can half-succeed, so
  # ask the question that matters rather than trusting the exit code above.
  echo "    OpenSCAD was installed but is not on PATH. Put it there and re-run;" >&2
  echo "    '.github/actions/setup-test/action.yml' has what CI does on macOS." >&2
  exit 1
fi

# Must run under the environment's own interpreter: it reads that
# environment's `site-packages`, and repairs it with that environment's pip.
echo "==> checking for files two wheels wrote at once"
poetry run python dev-tools/check_installed_files.py --fix

echo "==> what else this machine has"

# Reported, never installed. Unlike OpenSCAD, neither of these is part of the
# toolchain: without them some tests decline to run, and none of them fail.
report() {
  # $1: the thing, $2: how to see whether it is here, $3: what its absence costs
  if eval "$2" >/dev/null 2>&1; then
    echo "    yes  $1"
  else
    echo "    NO   $1 -- $3"
  fi
}

report "a Docker daemon" "docker info" \
  "the KiCad example is skipped without one, and the 'docker' Python sandbox falls back"
report "conda" "command -v conda || command -v mamba" \
  "the Python sandbox falls back to 'venv', which cannot provision an interpreter version but is otherwise fine"

echo "    ---"
echo "    Python sandbox in use: $(poetry run python -c 'from partcad_utils.user_config import UserConfig; print(UserConfig().python_sandbox)')"

cat <<'NOTE'

Done. Run pytest with:

    poetry run pytest tests cad/freecad -x -p no:error-for-skips -p no:warnings --dist no

The first run that renders a scripted part is slow whatever the sandbox: it
builds the CAD environment under ~/.partcad/sandbox and pip-installs the stack
into it, which is minutes of work and several GB of disk, once.

Do NOT run the whole `behave` suite here. Every scenario gets a throwaway $HOME,
so each one that renders anything builds a CAD sandbox of its own from scratch
and throws it away -- ~2.7 GB and minutes of pip, times 166 scenarios, and in
parallel that is several of them on disk at once. Run the one feature a change
touches instead:

    poetry run behave features/<name>.feature

`pre-commit` is not installed by any of this -- it comes from the dev container's
image, and the hooks it runs (pytest, behave, shellcheck, hadolint) are the gates
CI re-runs anyway. Committing here does not run them, so run what they run.
NOTE

exit 0
