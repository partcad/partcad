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
PLATFORM="${PARTCAD_PLATFORM:-}"
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
  --platform <id>       Install this exact build instead of the one that
                        matches this machine, e.g. ubuntu-22.04-x86_64.
  --uninstall           Remove an installation made by this script.
  --help                Show this message.

Every option also has an environment variable: PARTCAD_VERSION,
PARTCAD_INSTALL_DIR, PARTCAD_BIN_DIR, PARTCAD_BASE_URL, PARTCAD_REPOSITORY,
PARTCAD_PLATFORM.
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
  --platform)
    PLATFORM="${2:-}"
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

# A frozen bundle links against the C library and system frameworks of the
# machine it was built on, so it runs on that OS version and everything newer,
# and on nothing older. There is therefore one build per supported OS version,
# and the archive name carries it. These lists say which builds exist, newest
# first; keep them in sync with the matrix in
# ".github/workflows/build-standalone.yml".
#
# Both lists are Ubuntu/macOS releases because those are what the builders run.
# The Ubuntu ones are not a statement about which distribution you need: the
# older build has the lower glibc floor, which is all that a non-Ubuntu Linux
# cares about, and that is the one such a machine is offered.
LINUX_BUILDS="ubuntu-24.04 ubuntu-22.04"
MACOS_BUILDS="macos-26 macos-15"

# True when $1 <= $2, comparing dotted version numbers field by field.
# Note `test` rather than `$(( ))`: a leading zero makes shell arithmetic read
# "04" as octal, and Ubuntu version numbers are full of leading zeros.
version_le() {
  vl_left="$1"
  vl_right="$2"
  while [ -n "${vl_left}" ] || [ -n "${vl_right}" ]; do
    vl_l="${vl_left%%.*}"
    vl_r="${vl_right%%.*}"
    [ -n "${vl_l}" ] || vl_l=0
    [ -n "${vl_r}" ] || vl_r=0
    [ "${vl_l}" -lt "${vl_r}" ] && return 0
    [ "${vl_l}" -gt "${vl_r}" ] && return 1
    case "${vl_left}" in *.*) vl_left="${vl_left#*.}" ;; *) vl_left="" ;; esac
    case "${vl_right}" in *.*) vl_right="${vl_right#*.}" ;; *) vl_right="" ;; esac
  done
  return 0
}

# Which release this machine is, in the same "<name>-<version>" shape as the
# build lists above, or empty when it cannot be established.
host_release() {
  case "${OS_NAME}" in
  linux)
    # Every distribution ships /etc/os-release. Only Ubuntu can be lined up
    # against the build list by version; anything else is left empty on
    # purpose, and gets the oldest build below.
    [ -r /etc/os-release ] || return 0
    # shellcheck disable=SC1091
    . /etc/os-release
    [ "${ID:-}" = "ubuntu" ] || return 0
    [ -n "${VERSION_ID:-}" ] || return 0
    printf 'ubuntu-%s' "${VERSION_ID}"
    ;;
  macos)
    # The major version is the compatibility boundary; the point release is not.
    printf 'macos-%s' "$(sw_vers -productVersion | cut -d. -f1)"
    ;;
  esac
}

# The builds worth trying on this machine, best first. A build newer than this
# machine cannot run on it, so those are dropped rather than offered and left to
# fail at first start; if that leaves nothing -- an OS older than every build --
# the oldest build is offered anyway, as the only one with a chance.
candidate_releases() {
  cr_builds="$1"
  cr_host="$2"
  cr_oldest=""
  cr_result=""
  for cr_build in ${cr_builds}; do
    cr_oldest="${cr_build}"
    if [ -z "${cr_host}" ]; then
      # An unidentified system: offer the builds oldest first, so the widest
      # compatible one is tried before anything that needs a newer libc.
      cr_result="${cr_build} ${cr_result}"
    elif version_le "${cr_build#*-}" "${cr_host#*-}"; then
      cr_result="${cr_result} ${cr_build}"
    fi
  done
  [ -n "${cr_result}" ] || cr_result="${cr_oldest}"
  printf '%s' "${cr_result}"
}

if [ -n "${PLATFORM}" ]; then
  PLATFORMS="${PLATFORM}"
else
  case "${OS_NAME}" in
  linux) BUILDS="${LINUX_BUILDS}" ;;
  macos) BUILDS="${MACOS_BUILDS}" ;;
  esac
  HOST_RELEASE="$(host_release)"
  PLATFORMS=""
  for release in $(candidate_releases "${BUILDS}" "${HOST_RELEASE}"); do
    PLATFORMS="${PLATFORMS} ${release}-${ARCH_NAME}"
  done
  if [ -n "${HOST_RELEASE}" ]; then
    log "This machine is ${HOST_RELEASE} on ${ARCH_NAME}."
  else
    log "Could not identify this system's release; trying the most portable build first."
  fi
fi

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

: "${BASE_URL:=https://github.com/${REPOSITORY}/releases/download/${VERSION}}"

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT INT TERM

# The candidates are tried in order. A build can be absent from a release --
# an older release predates a platform, or a builder failed -- and every
# candidate after the first is still a bundle this machine can run, so a
# missing one moves on instead of ending the install.
ARCHIVE=""
for candidate_platform in ${PLATFORMS}; do
  candidate="partcad-${VERSION}-${candidate_platform}.tar.gz"
  log "Downloading PartCAD ${VERSION} for ${candidate_platform}..."
  log "  ${BASE_URL}/${candidate}"
  if download "${BASE_URL}/${candidate}" "${TMP_DIR}/${candidate}"; then
    ARCHIVE="${candidate}"
    PLATFORM="${candidate_platform}"
    break
  fi
  warn "there is no ${candidate} at ${BASE_URL}"
done
[ -n "${ARCHIVE}" ] || fail "no build of ${VERSION} for this machine. Tried:${PLATFORMS}
       See https://github.com/${REPOSITORY}/releases for what is available,
       and use --platform to install a specific build."
ARCHIVE_URL="${BASE_URL}/${ARCHIVE}"

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
log "PartCAD ${VERSION} (${PLATFORM}) is installed in ${TARGET}."

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
