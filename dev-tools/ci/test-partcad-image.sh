#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Run the PartCAD image the way a person does, and check each thing it promises.
#
#     PC_IMAGE=partcad:local dev-tools/ci/test-partcad-image.sh
#     PC_IMAGE=partcad:local PC_SOCKET=true dev-tools/ci/test-partcad-image.sh
#
# What the build checks already (`tools/containers/partcad/verify.sh`) is that
# the pieces are in it. This is everything that needs the image to *run*:
#
#   1. a command of `pc`'s is handed to `pc`, and `pc upgrade` refuses;
#   2. PartCAD writes into the workspace as the user who owns it;
#   3. `pc init` in the image has the agents start the image, not a `pc`;
#   4. a scripted part renders with no socket -- in a conda sandbox inside the
#      container, built from nothing into the volume;
#   5. `pc mcp` answers an MCP client over `docker run -i`, and its `render`
#      tool comes back with a picture;
#   6. with PC_SOCKET=true, the host's Docker: a scripted part renders in the
#      `docker` sandbox, and the KiCad example's board is built in KiCad's
#      container -- both started on the host's daemon from inside this one,
#      and reached in `upload` mode.
#
#   PC_IMAGE    The image to test. Default 'partcad:local', what
#               'build-partcad-image.sh' builds by default.
#   PC_SOCKET   'true' to run 6. It pulls KiCad's image, which is large.
#   PC_VERSION  The version 'pc version' has to report. Default: this tree's.
set -eu

here=$(unset CDPATH; cd -- "$(dirname -- "$0")/../.." && pwd)
PC_IMAGE="${PC_IMAGE:-partcad:local}"
PC_SOCKET="${PC_SOCKET:-false}"
PC_VERSION="${PC_VERSION:-$(sed -n 's/^current_version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "${here}/dev-tools/bumpversion.toml")}"

# A volume of its own, so that this neither reads nor clobbers a real one, and
# a directory of its own for the workspaces.
volume="partcad-image-test-$$"
volumes="${volume} ${volume}-socket"
work=$(mktemp -d)
cleanup() {
  # shellcheck disable=SC2086 # two names, split on purpose
  docker volume rm -f ${volumes} >/dev/null 2>&1 || true
  rm -rf "${work}" 2>/dev/null || true
}
trap cleanup EXIT

me="$(id -u):$(id -g)"
step() { echo; echo "==> $*"; }
fail() { echo "FAILED: $*" >&2; exit 1; }

# `docker run` of the image on a workspace, as the documentation spells it --
# plus the two variables a CI run that built images of its own points PartCAD
# at them with (see 'partcad_utils.container_image'). `-e NAME` passes one only
# where it is set, so outside such a run the image's PartCAD sees neither.
run_in() {
  dir="$1"
  shift
  docker run --rm -v "${volume}:/home/pc/.partcad" -v "${dir}:${dir}" -w "${dir}" \
    -e PC_CONTAINER_IMAGE_TAG -e PC_CONTAINER_IMAGE_OWNER "$@"
}

step "the build's own checks, run against the image"
docker run --rm "${PC_IMAGE}" sh /usr/local/share/partcad/verify.sh

step "a command of pc's is handed to pc"
version="$(docker run --rm "${PC_IMAGE}" --no-ansi version 2>&1)" || fail "pc version: ${version}"
echo "${version}"
echo "${version}" | grep -q "PartCAD CLI version: ${PC_VERSION}" || fail "pc version does not say ${PC_VERSION}"
echo "anything else runs as it is: $(docker run --rm "${PC_IMAGE}" sh -c 'echo "$0 as uid $(id -u)"')"

step "pc upgrade refuses, and says what to do instead"
if upgrade="$(docker run --rm "${PC_IMAGE}" --no-ansi upgrade 2>&1)"; then
  fail "pc upgrade succeeded in the image: ${upgrade}"
fi
echo "${upgrade}" | grep -q "docker pull" || fail "pc upgrade did not say to pull: ${upgrade}"

