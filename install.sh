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
PLATFORM="${PARTCAD_PLATFORM:-}"
APP_DIR="${PARTCAD_APP_DIR:-}"
IDE="${PARTCAD_IDE:-0}"
UNINSTALL=0

# The name of the application bundle, as `partcad-ide-standalone/build.sh` packs
# it. Used on MacOS, where installing means putting this in an Applications
# directory.
IDE_APP_NAME="PartCAD IDE.app"

# What a release says it carries, published beside the archives by
# "dev-tools/release/platforms-manifest.sh". This script reads it rather than
# keeping its own copy of the platform list, which is a copy that drifts.
MANIFEST_NAME="platforms.json"

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
                        released, such as one produced by a pull request. It
                        must also hold the release's platforms.json, or the
                        build has to be named with --platform.
  --repository <owner/name>
                        GitHub repository to install from
                        (default: partcad/partcad).
  --platform <id>       Install this exact build instead of the one that
                        matches this machine, e.g. ubuntu-22.04-x86_64.
  --uninstall           Remove an installation made by this script.
  --help                Show this message.

Every option also has an environment variable: PARTCAD_VERSION,
PARTCAD_INSTALL_DIR, PARTCAD_BIN_DIR, PARTCAD_APP_DIR, PARTCAD_BASE_URL,
PARTCAD_REPOSITORY, PARTCAD_IDE, PARTCAD_PLATFORM.
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

###################################################  HOST  ###################################################

case "$(uname -s)" in
Linux) OS_NAME="linux" ;;
Darwin) OS_NAME="macos" ;;
MINGW* | MSYS* | CYGWIN*)
  fail "this script does not support Windows. From
       https://github.com/${REPOSITORY}/releases, run the IDE's
       'partcad-ide-<version>-windows-x86_64-setup.exe', or unpack the command
       line tools' .zip, or install the wheels with 'pip install -U partcad-cli'."
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
# and the archive name carries it: "ubuntu-24.04-x86_64", not "linux-x86_64".
#
# Which of those builds a release actually has is a property of the release and
# not of this machine, so the release says: "platforms.json", published beside
# the archives, lists them newest first. This script reads that inventory below
# and then applies the policy in this section to it -- an inventory is not an
# answer, because a build newer than this machine still cannot run here.
#
# The published builds are named after Ubuntu and macOS releases because those
# are what the builders run. The Ubuntu ones are not a statement about which
# distribution you need: the older build has the lower glibc floor, which is all
# that a non-Ubuntu Linux cares about, and that is the one such a machine is
# offered.

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

# The platform ids a release manifest lists under one kind, operating system and
# architecture, in the order it lists them. The manifest arrives on stdin.
#
# Parsed with `awk` rather than with `jq`: this installer exists so that a bare
# machine needs nothing installed, and `awk` is on every POSIX system while `jq`
# is on almost none. It is a real scanner rather than a pattern match on the
# layout we happen to generate -- strings, objects and arrays are walked while a
# path is kept -- so a reformatted or extended manifest still reads correctly,
# and a malformed one is reported instead of half understood.
manifest_platforms() {
  awk -v want="$1.$2.$3" '
    { doc = doc $0 "\n" }

    function skip_ws(   ch) {
      while (pos <= len) {
        ch = substr(doc, pos, 1)
        if (ch == " " || ch == "\t" || ch == "\r" || ch == "\n") pos++
        else return
      }
    }

    function parse_string(   out, ch) {
      pos++                                   # the opening quote
      out = ""
      while (pos <= len) {
        ch = substr(doc, pos, 1)
        if (ch == "\\") { pos++; out = out substr(doc, pos, 1); pos++; continue }
        if (ch == "\"") { pos++; return out }
        out = out ch
        pos++
      }
      bad = 1
      return out
    }

    function parse_value(path,   ch, value) {
      if (bad) return
      skip_ws()
      ch = substr(doc, pos, 1)
      if (ch == "{") { parse_object(path); return }
      if (ch == "[") { parse_array(path); return }
      if (ch == "\"") {
        value = parse_string()
        # Every entry of the wanted list is a string reached by this path, and
        # nothing else in the manifest is.
        if (path == want) print value
        return
      }
      # A number, true, false or null. Nothing here reads one, so it is skipped.
      while (pos <= len && index(" \t\r\n,]}", substr(doc, pos, 1)) == 0) pos++
      if (pos > len) bad = 1
    }

    function parse_object(path,   key, ch) {
      pos++                                   # "{"
      skip_ws()
      if (substr(doc, pos, 1) == "}") { pos++; return }
      while (pos <= len && !bad) {
        skip_ws()
        if (substr(doc, pos, 1) != "\"") { bad = 1; return }
        key = parse_string()
        skip_ws()
        if (substr(doc, pos, 1) != ":") { bad = 1; return }
        pos++
        parse_value((path == "") ? key : (path "." key))
        skip_ws()
        ch = substr(doc, pos, 1)
        pos++
        if (ch == ",") continue
        if (ch == "}") return
        bad = 1
        return
      }
      bad = 1
    }

    function parse_array(path,   ch) {
      pos++                                   # "["
      skip_ws()
      if (substr(doc, pos, 1) == "]") { pos++; return }
      while (pos <= len && !bad) {
        parse_value(path)
        skip_ws()
        ch = substr(doc, pos, 1)
        pos++
        if (ch == ",") continue
        if (ch == "]") return
        bad = 1
        return
      }
      bad = 1
    }

    END {
      len = length(doc)
      pos = 1
      skip_ws()
      if (substr(doc, pos, 1) != "{") { print "not a JSON object" > "/dev/stderr"; exit 2 }
      parse_object("")
      # The scanner stops at the closing brace of the top-level object, so
      # anything after it -- a second document, a truncated file glued to
      # something else -- would otherwise go unread and unreported, and the ids
      # gathered so far would pass for the whole manifest.
      skip_ws()
      if (bad || pos <= len) { print "malformed JSON" > "/dev/stderr"; exit 2 }
    }
  '
}

