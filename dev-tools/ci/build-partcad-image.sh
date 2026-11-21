#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Build the PartCAD image, `ghcr.io/partcad/partcad`: PartCAD itself, for
# whoever would rather `docker run` it than install it.
#
#     dev-tools/ci/build-partcad-image.sh                      # this tree, this machine
#
#     PC_IMAGE_REFS="ghcr.io/partcad/partcad:<version> ghcr.io/partcad/partcad:latest" \
#     PC_WHEELS_DIR=dist PC_PARTCAD_VERSION=<version> \
#     PC_PLATFORMS=linux/amd64,linux/arm64 PC_PUSH=true \
#     dev-tools/ci/build-partcad-image.sh                      # the release
#
# The one place that knows how, for the reason 'build-sandbox-image.sh' gives:
# the job that tests this image and the job that publishes it build it here, so
# what was tested is what was published. Everything is read from the
# environment, and all of it is optional:
#
#   PC_IMAGE_REFS       The '<name>:<tag>' references to build, space separated.
#                       Default 'partcad:local'.
#   PC_WHEELS_DIR       A directory holding the partcad wheel to install -- the
#                       release's own file, on the release. Default: build one
#                       from this tree into a temporary directory.
#   PC_PARTCAD_VERSION  The version that wheel has to be; the build fails if it
#                       is not. Default: the Dockerfile's, which is this tree's
#                       release -- and so the version of a wheel built from it.
#   PC_BASE_TAG         The tag of the Python base image to build on, without
#                       the architecture: '<tag>-py3.11-gstreamer'. Default:
#                       this tree's release, or 'PC_CONTAINER_IMAGE_TAG' when a
#                       CI run built base images of its own (see
#                       'partcad_utils.container_image').
#   PC_BASE_IMAGE       The base image's name. Default
#                       'ghcr.io/partcad/partcad-container-python', or a fork's
#                       copy under 'PC_CONTAINER_IMAGE_OWNER'.
#   PC_PLATFORMS        'linux/amd64,linux/arm64'. Default: this machine's.
#   PC_PUSH             'true' to push, 'false' (default) to load the image into
#                       the local daemon -- one platform only, which is a
#                       limitation of loading and not of the image -- and
#                       'none' to build it and keep nothing, which is how the
#                       release is rehearsed on every version tag.
set -eu

here=$(unset CDPATH; cd -- "$(dirname -- "$0")/../.." && pwd)
# The image's own directory is the whole of its context: the Dockerfile builds
# from it alone, which is what lets anybody else build it -- Docker's MCP
# Catalog among them -- with a plain 'docker build'.
context="${here}/tools/containers/partcad"
dockerfile="${context}/Dockerfile"

PC_IMAGE_REFS="${PC_IMAGE_REFS:-partcad:local}"
PC_PUSH="${PC_PUSH:-false}"
PC_PLATFORMS="${PC_PLATFORMS:-}"
PC_PARTCAD_VERSION="${PC_PARTCAD_VERSION:-}"
PC_WHEELS_DIR="${PC_WHEELS_DIR:-}"

release=$(sed -n 's/^current_version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "${here}/dev-tools/bumpversion.toml")
if [ -z "${PC_BASE_TAG:-}" ]; then
  # The tag the sandbox images of this run were built under, when it built
  # its own, and the release's otherwise -- the same answer
  # 'container_image.image_tag' gives the code that pulls them.
  PC_BASE_TAG="${PC_CONTAINER_IMAGE_TAG:-${release}}-py3.11-gstreamer"
fi
if [ -z "${PC_BASE_IMAGE:-}" ]; then
  owner=$(printf '%s' "${PC_CONTAINER_IMAGE_OWNER:-partcad}" | tr '[:upper:]' '[:lower:]')
  PC_BASE_IMAGE="ghcr.io/${owner}/partcad-container-python"
fi

scratch=$(mktemp -d)
trap 'rm -rf "${scratch}"' EXIT
if [ -z "${PC_WHEELS_DIR}" ]; then
  # From a copy of the working tree -- what git tracks, and what it would track
  # but has not yet, changes included -- because setuptools builds in place and
  # leaves a 'build/' and an '.egg-info' in whatever directory it is given, and
  # the linters walk this checkout. tar rather than 'cp -r' so that the
  # symbolic links the build backend insists on (see 'dev-tools/build-backend')
  # arrive as links.
  #
  # 'pip wheel' rather than 'python -m build': pip is the one of the two every
  # Python has, and both go through the same in-tree PEP 517 backend.
  echo "building the wheel of ${here}"
  mkdir "${scratch}/source"
  (cd "${here}" && git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf -) |
    tar -xf - -C "${scratch}/source"
  python3 -m pip wheel --quiet --no-deps --wheel-dir "${scratch}/built" "${scratch}/source" >&2
  PC_WHEELS_DIR="${scratch}/built"
fi
# Exactly one: the release's 'dist' also holds the sdist and, after a download
# of both artifacts, the 'partcad-cli' shim -- neither is installed into this.
wheels="${scratch}/wheels"
mkdir -p "${wheels}"
found=0
for wheel in "${PC_WHEELS_DIR}"/partcad-*-py3-none-any.whl; do
  [ -f "${wheel}" ] || continue
  cp "${wheel}" "${wheels}/"
  found=$((found + 1))
done
if [ "${found}" -ne 1 ]; then
  echo "error: ${PC_WHEELS_DIR} holds ${found} partcad wheels, and the image installs exactly one" >&2
  ls -l "${PC_WHEELS_DIR}" >&2
  exit 1
fi

set -- \
  --file "${dockerfile}" \
  --build-context "wheels=${wheels}" \
  --build-arg "BASE_IMAGE=${PC_BASE_IMAGE}" \
  --build-arg "BASE_TAG=${PC_BASE_TAG}" \
  --provenance=false
if [ -n "${PC_PARTCAD_VERSION}" ]; then
  set -- "$@" --build-arg "PARTCAD_VERSION=${PC_PARTCAD_VERSION}"
fi
for ref in ${PC_IMAGE_REFS}; do
  set -- "$@" --tag "${ref}"
done
if [ -n "${PC_PLATFORMS}" ]; then
  set -- "$@" --platform "${PC_PLATFORMS}"
fi
case "${PC_PUSH}" in
true) set -- "$@" --output "type=image,push=true" ;;
false) set -- "$@" --output type=docker ;;
none) set -- "$@" --output type=cacheonly ;;
*)
  echo "error: PC_PUSH is '${PC_PUSH}'; it is 'true', 'false' or 'none'" >&2
  exit 1
  ;;
esac

echo "building ${PC_IMAGE_REFS} on ${PC_BASE_IMAGE}:${PC_BASE_TAG} (PartCAD ${PC_PARTCAD_VERSION:-of the wheel}${PC_PLATFORMS:+, ${PC_PLATFORMS}}, push=${PC_PUSH})"
docker buildx build "$@" "${context}"
