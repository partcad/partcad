#!/usr/bin/env bash
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Packages the standalone PartCAD command line tools as a snap.
#
# Usage (from the repository root):
#
#   dev-tools/snap/build.sh               # build the bundle if needed, then the snap
#   dev-tools/snap/build.sh --no-bundle   # the bundle is already in dist/standalone/partcad
#   dev-tools/snap/build.sh --use-lxd     # build in an LXD container instead of on this host
#
# By default snapcraft runs in destructive mode, which builds directly on this
# machine and therefore requires it to be the same Ubuntu release as the snap's
# base (core24 -> Ubuntu 24.04). Pass --use-lxd to build in a container of the
# right release instead; that works anywhere LXD does, and is the way to build
# this on any other distribution.
#
# The environment variable PYTHON is passed through to the bundle build, which
# embeds that interpreter; see dev-tools/pyinstaller/build.sh.
#
# The snap is built for the architecture of this machine; there is no
# cross-building, because the payload is a frozen native bundle.
#
# Output (relative to the repository root):
#
#   dist/snap/partcad_<version>_<arch>.snap
#   dist/snap/partcad_<version>_<arch>.snap.sha256

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE_DIR="${REPO_ROOT}/dist/standalone/partcad"
OUTPUT_DIR="${REPO_ROOT}/dist/snap"
PYTHON="${PYTHON:-python3}"

BUILD_BUNDLE=1
SNAPCRAFT_MODE="--destructive-mode"
for arg in "$@"; do
  case "${arg}" in
  --no-bundle) BUILD_BUNDLE=0 ;;
  --use-lxd) SNAPCRAFT_MODE="--use-lxd" ;;
  --destructive-mode) SNAPCRAFT_MODE="--destructive-mode" ;;
  -h | --help)
    sed -n '7,30p' "${BASH_SOURCE[0]}"
    exit 0
    ;;
  *)
    echo "error: unknown option '${arg}'" >&2
    exit 2
    ;;
  esac
done

################################################  PLATFORM  ##################################################

# Snaps are a Linux packaging format. The architecture names are Debian's, which
# is what snapcraft puts in the file name and what `snap/snapcraft.yaml` lists
# under `platforms`.
if [ "$(uname -s)" != "Linux" ]; then
  echo "error: snaps are built on Linux only, this is '$(uname -s)'" >&2
  exit 1
fi
case "$(uname -m)" in
x86_64 | amd64) SNAP_ARCH="amd64" ;;
aarch64 | arm64) SNAP_ARCH="arm64" ;;
*)
  echo "error: no snap platform for '$(uname -m)'" >&2
  exit 1
  ;;
esac

if ! command -v snapcraft >/dev/null 2>&1; then
  echo "error: 'snapcraft' is not on PATH; install it with:" >&2
  echo "         sudo snap install snapcraft --classic" >&2
  exit 1
fi

VERSION="$("${PYTHON}" -c "
import re, pathlib
source = pathlib.Path('${REPO_ROOT}/partcad/src/partcad/__init__.py').read_text()
print(re.search(r'__version__: str = \"([^\"]+)\"', source).group(1))
")"

echo "==> Packaging PartCAD ${VERSION} as a ${SNAP_ARCH} snap"

#################################################  BUNDLE  ###################################################

# The snap is a wrapper around the PyInstaller bundle rather than a second way
# of building the same thing: one build, one answer to what was shipped. CI
# unpacks the archive the "Standalone" workflow already produced into this
# directory and passes --no-bundle.
if [ "${BUILD_BUNDLE}" = "1" ] && [ ! -e "${BUNDLE_DIR}/pc" ]; then
  echo "==> Building the standalone bundle first"
  "${REPO_ROOT}/dev-tools/pyinstaller/build.sh" --no-archive
fi

echo "==> Checking the bundle"
missing=0
# What `snap/snapcraft.yaml` organizes and turns into apps. A bundle missing any
# of these produces a snap that installs and then fails to run, so check here.
for entry in pc partcad partcad-json-rpc _internal; do
  if [ ! -e "${BUNDLE_DIR}/${entry}" ]; then
    echo "error: '${BUNDLE_DIR}/${entry}' is missing" >&2
    missing=1
  fi
done
if [ "${missing}" != "0" ]; then
  echo "       run 'dev-tools/pyinstaller/build.sh --no-archive' to produce the bundle" >&2
  exit 1
fi
echo "    $(du -sh "${BUNDLE_DIR}" | cut -f1) in ${BUNDLE_DIR}"

#################################################  PACK  #####################################################

SNAP_NAME="partcad_${VERSION}_${SNAP_ARCH}.snap"

echo "==> Running snapcraft (${SNAPCRAFT_MODE})"
mkdir -p "${OUTPUT_DIR}"
rm -f "${OUTPUT_DIR}/${SNAP_NAME}" "${OUTPUT_DIR}/${SNAP_NAME}.sha256"
# snapcraft writes the .snap into the current directory, which has to be the
# project directory -- that is how it finds `snap/snapcraft.yaml`, and what it
# resolves the part's `source: dist/standalone/partcad` against. The result is
# moved out afterwards rather than passed through `--output`, whose handling of
# a directory argument has changed between snapcraft releases.
(cd "${REPO_ROOT}" && rm -f "${SNAP_NAME}" && snapcraft pack "${SNAPCRAFT_MODE}")

if [ ! -f "${REPO_ROOT}/${SNAP_NAME}" ]; then
  echo "error: snapcraft did not produce '${SNAP_NAME}'" >&2
  echo "       built instead: $(find "${REPO_ROOT}" -maxdepth 1 -name '*.snap' -printf '%f ' || true)" >&2
  exit 1
fi
mv "${REPO_ROOT}/${SNAP_NAME}" "${OUTPUT_DIR}/${SNAP_NAME}"

# The same checksum convention the standalone archives use, so that a snap
# attached to a release can be verified the same way.
(cd "${OUTPUT_DIR}" && sha256sum "${SNAP_NAME}" >"${SNAP_NAME}.sha256")

echo "==> Done"
echo "    snap:     ${OUTPUT_DIR}/${SNAP_NAME}"
echo "    checksum: ${OUTPUT_DIR}/${SNAP_NAME}.sha256"
echo
echo "    Install it with:"
echo "      sudo snap install --dangerous --classic ${OUTPUT_DIR}/${SNAP_NAME}"
echo "      sudo snap alias partcad.pc pc"