# The releases this machine could use, newest first, out of the manifest and in
# the shape candidate_releases() compares: "ubuntu-24.04-x86_64" comes back as
# "ubuntu-24.04", the architecture being settled already.
#
# An entry that carries no OS version is dropped with a warning rather than
# compared: `test -lt` against something that is not a number would end the
# install, and a manifest naming a build this script cannot reason about is a
# reason to fall back to the rest of the list, not to give up.
inventory_releases() {
  # A manifest that cannot be parsed ends the install here rather than reading
  # as an empty inventory, which would be reported as "this release has no
  # build for your machine" and send somebody looking in the wrong place.
  ir_ids="$(printf '%s\n' "${MANIFEST}" | manifest_platforms bundle "${OS_NAME}" "${ARCH_NAME}")" ||
    fail "${BASE_URL}/${MANIFEST_NAME} is not a valid release manifest.
       Use --platform to name the build to install."
  ir_result=""
  for ir_id in ${ir_ids}; do
    ir_release="${ir_id%-*}"
    case "${ir_release#*-}" in
    "${ir_release}" | '' | *[!0-9.]*)
      warn "ignoring '${ir_id}' from ${MANIFEST_NAME}: it names no OS version"
      continue
      ;;
    esac
    ir_result="${ir_result} ${ir_release}"
  done
  printf '%s' "${ir_result}"
}

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

command -v awk >/dev/null 2>&1 || fail "awk is not available; it is needed to read the release manifest"

if [ -z "${VERSION}" ]; then
  log "Looking up the latest PartCAD release..."
  # Parsed with sed rather than with a JSON tool: `jq` is exactly the kind of
  # prerequisite this installer exists to avoid.
  VERSION="$(read_url "https://api.github.com/repos/${REPOSITORY}/releases/latest" |
    sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n 1)"
  [ -n "${VERSION}" ] || fail "could not determine the latest release of ${REPOSITORY}"
fi

if [ "${IDE}" = "1" ]; then
  ARCHIVE_PREFIX="partcad-ide"
  WHAT="the PartCAD IDE"
else
  ARCHIVE_PREFIX="partcad"
  WHAT="PartCAD"
fi

: "${BASE_URL:=https://github.com/${REPOSITORY}/releases/download/${VERSION}}"

##################################################  BUILD  ###################################################

if [ -n "${PLATFORM}" ]; then
  # An explicit build: no inventory is consulted, which is also what makes
  # --platform the way out of anything this resolution gets wrong.
  PLATFORMS="${PLATFORM}"
elif [ "${IDE}" = "1" ]; then
  # The IDE is built once per operating system and architecture, not once per
  # OS version: it carries its own Electron runtime, and
  # "partcad-ide-standalone/build.sh" names its archive "<os>-<arch>". There is
  # therefore exactly one candidate and nothing to choose between, so the
  # manifest is not read. The command line tools inside it are the
  # per-OS-version bundle, but that is the IDE build's choice, not something
  # this script names.
  PLATFORMS="${OS_NAME}-${ARCH_NAME}"
else
  log "Looking up the builds ${VERSION} was published for..."
  MANIFEST="$(read_url "${BASE_URL}/${MANIFEST_NAME}" 2>/dev/null || true)"
  [ -n "${MANIFEST}" ] || fail "there is no ${MANIFEST_NAME} at
         ${BASE_URL}
       so there is no way to tell which builds this release has. Releases made
       before that file existed cannot be resolved by name, because the archives
       are named after the OS version they were built on and no machine can
       guess which of those were published. Two ways forward:
         - install the latest release, which does publish it: leave out
           --version (and --base-url, if you passed one);
         - name the build yourself, from
           https://github.com/${REPOSITORY}/releases:
             ... | sh -s -- --version ${VERSION} --platform ubuntu-22.04-${ARCH_NAME}"

  HOST_RELEASE="$(host_release)"
  BUILDS="$(inventory_releases)"
  [ -n "${BUILDS}" ] || fail "${VERSION} publishes no PartCAD bundle for ${OS_NAME} on ${ARCH_NAME}.
       See https://github.com/${REPOSITORY}/releases for what it does have, and
       use --platform to install one of those builds."

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

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT INT TERM

# The candidates are tried in order. A build can be absent from a release --
# an older release predates a platform, or a builder failed -- and every
# candidate after the first is still a bundle this machine can run, so a
# missing one moves on instead of ending the install. With --ide there is only
# ever one candidate, so this is a single download that reports the same way.
ARCHIVE=""
for candidate_platform in ${PLATFORMS}; do
  candidate="${ARCHIVE_PREFIX}-${VERSION}-${candidate_platform}.tar.gz"
  log "Downloading ${WHAT} ${VERSION} for ${candidate_platform}..."
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
    # The Exec value is tokenized on whitespace, so a launcher path that carries
    # a space -- or any other character the Desktop Entry specification reserves
    # -- has to be quoted, with '"', '`', '$' and '\\' escaped inside the quotes.
    IDE_EXEC="$(printf '%s' "${TARGET}/partcad-ide" | sed 's/["`$\\]/\\&/g')"
    cat >"${DESKTOP_DIR}/partcad-ide.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PartCAD IDE
GenericName=CAD Editor
Comment=Design manufacturable products with PartCAD
Exec="${IDE_EXEC}" %F
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
log "Installed ${WHAT} ${VERSION} (${PLATFORM}) in ${TARGET}."

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