step "pc init writes as the owner of the workspace, and starts the image for the agents"
mkdir "${work}/init"
run_in "${work}/init" "${PC_IMAGE}" --no-ansi init
for file in partcad.yaml .mcp.json .cursor/mcp.json; do
  [ -f "${work}/init/${file}" ] || fail "pc init did not write ${file}"
  owner="$(stat -c %u:%g "${work}/init/${file}")"
  [ "${owner}" = "${me}" ] || fail "${file} belongs to ${owner}, not to ${me} who owns the workspace"
done
grep -q '"docker"' "${work}/init/.mcp.json" || fail ".mcp.json does not start the image"
grep -q "ghcr.io/partcad/partcad" "${work}/init/.mcp.json" || fail ".mcp.json does not name the image"

step "a scripted part renders without the host's Docker (conda, inside the container)"
cp -R "${here}/examples/produce_part_build123d_primitive" "${work}/part"
mkdir "${work}/part/out"
run_in "${work}/part" -e PC_DAEMON_IDLE_TIMEOUT=0 "${PC_IMAGE}" --no-ansi render -t png -O out cube
[ -s "${work}/part/out/cube.png" ] || fail "no cube.png"
[ "$(stat -c %u:%g "${work}/part/out/cube.png")" = "${me}" ] || fail "cube.png is not the workspace owner's"
docker run --rm -v "${volume}:/home/pc/.partcad" --entrypoint sh "${PC_IMAGE}" -c \
  'ls -d /home/pc/.partcad/sandbox/pc-py-conda-*' || fail "the sandbox it rendered in is not a conda one"

step "pc mcp answers an MCP client over docker run -i"
python3 "${here}/dev-tools/ci/mcp_smoke.py" --render cube -- \
  docker run -i --rm -v "${volume}:/home/pc/.partcad" -v "${work}/part:${work}/part" -w "${work}/part" \
  "${PC_IMAGE}" mcp

if [ "${PC_SOCKET}" = "true" ]; then
  socket=/var/run/docker.sock
  # A volume of its own, so that the conda sandbox step 4 left is not what
  # renders: with a daemon to use, PartCAD chooses the 'docker' sandbox.
  volume="${volume}-socket"

  step "with the host's Docker: a scripted part renders in the docker sandbox"
  rm -rf "${work}/part/out" && mkdir "${work}/part/out"
  run_in "${work}/part" -v "${socket}:${socket}" -e PC_DAEMON_IDLE_TIMEOUT=0 \
    "${PC_IMAGE}" --no-ansi render -t png -O out cube
  [ -s "${work}/part/out/cube.png" ] || fail "no cube.png"
  [ "$(stat -c %u:%g "${work}/part/out/cube.png")" = "${me}" ] || fail "cube.png is not the workspace owner's"
  [ -n "$(docker ps -q --filter label=partcad.role=sandbox)" ] ||
    fail "no sandbox container is running on the host's daemon"
  docker run --rm -v "${volume}:/home/pc/.partcad" --entrypoint sh "${PC_IMAGE}" -c \
    '! ls -d /home/pc/.partcad/sandbox/pc-py-conda-* 2>/dev/null' || fail "it rendered in conda, not in docker"

  step "with the host's Docker: the KiCad example's board, built in KiCad's container"
  # Through the library rather than 'pc render', which renders nothing for this
  # part on any machine -- the same call 'test_part_example_kicad' makes.
  cp -R "${here}/examples/produce_part_kicad" "${work}/kicad"
  run_in "${work}/kicad" -v "${socket}:${socket}" "${PC_IMAGE}" python3 -c '
import sys

import partcad as pc
from partcad import runtime

if not runtime.docker_enabled():
    sys.exit("the host Docker is not usable from the image")
ctx = pc.init(".")
if ctx.get_project("//").skipped:
    sys.exit("the KiCad example is excluded here")
if ctx.get_part_shape("//:Arduino_Nano") is None:
    sys.exit("KiCad produced no shape")
print("Arduino_Nano built in KiCad")
'
fi

step "ok"
