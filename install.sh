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
# With `--ide`, installs the PartCAD IDE instead: the editor, the PartCAD
# extension and those same command line tools, in one application.
#
#   curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh -s -- --ide
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
APP_DIR="${PARTCAD_APP_DIR:-}"
IDE="${PARTCAD_IDE:-0}"
UNINSTALL=0

# The name of the application bundle, as `partcad-ide-standalone/build.sh` packs
# it. Used on MacOS, where installing means putting this in an Applications
# directory.
IDE_APP_NAME="PartCAD IDE.app"

usage() {
  cat <<'EOF'
Install the standalone PartCAD command line tools, or the PartCAD IDE.

Usage:
  curl -fsSL <this script> | sh
  curl -fsSL <this script> | sh -s -- [options]

Options:
  --ide                 Install the PartCAD IDE: the editor with the PartCAD
                        extension and the command line tools inside it, rather
                        than the command line tools alone. `pc` and `partcad`
                        are linked from the copy the IDE carries, so nothing is
                        downloaded twice.
  --version <version>   Version to install (default: the latest release).
  --install-dir <dir>   Where to unpack the bundle
                        (default: ${XDG_DATA_HOME:-~/.local/share}/partcad).
  --bin-dir <dir>       Where to link the `pc` and `partcad` commands
                        (default: ~/.local/bin).
  --app-dir <dir>       MacOS, with --ide: where to put the application
                        (default: /Applications, or ~/Applications when that is
                        not writable).
  --base-url <url>      Directory holding the archives, instead of the GitHub
                        release. Use it to install a build that is not
                        released, such as one produced by a pull request.
  --repository <owner/name>
                        GitHub repository to install from
                        (default: partcad/partcad).
  --uninstall           Remove an installation made by this script.
  --help                Show this message.

Every option also has an environment variable: PARTCAD_VERSION,
PARTCAD_INSTALL_DIR, PARTCAD_BIN_DIR, PARTCAD_APP_DIR, PARTCAD_BASE_URL,
PARTCAD_REPOSITORY, PARTCAD_IDE.
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
  --app-dir)
    APP_DIR="${2:-}"
    shift 2
    ;;
  --ide)
    IDE=1
    shift
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

# An application bundle is this script's only if it says it is a PartCAD IDE.
# Somebody else's application that happens to share the name is left alone.
is_our_app() {
  [ -d "$1" ] && grep -q '"applicationName": *"partcad-ide"' "$1/Contents/Resources/app/product.json" 2>/dev/null
}

