#!/bin/sh
#
# The tag this package's image would be published and pinned under: a hash of
# what it is built from, not a version -- as partcad-cae-elmer and the other
# CAE packages do it. A content tag is immutable, so a `dockerImage:` pin keeps
# working when the image is next edited.
set -eu

cd "$(dirname "$0")"

PYTHON_VERSION="${PYTHON_VERSION:-3.11}"

if command -v sha256sum >/dev/null 2>&1; then
    SUM="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    SUM="shasum -a 256"
else
    echo "image-tag.sh needs sha256sum or shasum" >&2
    exit 1
fi

{ echo "python ${PYTHON_VERSION}"; cat Dockerfile verify_image.py; } | ${SUM} | cut -c1-12
