#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Installs the standalone PartCAD command line tools: a self-contained bundle
# that carries its own Python interpreter, for machines that have no Python
# installed and no interest in managing Python environments.
#
#   curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh
#
# Run `... | sh -s -- --help` for the options.
#
# This script is written for POSIX `sh` on purpose: it has to run on whatever
# shell a bare machine happens to have.

set -eu

REPOSITORY="${PARTCAD_REPOSITORY:-partcad/partcad}"
VERSION="${PARTCAD_VERSION:-}"
BASE_URL="${PARTCAD_BASE_URL:-}"
INSTALL_DIR="${PARTCAD_INSTALL_DIR:-}"
BIN_DIR="${PARTCAD_BIN_DIR:-}"
UNINSTALL=0

usage() {
  cat <<'EOF'
Install the standalone PartCAD command line tools.

Usage:
  curl -fsSL <this script> | sh
  curl -fsSL <this script> | sh -s -- [options]

Options:
  --version <version>   Version to install (default: the latest release).
  --install-dir <dir>   Where to unpack the bundle
                        (default: ${XDG_DATA_HOME:-~/.local/share}/partcad).
  --bin-dir <dir>       Where to link the `pc` and `partcad` commands
                        (default: ~/.local/bin).
  --base-url <url>      Directory holding the archives, instead of the GitHub
                        release. Use it to install a build that is not
                        released, such as one produced by a pull request.
  --repository <owner/name>
                        GitHub repository to install from
                        (default: partcad/partcad).
  --uninstall           Remove an installation made by this script.
  --help                Show this message.

Every option also has an environment variable: PARTCAD_VERSION,
PARTCAD_INSTALL_DIR, PARTCAD_BIN_DIR, PARTCAD_BASE_URL, PARTCAD_REPOSITORY.
EOF
}

log() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
  --version)
    VERSION="${2:-}"
    shift 2
    ;;
  --install-dir)
    INSTALL_DIR="${2:-}"
    shift 2
    ;;
  --bin-dir)
    BIN_DIR="${2:-}"
    shift 2
    ;;
  --base-url)
    BASE_URL="${2:-}"
    shift 2
    ;;
  --repository)
    REPOSITORY="${2:-}"
    shift 2
    ;;
  --uninstall)
    UNINSTALL=1
    shift
    ;;
  --help | -h)
    usage
    exit 0
    ;;
  *) fail "unknown option '$1' (try --help)" ;;
  esac
done

: "${INSTALL_DIR:=${XDG_DATA_HOME:-${HOME}/.local/share}/partcad}"
: "${BIN_DIR:=${HOME}/.local/bin}"

##############################################  UNINSTALL  ###################################################