if [ "${UNINSTALL}" = "1" ]; then
  # Where an installed IDE can be: the directory asked for, then the two an
  # --ide install picks between on MacOS.
  APP_PATH=""
  for directory in "${APP_DIR}" "/Applications" "${HOME}/Applications"; do
    [ -n "${directory}" ] || continue
    if is_our_app "${directory}/${IDE_APP_NAME}"; then
      APP_PATH="${directory}/${IDE_APP_NAME}"
      break
    fi
  done

  for command_name in pc partcad partcad-ide; do
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
      *)
        if [ -n "${APP_PATH}" ]; then
          case "$(readlink "${link}")" in
          "${APP_PATH}"/*)
            rm -f "${link}"
            log "Removed ${link}"
            continue
            ;;
          esac
        fi
        warn "left ${link} alone: it does not point into ${INSTALL_DIR}"
        ;;
      esac
    fi
  done

  if [ -n "${APP_PATH}" ]; then
    rm -rf "${APP_PATH}"
    log "Removed ${APP_PATH}"
  fi

  # The desktop entry an --ide install writes on Linux, and its icon.
  DESKTOP_FILE="${XDG_DATA_HOME:-${HOME}/.local/share}/applications/partcad-ide.desktop"
  DESKTOP_ICON="${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor/512x512/apps/partcad-ide.png"
  for path in "${DESKTOP_FILE}" "${DESKTOP_ICON}"; do
    if [ -f "${path}" ]; then
      rm -f "${path}"
      log "Removed ${path}"
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
       https://github.com/${REPOSITORY}/releases and unpack it -- both the
       command line tools and the IDE are published as .zip archives there --
       or install the wheels with 'pip install -U partcad-cli'."
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

if [ "${IDE}" = "1" ]; then
  ARCHIVE="partcad-ide-${VERSION}-${PLATFORM}.tar.gz"
  WHAT="the PartCAD IDE"
else
  ARCHIVE="partcad-${VERSION}-${PLATFORM}.tar.gz"
  WHAT="PartCAD"
fi
: "${BASE_URL:=https://github.com/${REPOSITORY}/releases/download/${VERSION}}"
ARCHIVE_URL="${BASE_URL}/${ARCHIVE}"

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT INT TERM

log "Downloading ${WHAT} ${VERSION} for ${PLATFORM}..."
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

# Replace an existing copy by moving the old one aside first, so that a failure
# part way through cannot leave a half-deleted installation behind.
replace() {
  if [ -e "$2" ]; then
    rm -rf "$2.old"
    mv "$2" "$2.old"
  fi
  mv "$1" "$2"
  rm -rf "$2.old"
}

# Link a command into BIN_DIR, unless something that is not ours is there.
link_command() {
  link="${BIN_DIR}/$2"
  if [ -e "${link}" ] && [ ! -L "${link}" ]; then
    warn "${link} exists and is not a symlink, leaving it alone.
         The standalone command is at $1."
    return 0
  fi
  ln -sf "$1" "${link}"
}

mkdir -p "${BIN_DIR}"

if [ "${IDE}" = "1" ]; then
  if [ "${OS_NAME}" = "macos" ]; then
    [ -d "${TMP_DIR}/${IDE_APP_NAME}" ] || fail "the archive does not look like a PartCAD IDE"
    if [ -z "${APP_DIR}" ]; then
      # /Applications when this account may write there, which is the usual case
      # for the first account on a Mac, and the per-user directory otherwise. No
      # sudo either way: this installer never asks for a password.
      if [ -w "/Applications" ]; then
        APP_DIR="/Applications"
      else
        APP_DIR="${HOME}/Applications"
      fi
    fi
    mkdir -p "${APP_DIR}"
    TARGET="${APP_DIR}/${IDE_APP_NAME}"
    if [ -e "${TARGET}" ] && ! is_our_app "${TARGET}"; then
      fail "${TARGET} exists and was not installed by this script. Move it aside,
       or install elsewhere with --app-dir."
    fi
    replace "${TMP_DIR}/${IDE_APP_NAME}" "${TARGET}"

    # The bundle is signed ad-hoc rather than with a Developer ID, so MacOS
    # would refuse to open it while it carries the "downloaded from the
    # internet" flag. The user just asked for it by running this script, which
    # is the judgement Gatekeeper is asking for.
    if command -v xattr >/dev/null 2>&1; then
      xattr -dr com.apple.quarantine "${TARGET}" 2>/dev/null || true
    fi

    IDE_LAUNCHER="${TARGET}/Contents/Resources/app/bin/partcad-ide"
    TOOLS_DIR="${TARGET}/Contents/Resources/partcad-cli"
  else
    [ -x "${TMP_DIR}/partcad-ide/partcad-ide" ] || fail "the archive does not look like a PartCAD IDE"
    mkdir -p "${INSTALL_DIR}"
    TARGET="${INSTALL_DIR}/${VERSION}-ide"
    replace "${TMP_DIR}/partcad-ide" "${TARGET}"

    IDE_LAUNCHER="${TARGET}/bin/partcad-ide"
    TOOLS_DIR="${TARGET}/resources/partcad-cli"

    # So that the IDE appears in the desktop environment's application menu,
    # which is where someone who installed an editor looks for it.
    DESKTOP_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
    ICON_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor/512x512/apps"
    mkdir -p "${DESKTOP_DIR}" "${ICON_DIR}"
    if [ -f "${TARGET}/partcad-ide.png" ]; then
      cp "${TARGET}/partcad-ide.png" "${ICON_DIR}/partcad-ide.png"
    fi
    cat >"${DESKTOP_DIR}/partcad-ide.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PartCAD IDE
GenericName=CAD Editor
Comment=Design manufacturable products with PartCAD
Exec=${TARGET}/partcad-ide %F
Icon=partcad-ide
Categories=Development;Engineering;Graphics;
Keywords=partcad;cad;
StartupNotify=false
StartupWMClass=partcad-ide
MimeType=inode/directory;text/plain;
EOF
    if command -v update-desktop-database >/dev/null 2>&1; then
      update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
    fi
  fi

  link_command "${IDE_LAUNCHER}" partcad-ide

  # The IDE carries the same command line tools as the standalone bundle, so
  # `pc` comes from inside it rather than from a second download.
  for command_name in pc partcad; do
    if [ -x "${TOOLS_DIR}/${command_name}" ]; then
      link_command "${TOOLS_DIR}/${command_name}" "${command_name}"
    fi
  done
else
  [ -x "${TMP_DIR}/partcad/pc" ] || fail "the archive does not look like a PartCAD bundle"
  mkdir -p "${INSTALL_DIR}"
  TARGET="${INSTALL_DIR}/${VERSION}"
  replace "${TMP_DIR}/partcad" "${TARGET}"

  for command_name in pc partcad; do
    link_command "${TARGET}/${command_name}" "${command_name}"
  done
fi

log ""
log "Installed ${WHAT} ${VERSION} in ${TARGET}."

if [ "${IDE}" = "1" ]; then
  log "Start it from your applications, or run 'partcad-ide'."
fi

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
