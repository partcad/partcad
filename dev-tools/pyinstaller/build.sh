#!/usr/bin/env bash
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Builds the standalone PartCAD command line tools with PyInstaller and packs
# them into the archive that `install.sh` downloads.
#
# Usage (from the repository root):
#
#   dev-tools/pyinstaller/build.sh              # install dependencies, then build
#   dev-tools/pyinstaller/build.sh --no-install # build only, dependencies are in place
#   dev-tools/pyinstaller/build.sh --no-archive # leave the bundle unpacked, skip the archive
#
# The environment variable PYTHON selects the interpreter to freeze (default
# `python3`); the bundle embeds that exact interpreter, so it decides the
# Python version users end up running.
#
# Output (relative to the repository root):
#
#   dist/standalone/partcad/                      the bundle
#   dist/standalone/partcad-<version>-<platform>.<ext>       the archive
#   dist/standalone/partcad-<version>-<platform>.<ext>.sha256

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# On Windows this script runs in Git Bash, but the Python, pip and PyInstaller
# it drives are native Windows programs: they read a Git Bash path like
# "/d/a/partcad" as the nonexistent "\d\a\partcad". `cygpath -m` converts it to
# the mixed form, "D:/a/partcad", which the native tools and Git Bash both
# understand -- unlike `cygpath -w`, whose backslashes would need re-quoting
# every time the path is interpolated below.
if command -v cygpath >/dev/null 2>&1; then
  REPO_ROOT="$(cygpath -m "${REPO_ROOT}")"
fi
SPEC_DIR="${REPO_ROOT}/dev-tools/pyinstaller"
OUTPUT_DIR="${REPO_ROOT}/dist/standalone"
PYTHON="${PYTHON:-python3}"

INSTALL_DEPENDENCIES=1
CREATE_ARCHIVE=1
for arg in "$@"; do
  case "${arg}" in
  --no-install) INSTALL_DEPENDENCIES=0 ;;
  --no-archive) CREATE_ARCHIVE=0 ;;
  -h | --help)
    sed -n '7,25p' "${BASH_SOURCE[0]}"
    exit 0
    ;;
  *)
    echo "error: unknown option '${arg}'" >&2
    exit 2
    ;;
  esac
done

################################################  PLATFORM  ##################################################

# The archive name has to say what the bundle runs on, and has to agree with
# the names `install.sh` derives from `uname`. Keep the two in sync.
case "$(uname -s)" in
Linux*) OS_NAME="linux" ;;
Darwin*) OS_NAME="macos" ;;
MINGW* | MSYS* | CYGWIN*) OS_NAME="windows" ;;
*)
  echo "error: unsupported operating system '$(uname -s)'" >&2
  exit 1
  ;;
esac

case "$(uname -m)" in
x86_64 | amd64 | AMD64) ARCH_NAME="x86_64" ;;
arm64 | aarch64) ARCH_NAME="arm64" ;;
*)
  echo "error: unsupported architecture '$(uname -m)'" >&2
  exit 1
  ;;
esac

PLATFORM="${OS_NAME}-${ARCH_NAME}"
if [ "${OS_NAME}" = "windows" ]; then
  ARCHIVE_EXT="zip"
  # PyInstaller names the executables `pc.exe` and `partcad.exe` there.
  EXE_SUFFIX=".exe"
else
  ARCHIVE_EXT="tar.gz"
  EXE_SUFFIX=""
fi

VERSION="$("${PYTHON}" -c "
import re, pathlib
source = pathlib.Path('${REPO_ROOT}/partcad/src/partcad/__init__.py').read_text()
print(re.search(r'__version__: str = \"([^\"]+)\"', source).group(1))
")"

echo "==> Building PartCAD ${VERSION} for ${PLATFORM} with $("${PYTHON}" --version)"

##############################################  DEPENDENCIES  ################################################

