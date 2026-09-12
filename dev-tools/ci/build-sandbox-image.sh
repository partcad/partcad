#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Build one of PartCAD's Python sandbox base images.
#
#     PC_IMAGE_REF=ghcr.io/partcad/partcad-container-python:0.8.70-py3.11-amd64 \
#     PC_PYTHON_VERSION=3.11 PC_PARTCAD_VERSION=0.8.70 \
#     dev-tools/ci/build-sandbox-image.sh
#
# There is one of these images per supported interpreter per architecture, and
# until this file existed there were two places that knew how to build one:
# "Build the Python sandbox images" in '.github/workflows/test.yml', which
# builds the matrix and publishes it, and '.github/actions/sandbox-image',
# which built a copy in every job that renders. The same Dockerfile with the
# same two build arguments, written out twice, with nothing keeping them in
# step -- and the way that goes wrong is not a failure but a *disagreement*: a
# job testing an image built differently from the one the run published, under
# a name that says they are the same.
#
# So both call this, and there is one answer to "how is this image built".
#
# Everything is read from the environment rather than taken as arguments,
# because every caller is a CI step that already has these as environment
# variables and because a positional list of five is a list somebody will get
# out of order:
#
#   PC_IMAGE_REF        required. The full '<name>:<tag>' to build. The caller
#                       owns the tag -- see '.github/actions/container-images'
#                       for which tag a run addresses -- because the tag is the
#                       one thing about these images that is not a property of
#                       the Dockerfile.
#   PC_PYTHON_VERSION   required. The interpreter the image carries.
#   PC_PARTCAD_VERSION  required. The release installed *into* it. Not the same
#                       thing as the tag, and deliberately so: an image built
#                       from a branch to test this commit's Dockerfile still
#                       installs the release.
#   PC_PLATFORM         optional. 'linux/amd64', 'linux/arm64'. Defaults to the
#                       builder's own, which is what a job wanting an image it
#                       can run locally wants.
#   PC_PUSH             optional, 'true' or 'false' (default). Pushing and
#                       loading are exclusive in buildx: a pushed image is not
#                       in the local daemon and a loaded one is not in the
#                       registry, so the caller says which it is after.
#   PC_CACHE_FROM       optional. A registry ref to take layers from. Left
#                       empty by a caller that has nothing to point at -- the
#                       first build of a tag, most of all.
#
set -eu

: "${PC_IMAGE_REF:?PC_IMAGE_REF is required}"
: "${PC_PYTHON_VERSION:?PC_PYTHON_VERSION is required}"
: "${PC_PARTCAD_VERSION:?PC_PARTCAD_VERSION is required}"
PC_PLATFORM="${PC_PLATFORM:-}"
PC_PUSH="${PC_PUSH:-false}"
PC_CACHE_FROM="${PC_CACHE_FROM:-}"

# Resolved against this file rather than the working directory, so that a
# caller's 'cd' cannot change which Dockerfile gets built.
here=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
context="${here}/tools/containers"
dockerfile="${context}/python/Dockerfile"

set -- \
  --build-arg "PYTHON_VERSION=${PC_PYTHON_VERSION}" \
  --build-arg "PARTCAD_VERSION=${PC_PARTCAD_VERSION}" \
  --tag "${PC_IMAGE_REF}" \
  --file "${dockerfile}"

# Spelled as 'if' rather than '[ ... ] && ...': under 'set -e' the latter is a
# list whose status is the test's when the test fails, and whether that exits
# is exactly the corner of errexit shells disagree about.
if [ -n "${PC_PLATFORM}" ]; then
  set -- "$@" --platform "${PC_PLATFORM}"
fi
if [ -n "${PC_CACHE_FROM}" ]; then
  set -- "$@" --cache-from "type=registry,ref=${PC_CACHE_FROM}"
fi

if [ "${PC_PUSH}" = "true" ]; then
  # Inline cache so that the layers this publishes are what the next build
  # takes 'PC_CACHE_FROM' from. Only on a push: there is nothing to write it
  # into otherwise.
  set -- "$@" --cache-to type=inline --output "type=image,push=true"
else
  # Into the local daemon, which is the whole point for a caller that is about
  # to run it. 'type=docker' rather than '--load', which is the same thing
  # spelled in a way that does not compose with '--output'.
  set -- "$@" --output type=docker
fi

echo "building ${PC_IMAGE_REF} (python ${PC_PYTHON_VERSION}, PartCAD ${PC_PARTCAD_VERSION}${PC_PLATFORM:+, ${PC_PLATFORM}}, push=${PC_PUSH})"
exec docker buildx build "$@" "${context}"
