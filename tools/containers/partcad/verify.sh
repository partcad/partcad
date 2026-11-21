#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# What the PartCAD image promises, checked while it is built: a build that
# breaks any of it fails here rather than in somebody's MCP client. Kept in the
# image, like the base's `verify.py`, so that it can be run against a published
# tag as well:
#
#     docker run --rm ghcr.io/partcad/partcad sh /usr/local/share/partcad/verify.sh
#
# What it cannot check -- rendering, the daemon, `pc mcp` over `docker run -i`,
# the host's Docker socket -- is `dev-tools/ci/test-partcad-image.sh`, which
# runs the image the way a person does.

set -eu

say() { echo "verify: $*"; }

# A throwaway home, so that nothing asked here is left in the image.
scratch="$(mktemp -d)"
trap 'rm -rf "${scratch}"' EXIT
export HOME="${scratch}" PC_INTERNAL_STATE_DIR="${scratch}/.partcad"

say "PartCAD $(python3 -c 'import partcad_cli; print(partcad_cli.__version__)')"
for command in pc partcad partcad-json-rpc partcad-service-remote-docker micromamba openscad git git-lfs tini; do
  command -v "${command}" >/dev/null || {
    echo "verify: '${command}' is not on PATH" >&2
    exit 1
  }
done
say "$(micromamba --version | head -n 1) / $(openscad --version 2>&1 | head -n 1) / $(git lfs version)"

# The conda PartCAD finds is this image's micromamba, and so the sandbox it
# chooses is conda's: the one that provisions whatever interpreter a package
# asks for. `venv` here would mean every package rendering on this image's 3.11.
python3 - <<'PY'
import sys

from partcad_utils import conda

found = conda.find_executable()
if found != "/usr/local/bin/micromamba":
    sys.exit("verify: PartCAD finds conda at %r, not this image's micromamba" % (found,))

from partcad_utils.user_config import user_config

if user_config.python_sandbox != "conda":
    sys.exit("verify: the default Python sandbox is %r, not conda" % (user_config.python_sandbox,))
if not user_config.use_docker_remote:
    sys.exit("verify: useDockerRemote is off, and a mounted socket would bind paths the host cannot see")
print("verify: conda found at %s; pythonSandbox=conda; useDockerRemote=true" % found)
PY

# `pc upgrade` refuses: this installation is replaced by pulling an image.
python3 - <<'PY'
import sys

from partcad_client import selfupdate

status = selfupdate.check()
if status["kind"] != selfupdate.KIND_IMAGE or not status["reason"]:
    sys.exit("verify: pc upgrade would not refuse inside the image: %r" % (status,))
print("verify: pc upgrade refuses, as it should")
PY

say "ok"