if [ "${INSTALL_DEPENDENCIES}" = "1" ]; then
  echo "==> Installing build dependencies"
  "${PYTHON}" -m pip install --upgrade pip wheel setuptools
  "${PYTHON}" -m pip install "pyinstaller>=6.11"

  # `partcad-cli` declares its license by a path inside its own directory, but
  # the file itself only exists in the repository root. The wheel build in
  # "deploy.yml" copies it the same way.
  cp "${REPO_ROOT}/LICENSE.txt" "${REPO_ROOT}/partcad-cli/"

  echo "==> Installing PartCAD from this checkout"
  # A frozen bundle cannot be extended with pip afterwards, so the optional
  # extras that the wheels leave to the user are all built in.
  "${PYTHON}" -m pip install "${REPO_ROOT}/partcad[ai,lint]"
  # This satisfies the `partcad==<version>` pin of `partcad-cli` with the local
  # build rather than with the release on PyPI.
  "${PYTHON}" -m pip install "${REPO_ROOT}/partcad-cli"
fi

##############################################  PRE-FLIGHT  ##################################################

# PartCAD imports these by name at runtime, so PyInstaller only finds them by
# importing them here, at build time. When that import fails, the collection is
# skipped with a warning buried in the build log and the bundle is built
# anyway: complete to look at, broken on the one code path that needed the
# package, for users only. Fail here instead, where it is still visible.
echo "==> Checking the dependencies that are imported by name"
"${PYTHON}" - <<'PREFLIGHT'
import importlib
import sys

REQUIRED = {
    "OCP": "the geometry kernel",
    "build123d": "the geometry kernel",
    "ocp_vscode": "`pc inspect` (needs Python 3.11 or newer)",
    "openai": "the OpenAI provider",
    "ollama": "the Ollama provider",
    "google.generativeai": "the Google Gemini provider",
    "ruff.__main__": "`pc lint` of Python files",
}

broken = []
for name, used_by in REQUIRED.items():
    try:
        importlib.import_module(name)
    except Exception as e:
        broken.append(f"  {name}: {used_by}\n    {type(e).__name__}: {e}")

if broken:
    print("error: these cannot be imported in this build environment, so they")
    print("       cannot be frozen into the bundle either:")
    print()
    print("\n".join(broken))
    sys.exit(1)
PREFLIGHT

################################################  FREEZE  ####################################################

echo "==> Freezing"
rm -rf "${OUTPUT_DIR}/partcad"
"${PYTHON}" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "${OUTPUT_DIR}" \
  --workpath "${REPO_ROOT}/build/pyinstaller" \
  "${SPEC_DIR}/partcad.spec"

BUNDLE_DIR="${OUTPUT_DIR}/partcad"

echo "==> Smoke testing the bundle"
# Run from a directory that is not the checkout: a bundle that accidentally
# depends on the source tree still works when started next to it.
SMOKE_DIR="$(mktemp -d)"
trap 'rm -rf "${SMOKE_DIR}"' EXIT
(cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/pc${EXE_SUFFIX}" version)
(cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/partcad${EXE_SUFFIX}" --help >/dev/null)

if [ "${CREATE_ARCHIVE}" = "0" ]; then
  echo "==> Bundle: ${BUNDLE_DIR}"
  exit 0
fi

################################################  PACKAGE  ###################################################

ARCHIVE_NAME="partcad-${VERSION}-${PLATFORM}.${ARCHIVE_EXT}"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"

echo "==> Packing ${ARCHIVE_NAME}"
rm -f "${ARCHIVE_PATH}" "${ARCHIVE_PATH}.sha256"
if [ "${ARCHIVE_EXT}" = "zip" ]; then
  (cd "${OUTPUT_DIR}" && "${PYTHON}" -m zipfile -c "${ARCHIVE_NAME}" partcad)
else
  # The archive unpacks to a single `partcad/` directory, which is what
  # `install.sh` expects to move into place.
  tar -czf "${ARCHIVE_PATH}" -C "${OUTPUT_DIR}" partcad
fi

# `install.sh` verifies this checksum before it unpacks anything.
(
  cd "${OUTPUT_DIR}"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${ARCHIVE_NAME}" >"${ARCHIVE_NAME}.sha256"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${ARCHIVE_NAME}" >"${ARCHIVE_NAME}.sha256"
  else
    "${PYTHON}" -c "
import hashlib, pathlib
name = '${ARCHIVE_NAME}'
digest = hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()
pathlib.Path(name + '.sha256').write_text(f'{digest}  {name}\n')
"
  fi
)

echo "==> Done"
echo "    bundle:   ${BUNDLE_DIR}"
echo "    archive:  ${ARCHIVE_PATH}"
echo "    checksum: ${ARCHIVE_PATH}.sha256"