if [ "${UNINSTALL}" = "1" ]; then
  for command_name in pc partcad; do
    link="${BIN_DIR}/${command_name}"
    # Only remove links this script owns. Anything else on PATH by that name,
    # a wheel install of `pc` above all, is somebody else's.
    if [ -L "${link}" ]; then
      # Compared as written rather than resolved, so that a link left dangling
      # by a half-removed installation is still recognized as ours.
      case "$(readlink "${link}")" in
      "${INSTALL_DIR}"/*)
        rm -f "${link}"
        log "Removed ${link}"
        ;;
      *) warn "left ${link} alone: it does not point into ${INSTALL_DIR}" ;;
      esac
    fi
  done
  if [ -d "${INSTALL_DIR}" ]; then
    rm -rf "${INSTALL_DIR}"
    log "Removed ${INSTALL_DIR}"
  fi
  log ""
  log "PartCAD is uninstalled. Its cache and configuration in ~/.partcad were kept;"
  log "remove that directory too if you want nothing left behind."
  exit 0
fi

###############################################  PLATFORM  ###################################################

case "$(uname -s)" in
Linux) OS_NAME="linux" ;;
Darwin) OS_NAME="macos" ;;
MINGW* | MSYS* | CYGWIN*)
  fail "this script does not support Windows. Download the .zip from
       https://github.com/${REPOSITORY}/releases and unpack it, or install the
       wheels with 'pip install -U partcad-cli'."
  ;;
*) fail "unsupported operating system '$(uname -s)'" ;;
esac

case "$(uname -m)" in
x86_64 | amd64) ARCH_NAME="x86_64" ;;
arm64 | aarch64) ARCH_NAME="arm64" ;;
*) fail "unsupported architecture '$(uname -m)'" ;;
esac

PLATFORM="${OS_NAME}-${ARCH_NAME}"

################################################  FETCH  #####################################################

if command -v curl >/dev/null 2>&1; then
  download() { curl -fsSL "$1" -o "$2"; }
  read_url() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
  download() { wget -q "$1" -O "$2"; }
  read_url() { wget -q "$1" -O -; }
else
  fail "neither curl nor wget is available"
fi

if [ -z "${VERSION}" ]; then
  log "Looking up the latest PartCAD release..."
  # Parsed with sed rather than with a JSON tool: `jq` is exactly the kind of
  # prerequisite this installer exists to avoid.
  VERSION="$(read_url "https://api.github.com/repos/${REPOSITORY}/releases/latest" |
    sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n 1)"
  [ -n "${VERSION}" ] || fail "could not determine the latest release of ${REPOSITORY}"
fi

ARCHIVE="partcad-${VERSION}-${PLATFORM}.tar.gz"
: "${BASE_URL:=https://github.com/${REPOSITORY}/releases/download/${VERSION}}"
ARCHIVE_URL="${BASE_URL}/${ARCHIVE}"

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT INT TERM

log "Downloading PartCAD ${VERSION} for ${PLATFORM}..."
log "  ${ARCHIVE_URL}"
download "${ARCHIVE_URL}" "${TMP_DIR}/${ARCHIVE}" || fail "download failed.
       There may be no build of ${VERSION} for ${PLATFORM}. See
       https://github.com/${REPOSITORY}/releases for what is available."

# The download itself is authenticated by HTTPS; the checksum is here to catch
# a truncated or corrupted transfer, so a machine without a checksum tool gets
# a warning rather than a refusal.
if download "${ARCHIVE_URL}.sha256" "${TMP_DIR}/${ARCHIVE}.sha256" 2>/dev/null; then
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "${TMP_DIR}" && sha256sum -c "${ARCHIVE}.sha256" >/dev/null) ||
      fail "checksum mismatch, the download is corrupted"
    log "Checksum verified."
  elif command -v shasum >/dev/null 2>&1; then
    (cd "${TMP_DIR}" && shasum -a 256 -c "${ARCHIVE}.sha256" >/dev/null) ||
      fail "checksum mismatch, the download is corrupted"
    log "Checksum verified."
  else
    warn "no sha256 tool found, skipping checksum verification"
  fi
else
  warn "no checksum published next to the archive, skipping verification"
fi

###############################################  INSTALL  ####################################################

log "Unpacking..."
tar -xzf "${TMP_DIR}/${ARCHIVE}" -C "${TMP_DIR}"
[ -x "${TMP_DIR}/partcad/pc" ] || fail "the archive does not look like a PartCAD bundle"

TARGET="${INSTALL_DIR}/${VERSION}"
mkdir -p "${INSTALL_DIR}"
# Replacing an existing copy of the same version: move the old one aside first,
# so a failure here cannot leave a half-deleted installation behind.
if [ -e "${TARGET}" ]; then
  rm -rf "${TARGET}.old"
  mv "${TARGET}" "${TARGET}.old"
fi
mv "${TMP_DIR}/partcad" "${TARGET}"
rm -rf "${TARGET}.old"

mkdir -p "${BIN_DIR}"
for command_name in pc partcad; do
  link="${BIN_DIR}/${command_name}"
  if [ -e "${link}" ] && [ ! -L "${link}" ]; then
    warn "${link} exists and is not a symlink, leaving it alone.
         The standalone command is at ${TARGET}/${command_name}."
    continue
  fi
  ln -sf "${TARGET}/${command_name}" "${link}"
done

log ""
log "PartCAD ${VERSION} is installed in ${TARGET}."

case ":${PATH}:" in
*":${BIN_DIR}:"*)
  log "Run 'pc --help' to get started."
  ;;
*)
  log ""
  log "${BIN_DIR} is not on your PATH. Add it, for example:"
  log ""
  log "    echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.profile"
  log "    export PATH=\"${BIN_DIR}:\$PATH\""
  log ""
  log "Then run 'pc --help' to get started."
  ;;
esac

log ""
log "PartCAD runs CAD scripts in a sandbox it builds with conda, and clones"
log "package repositories with git. Install conda and git to use those parts;"
log "'pc healthcheck' reports what is missing."
