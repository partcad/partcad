#!/usr/bin/env bash
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Builds the PartCAD IDE: a VSCodium build, rebranded, carrying the PartCAD
# extension and the extensions this repository recommends, and -- when it is
# given one -- the standalone PartCAD command line tools, so that the result
# needs nothing else on the user's machine.
#
# Usage (from anywhere):
#
#   ide/standalone/build.sh
#   ide/standalone/build.sh --with-cli-bundle dist/standalone/partcad
#   ide/standalone/build.sh --no-archive       # leave it unpacked
#   ide/standalone/build.sh --record           # pin what it downloaded
#
# Output (relative to the repository root):
#
#   dist/ide/partcad-ide/                              the application (Linux, Windows)
#   dist/ide/PartCAD IDE.app/                          the application (MacOS)
#   dist/ide/partcad-ide-<version>-<platform>.<ext>    the archive, and its .sha256
#   dist/ide/partcad-ide-<version>-<platform>-setup.exe  Windows only, the installer
#   dist/ide/partcad-ide-<version>-<platform>.dmg      MacOS only, with --dmg
#
# Everything the build does to the VSCodium it downloads is in this file and in
# `tools/`; `README.md` says why each of those steps exists.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
# On Windows this runs in Git Bash while the tools it drives (Python, npm, the
# VSCodium command line) are native Windows programs, which read "/d/a/partcad"
# as the nonexistent "\d\a\partcad". Same treatment as in
# `dev-tools/pyinstaller/build.sh`, for the same reason.
if command -v cygpath >/dev/null 2>&1; then
  SCRIPT_DIR="$(cygpath -m "${SCRIPT_DIR}")"
  REPO_ROOT="$(cygpath -m "${REPO_ROOT}")"
fi

OUTPUT_DIR="${REPO_ROOT}/dist/ide"
CACHE_DIR="${REPO_ROOT}/build/vscodium"
STAGE_DIR="${REPO_ROOT}/build/ide"
PYTHON="${PYTHON:-python3}"
PIN_FILE="${SCRIPT_DIR}/vscodium.json"

VSCODIUM_REPOSITORY="${VSCODIUM_REPOSITORY:-VSCodium/vscodium}"
VSCODIUM_VERSION="${VSCODIUM_VERSION:-}"
CLI_BUNDLE=""
EXTENSION_VSIX=""
CREATE_ARCHIVE=1
CREATE_DMG=0
CREATE_INSTALLER=1
INSTALL_EXTENSIONS=1
BRAND_ICONS=1
RECORD_PIN=0

usage() {
  sed -n '7,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --with-cli-bundle <dir>  Embed the standalone PartCAD command line tools from
                           this directory (what `dev-tools/pyinstaller/build.sh`
                           leaves in `dist/standalone/partcad`). Without it the
                           IDE is built without them, and asks the user to
                           download them on first use.
  --vsix <path>            The PartCAD extension to install. Defaults to
                           `ide/vscode/partcad.vsix`, built with `npm`
                           if it is not there yet.
  --vscodium-version <tag> Build from this VSCodium release instead of the one
                           `vscodium.json` pins (or the latest, when it pins
                           none).
  --no-extensions          Skip installing extensions. For iterating on the
                           branding; the result is not shippable.
  --no-icons               Keep VSCodium's icons.
  --no-archive             Stop after the application, skip the archive.
  --no-installer           Skip the Windows installer (Windows only). Without
                           this it is built whenever Inno Setup is installed.
  --dmg                    Also produce a .dmg (MacOS only).
  --record                 Write the VSCodium version and checksum that were
                           used into `vscodium.json`, to be committed as a pin.
  --help                   Show this message.
EOF
}

log() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

# An option that takes a value must be given one: an empty '--with-cli-bundle'
# would otherwise take the "no tools given" path and only warn, and the released
# IDE would ship without the command line tools the operator asked for. A missing
# one would fail in `shift 2` with the shell's message rather than ours.
require_value() {
  [ -n "${2:-}" ] || fail "$1 needs a value (try --help)"
}

while [ $# -gt 0 ]; do
  case "$1" in
  --with-cli-bundle)
    require_value "$1" "${2:-}"
    CLI_BUNDLE="$2"
    shift 2
    ;;
  --vsix)
    require_value "$1" "${2:-}"
    EXTENSION_VSIX="$2"
    shift 2
    ;;
  --vscodium-version)
    require_value "$1" "${2:-}"
    VSCODIUM_VERSION="$2"
    shift 2
    ;;
  --no-extensions)
    INSTALL_EXTENSIONS=0
    shift
    ;;
  --no-icons)
    BRAND_ICONS=0
    shift
    ;;
  --no-archive)
    CREATE_ARCHIVE=0
    shift
    ;;
  --no-installer)
    CREATE_INSTALLER=0
    shift
    ;;
  --dmg)
    CREATE_DMG=1
    shift
    ;;
  --record)
    RECORD_PIN=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *) fail "unknown option '$1' (try --help)" ;;
  esac
done

################################################  PLATFORM  ##################################################

# The archive name says what the application runs on, in the same words as the
# command line bundles in `dev-tools/pyinstaller/build.sh` and the names
# `install.sh` derives from `uname`. Keep the three in sync.
case "$(uname -s)" in
Linux*) OS_NAME="linux" ;;
Darwin*) OS_NAME="macos" ;;
MINGW* | MSYS* | CYGWIN*) OS_NAME="windows" ;;
*) fail "unsupported operating system '$(uname -s)'" ;;
esac

case "$(uname -m)" in
x86_64 | amd64 | AMD64) ARCH_NAME="x86_64" ;;
arm64 | aarch64) ARCH_NAME="arm64" ;;
*) fail "unsupported architecture '$(uname -m)'" ;;
esac

PLATFORM="${OS_NAME}-${ARCH_NAME}"

# VSCodium names its release assets after the platform triple Electron uses.
case "${PLATFORM}" in
linux-x86_64) VSCODIUM_PLATFORM="linux-x64" ;;
linux-arm64) VSCODIUM_PLATFORM="linux-arm64" ;;
macos-x86_64) VSCODIUM_PLATFORM="darwin-x64" ;;
macos-arm64) VSCODIUM_PLATFORM="darwin-arm64" ;;
windows-x86_64) VSCODIUM_PLATFORM="win32-x64" ;;
windows-arm64) VSCODIUM_PLATFORM="win32-arm64" ;;
*) fail "no VSCodium build for '${PLATFORM}'" ;;
esac

if [ "${OS_NAME}" = "linux" ]; then
  VSCODIUM_EXT="tar.gz"
else
  VSCODIUM_EXT="zip"
fi

if [ "${OS_NAME}" = "windows" ]; then
  ARCHIVE_EXT="zip"
  EXE_SUFFIX=".exe"
else
  ARCHIVE_EXT="tar.gz"
  EXE_SUFFIX=""
fi

# Every `python -c` below takes its values through `sys.argv`. Interpolating them
# into the source would break the program on a path or a version that contains a
# quote or a backslash, and would run whatever such a value spelled out.
VERSION="$("${PYTHON}" -c "
import re, pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text()
print(re.search(r'__version__: str = \"([^\"]+)\"', source).group(1))
" "${REPO_ROOT}/src/partcad/__init__.py")"

log "==> Building the PartCAD IDE ${VERSION} for ${PLATFORM}"

#################################################  FETCH  ####################################################

if command -v curl >/dev/null 2>&1; then
  download() { curl -fsSL "$1" -o "$2"; }
  read_url() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
  download() { wget -q "$1" -O "$2"; }
  read_url() { wget -q "$1" -O -; }
else
  fail "neither curl nor wget is available"
fi

if [ -z "${VSCODIUM_VERSION}" ]; then
  VSCODIUM_VERSION="$("${PYTHON}" -c "
import sys
sys.path.insert(0, sys.argv[1])
import jsonc
print(jsonc.load(sys.argv[2]).get('version') or '')
" "${SCRIPT_DIR}/tools" "${PIN_FILE}")"
fi

if [ -z "${VSCODIUM_VERSION}" ]; then
  log "==> Looking up the latest VSCodium release (nothing is pinned in vscodium.json)"
  VSCODIUM_VERSION="$(read_url "https://api.github.com/repos/${VSCODIUM_REPOSITORY}/releases/latest" |
    sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n 1)"
  [ -n "${VSCODIUM_VERSION}" ] || fail "could not determine the latest release of ${VSCODIUM_REPOSITORY}"
fi

VSCODIUM_ASSET="VSCodium-${VSCODIUM_PLATFORM}-${VSCODIUM_VERSION}.${VSCODIUM_EXT}"
VSCODIUM_URL="https://github.com/${VSCODIUM_REPOSITORY}/releases/download/${VSCODIUM_VERSION}/${VSCODIUM_ASSET}"
VSCODIUM_ARCHIVE="${CACHE_DIR}/${VSCODIUM_ASSET}"

mkdir -p "${CACHE_DIR}"
if [ -f "${VSCODIUM_ARCHIVE}" ]; then
  log "==> Using the cached ${VSCODIUM_ASSET}"
else
  log "==> Downloading ${VSCODIUM_URL}"
  download "${VSCODIUM_URL}" "${VSCODIUM_ARCHIVE}.part" ||
    fail "could not download ${VSCODIUM_ASSET}.
       Check that ${VSCODIUM_VERSION} is a release of ${VSCODIUM_REPOSITORY} and that it
       publishes a build for ${VSCODIUM_PLATFORM}: https://github.com/${VSCODIUM_REPOSITORY}/releases"
  mv "${VSCODIUM_ARCHIVE}.part" "${VSCODIUM_ARCHIVE}"
fi

ACTUAL_SHA256="$("${PYTHON}" -c "
import hashlib, pathlib, sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
" "${VSCODIUM_ARCHIVE}")"

EXPECTED_SHA256="$("${PYTHON}" -c "
import sys
sys.path.insert(0, sys.argv[1])
import jsonc
print(jsonc.load(sys.argv[2]).get('checksums', {}).get(sys.argv[3]) or '')
" "${SCRIPT_DIR}/tools" "${PIN_FILE}" "${VSCODIUM_ASSET}")"

if [ -n "${EXPECTED_SHA256}" ]; then
  [ "${EXPECTED_SHA256}" = "${ACTUAL_SHA256}" ] ||
    fail "${VSCODIUM_ASSET} does not match the checksum pinned in vscodium.json.
       expected ${EXPECTED_SHA256}
       actual   ${ACTUAL_SHA256}
       Either the download is corrupted, or upstream replaced the asset. Do not
       build a released IDE from it until you know which."
  log "==> Checksum matches the pin in vscodium.json"
else
  warn "no checksum pinned for ${VSCODIUM_ASSET}; it is verified only by HTTPS.
         Run this script with --record and commit vscodium.json to pin it."
fi

if [ "${RECORD_PIN}" = "1" ]; then
  "${PYTHON}" -c "
import json, sys
sys.path.insert(0, sys.argv[1])
import jsonc

pin = jsonc.load(sys.argv[2])
pin['version'] = sys.argv[3]
pin.setdefault('checksums', {})[sys.argv[4]] = sys.argv[5]
with open(sys.argv[2], 'w', encoding='utf-8') as handle:
    json.dump(pin, handle, indent=2, sort_keys=True)
    handle.write('\n')
" "${SCRIPT_DIR}/tools" "${PIN_FILE}" "${VSCODIUM_VERSION}" "${VSCODIUM_ASSET}" "${ACTUAL_SHA256}"
  # The comments explaining the file are lost when it is rewritten as plain
  # JSON, and putting them back by hand is the point of showing this.
  warn "vscodium.json was rewritten without its comments; restore them before committing."
  log "==> Recorded ${VSCODIUM_VERSION} and the checksum of ${VSCODIUM_ASSET} in vscodium.json"
fi

################################################  UNPACK  ####################################################

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"
log "==> Unpacking ${VSCODIUM_ASSET}"
case "${VSCODIUM_EXT}" in
tar.gz) tar -xzf "${VSCODIUM_ARCHIVE}" -C "${STAGE_DIR}" ;;
zip)
  if [ "${OS_NAME}" = "macos" ]; then
    # `unzip` drops the symlinks and the permission bits an application bundle
    # is made of; `ditto` is what Apple ships for exactly this.
    ditto -x -k "${VSCODIUM_ARCHIVE}" "${STAGE_DIR}"
  else
    unzip -q "${VSCODIUM_ARCHIVE}" -d "${STAGE_DIR}"
  fi
  ;;
esac

# Some releases wrap the application in a directory and some do not, and the
# MacOS bundle spells the same directory "Resources". Find the application by
# the one file that is always in it, rather than by a layout that varies.
PRODUCT_JSON="$(find "${STAGE_DIR}" -maxdepth 5 -type f -ipath "*/resources/app/product.json" | head -n 1)"
[ -n "${PRODUCT_JSON}" ] || fail "no resources/app/product.json under ${STAGE_DIR}: this is not a VSCodium build"

RESOURCES_DIR="$(cd -- "$(dirname -- "$(dirname -- "${PRODUCT_JSON}")")" && pwd)"
if [ "${OS_NAME}" = "macos" ]; then
  # <bundle>.app/Contents/Resources/app/product.json
  APP_ROOT="$(cd -- "$(dirname -- "$(dirname -- "${RESOURCES_DIR}")")" && pwd)"
else
  # <directory>/resources/app/product.json
  APP_ROOT="$(cd -- "$(dirname -- "${RESOURCES_DIR}")" && pwd)"
fi

##############################################  EXTENSIONS  ##################################################

if [ "${OS_NAME}" = "macos" ]; then
  LAUNCHER_DIR="${RESOURCES_DIR}/app/bin"
else
  LAUNCHER_DIR="${APP_ROOT}/bin"
fi

if [ "${OS_NAME}" = "windows" ]; then
  VSCODIUM_CLI="${LAUNCHER_DIR}/codium.cmd"
else
  VSCODIUM_CLI="${LAUNCHER_DIR}/codium"
fi
[ -f "${VSCODIUM_CLI}" ] || fail "no command line launcher at ${VSCODIUM_CLI}"

# Where the extensions end up: the application's own extensions directory, the
# one VS Code calls "built-in". They travel with the application, which is what
# lets a MacOS user drag the bundle to /Applications and keep them, and what
# keeps them out of an existing `~/.vscode` on the same machine. A user can
# still install a newer version of any of them from the Extensions view; an
# installed version wins over the one shipped here.
BUILTIN_EXTENSIONS_DIR="${RESOURCES_DIR}/app/extensions"

PLAN_FILE="${STAGE_DIR}/extensions-plan.json"

build_bootstrap_vsix() {
  local staging="${STAGE_DIR}/bootstrap"
  rm -rf "${staging}"
  cp -R "${SCRIPT_DIR}/bootstrap" "${staging}"
  cp "${REPO_ROOT}/LICENSE.txt" "${staging}/LICENSE.txt"
  # The bootstrap extension has no version of its own: it is part of the IDE,
  # and saying so makes an installed IDE self-describing in the Extensions view.
  "${PYTHON}" -c "
import json, pathlib, sys
manifest = pathlib.Path(sys.argv[1])
package = json.loads(manifest.read_text(encoding='utf-8'))
package['version'] = sys.argv[2]
manifest.write_text(json.dumps(package, indent=2) + '\n', encoding='utf-8')
" "${staging}/package.json" "${VERSION}"
  (cd "${staging}" && npx --yes @vscode/vsce package --no-dependencies --out "${STAGE_DIR}/partcad-ide-bootstrap.vsix" >/dev/null)
}

if [ "${INSTALL_EXTENSIONS}" = "1" ]; then
  command -v npx >/dev/null 2>&1 || fail "npx is needed to package the extensions; install Node.js"

  if [ -z "${EXTENSION_VSIX}" ]; then
    EXTENSION_VSIX="${REPO_ROOT}/ide/vscode/partcad.vsix"
    if [ ! -f "${EXTENSION_VSIX}" ]; then
      log "==> Building the PartCAD extension (no ${EXTENSION_VSIX} yet)"
      # The same command ".github/workflows/vsix.yml" runs for the package that
      # goes on the release, so the extension inside the IDE and the released one
      # are built the same way.
      #
      # This used to be `nox --session build_package`, because the extension
      # carried a Python language server whose vendored dependencies
      # (`bundled/libs`) only the nox session populated -- and, since those were
      # compiled wheels, it had to run here per platform rather than reuse the
      # released package. The extension is a JSON-RPC client now: no Python, no
      # compiled content, so this is plain npm and the result is
      # platform-independent.
      (cd "${REPO_ROOT}/ide/vscode" && npm ci && npm run vsce-package)
    fi
  fi
  [ -f "${EXTENSION_VSIX}" ] || fail "no PartCAD extension at ${EXTENSION_VSIX}"

  log "==> Packaging the IDE bootstrap extension"
  build_bootstrap_vsix

  log "==> Resolving which extensions to install"
  "${PYTHON}" "${SCRIPT_DIR}/tools/resolve_extensions.py" \
    --repo-root "${REPO_ROOT}" \
    --policy "${SCRIPT_DIR}/extensions.json" \
    --local "OpenVMP.partcad=${EXTENSION_VSIX}" \
    --local "PartCAD.partcad-ide-bootstrap=${STAGE_DIR}/partcad-ide-bootstrap.vsix" \
    --output "${PLAN_FILE}" \
    --explain

  STAGING_EXTENSIONS="${STAGE_DIR}/extensions"
  STAGING_USER_DATA="${STAGE_DIR}/user-data"
  mkdir -p "${STAGING_EXTENSIONS}" "${STAGING_USER_DATA}"

  # The application installs its own extensions: it resolves them against the
  # gallery in its `product.json`, picks the build that matches this platform,
  # and writes the layout it expects to read back. Reimplementing that here is
  # how an IDE ends up with extensions that are present but not loadable.
  run_vscodium() {
    if [ "${OS_NAME}" = "linux" ] && [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then
      xvfb-run -a "${VSCODIUM_CLI}" --extensions-dir "${STAGING_EXTENSIONS}" \
        --user-data-dir "${STAGING_USER_DATA}" "$@"
    else
      "${VSCODIUM_CLI}" --extensions-dir "${STAGING_EXTENSIONS}" \
        --user-data-dir "${STAGING_USER_DATA}" "$@"
    fi
  }

  FAILED_REQUIRED=""
  FAILED_OPTIONAL=""
  # Split on the unit separator rather than on a tab: `read` folds runs of
  # whitespace delimiters together, which silently shifts every field after an
  # empty one -- and `url` and `path` are empty for most entries.
  while IFS=$'\x1f' read -r identifier source url path required; do
    case "${source}" in
    gallery) target="${identifier}" ;;
    local) target="${path}" ;;
    vsix)
      target="${STAGE_DIR}/$(basename "${url}")"
      log "==> Downloading ${url}"
      download "${url}" "${target}" || target=""
      ;;
    *) fail "unknown extension source '${source}'" ;;
    esac

    log "==> Installing ${identifier}"
    if [ -n "${target}" ] && run_vscodium --install-extension "${target}" --force; then
      continue
    fi
    if [ "${required}" = "True" ]; then
      FAILED_REQUIRED="${FAILED_REQUIRED} ${identifier}"
    else
      FAILED_OPTIONAL="${FAILED_OPTIONAL} ${identifier}"
    fi
  done < <("${PYTHON}" -c "
import json, sys
plan = json.load(open(sys.argv[1], encoding='utf-8'))
for entry in plan['install']:
    print('\x1f'.join([entry['id'], entry['source'], entry['url'] or '', entry.get('path', ''), str(entry['required'])]))
" "${PLAN_FILE}")

  [ -z "${FAILED_REQUIRED}" ] || fail "these extensions are required and could not be installed:${FAILED_REQUIRED}"
  if [ -n "${FAILED_OPTIONAL}" ]; then
    warn "these extensions could not be installed and the IDE ships without them:${FAILED_OPTIONAL}
         Each one is a recommendation from .vscode/extensions.json that the gallery does
         not carry. Add it to extensions.json with a \"url\", or record why it is absent."
  fi

  log "==> Moving the extensions into the application"
  mkdir -p "${BUILTIN_EXTENSIONS_DIR}"
  for extension in "${STAGING_EXTENSIONS}"/*/; do
    [ -f "${extension}package.json" ] || continue
    rm -rf "${BUILTIN_EXTENSIONS_DIR:?}/$(basename "${extension}")"
    cp -R "${extension%/}" "${BUILTIN_EXTENSIONS_DIR}/"
  done
fi

###############################################  BRANDING  ###################################################

log "==> Rebranding"
"${PYTHON}" "${SCRIPT_DIR}/tools/brand.py" product \
  --path "${RESOURCES_DIR}/app/product.json" \
  --overlay "${SCRIPT_DIR}/product.overlay.json" \
  --version "${VERSION}"

ICON_DIR="${STAGE_DIR}/icons"
ICONS_BUILT=0
if [ "${BRAND_ICONS}" = "1" ]; then
  if "${PYTHON}" "${SCRIPT_DIR}/tools/make_icons.py" \
    --svg "${REPO_ROOT}/ide/vscode/resources/logo.svg" \
    --output-dir "${ICON_DIR}"; then
    ICONS_BUILT=1
  else
    warn "could not render the icons; the IDE keeps VSCodium's.
         Install the renderers with: ${PYTHON} -m pip install cairosvg pillow"
  fi
fi

if [ "${ICONS_BUILT}" = "1" ]; then
  # The window and launcher icon, on the two platforms that read it from a file.
  if [ -f "${RESOURCES_DIR}/app/resources/linux/code.png" ]; then
    cp "${ICON_DIR}/partcad-ide.png" "${RESOURCES_DIR}/app/resources/linux/code.png"
  fi
  if [ "${OS_NAME}" = "macos" ]; then
    cp "${ICON_DIR}/partcad-ide.icns" "${RESOURCES_DIR}/partcad-ide.icns"
  else
    # Beside the executable, where `install.sh` picks it up for the desktop
    # entry it writes.
    cp "${ICON_DIR}/partcad-ide.png" "${APP_ROOT}/partcad-ide.png"
  fi
  if [ "${OS_NAME}" = "windows" ]; then
    cp "${ICON_DIR}/partcad-ide.ico" "${APP_ROOT}/partcad-ide.ico"
  fi
fi

# Rename the executable, so that the process, the task bar and `ps` all say
# PartCAD IDE. Done after the extensions are installed, because installing them
# runs the launcher that this breaks until the shim below is rewritten.
case "${OS_NAME}" in
linux | windows)
  [ -f "${APP_ROOT}/codium${EXE_SUFFIX}" ] || [ -f "${APP_ROOT}/VSCodium${EXE_SUFFIX}" ] ||
    fail "no VSCodium executable in ${APP_ROOT}; the layout changed upstream"
  for candidate in "codium" "VSCodium"; do
    if [ -f "${APP_ROOT}/${candidate}${EXE_SUFFIX}" ]; then
      mv "${APP_ROOT}/${candidate}${EXE_SUFFIX}" "${APP_ROOT}/partcad-ide${EXE_SUFFIX}"
      break
    fi
  done
  EXECUTABLE="${APP_ROOT}/partcad-ide${EXE_SUFFIX}"
  ;;
macos)
  # Nothing to rename: the MacOS launcher finds the executable through the
  # bundle, whose name comes from Info.plist and whose directory is renamed as a
  # whole further down.
  BUNDLE_EXECUTABLE="$("${PYTHON}" -c "
import plistlib, sys
with open(sys.argv[1], 'rb') as handle:
    print(plistlib.load(handle)['CFBundleExecutable'])
" "${APP_ROOT}/Contents/Info.plist")"
  EXECUTABLE="${APP_ROOT}/Contents/MacOS/${BUNDLE_EXECUTABLE}"
  ;;
esac

for shim in "${LAUNCHER_DIR}"/codium*; do
  [ -f "${shim}" ] || continue
  suffix="${shim##*/codium}"
  target="${LAUNCHER_DIR}/partcad-ide${suffix}"
  mv "${shim}" "${target}"
  "${PYTHON}" "${SCRIPT_DIR}/tools/brand.py" shim --path "${target}" \
    --from "codium" --to "partcad-ide" --allow-missing
  "${PYTHON}" "${SCRIPT_DIR}/tools/brand.py" shim --path "${target}" \
    --from "VSCodium.exe" --to "partcad-ide.exe" --allow-missing
done

if [ "${OS_NAME}" = "windows" ]; then
  LAUNCHER="${LAUNCHER_DIR}/partcad-ide.cmd"
else
  LAUNCHER="${LAUNCHER_DIR}/partcad-ide"
fi
[ -f "${LAUNCHER}" ] || fail "the command line launcher was not renamed; nothing at ${LAUNCHER}"

##############################################  THE TOOLS  ###################################################

if [ -n "${CLI_BUNDLE}" ]; then
  [ -d "${CLI_BUNDLE}" ] || fail "no PartCAD command line bundle at ${CLI_BUNDLE}"
  [ -f "${CLI_BUNDLE}/partcad-json-rpc${EXE_SUFFIX}" ] ||
    fail "${CLI_BUNDLE} holds no partcad-json-rpc${EXE_SUFFIX}: it is not a PartCAD bundle.
       Build one with dev-tools/pyinstaller/build.sh --no-archive."
  log "==> Embedding the PartCAD command line tools"
  # Beside `app/`, not inside it: `resources/app` is the editor, and a 900MB
  # payload inside it is walked by every extension scan. The bootstrap extension
  # finds it here, relative to `appRoot`, on all three platforms.
  rm -rf "${RESOURCES_DIR}/partcad-cli"
  cp -R "${CLI_BUNDLE}" "${RESOURCES_DIR}/partcad-cli"
else
  warn "built without the PartCAD command line tools (--with-cli-bundle was not given).
         The IDE will offer to download them the first time it is used."
fi

#############################################  THE BUNDLE  ###################################################

mkdir -p "${OUTPUT_DIR}"
if [ "${OS_NAME}" = "macos" ]; then
  APP_NAME="PartCAD IDE.app"
  PLIST_ARGS=(
    --path "${APP_ROOT}/Contents/Info.plist"
    --name "PartCAD IDE"
    --identifier "org.partcad.ide"
    --version "${VERSION}"
  )
  if [ "${ICONS_BUILT}" = "1" ]; then
    PLIST_ARGS+=(--icon "partcad-ide")
  fi
  "${PYTHON}" "${SCRIPT_DIR}/tools/brand.py" plist "${PLIST_ARGS[@]}"
else
  APP_NAME="partcad-ide"
fi

rm -rf "${OUTPUT_DIR:?}/${APP_NAME}"
mv "${APP_ROOT}" "${OUTPUT_DIR}/${APP_NAME}"
APP_ROOT="${OUTPUT_DIR}/${APP_NAME}"
if [ "${OS_NAME}" = "macos" ]; then
  RESOURCES_DIR="${APP_ROOT}/Contents/Resources"
  LAUNCHER="${RESOURCES_DIR}/app/bin/partcad-ide"
  EXECUTABLE="${APP_ROOT}/Contents/MacOS/${BUNDLE_EXECUTABLE}"
else
  RESOURCES_DIR="${APP_ROOT}/resources"
  EXECUTABLE="${APP_ROOT}/partcad-ide${EXE_SUFFIX}"
  if [ "${OS_NAME}" = "windows" ]; then
    LAUNCHER="${APP_ROOT}/bin/partcad-ide.cmd"
  else
    LAUNCHER="${APP_ROOT}/bin/partcad-ide"
  fi
fi

if [ "${OS_NAME}" = "macos" ]; then
  # Everything above edited files inside a signed bundle, which invalidates the
  # signature: MacOS then refuses to open the application at all. Ad-hoc signing
  # makes it launchable again. It is not a Developer ID signature and does not
  # make the application notarized -- `install.sh` clears the quarantine flag
  # for a user who installs it, and README.md says what to do otherwise.
  if command -v codesign >/dev/null 2>&1; then
    log "==> Signing the application bundle (ad-hoc)"
    codesign --force --deep --sign - "${APP_ROOT}" >/dev/null ||
      fail "ad-hoc signing failed; MacOS will refuse to open this bundle"
  else
    fail "no codesign; MacOS will refuse to open this bundle"
  fi
fi

if [ "${OS_NAME}" = "windows" ] && [ "${ICONS_BUILT}" = "1" ]; then
  if command -v rcedit >/dev/null 2>&1; then
    rcedit "${EXECUTABLE}" --set-icon "${APP_ROOT}/partcad-ide.ico" ||
      warn "could not set the executable's icon"
  else
    warn "no rcedit on PATH; partcad-ide.exe keeps VSCodium's icon.
         Install it with: npm install -g rcedit"
  fi
fi

##############################################  SMOKE TEST  ##################################################

log "==> Checking the application starts"
IDE_VERSION="$("${LAUNCHER}" --version | head -n 1)" ||
  fail "${LAUNCHER} does not run"
log "    ${LAUNCHER} --version -> ${IDE_VERSION}"

if [ "${INSTALL_EXTENSIONS}" = "1" ]; then
  log "==> Verifying the bundle"
  VERIFY_ARGS=(
    --resources "${RESOURCES_DIR}"
    --plan "${PLAN_FILE}"
    --executable "${EXECUTABLE}"
    --launcher "${LAUNCHER}"
  )
  if [ -n "${CLI_BUNDLE}" ]; then
    VERIFY_ARGS+=(--expect-tools)
  fi
  "${PYTHON}" "${SCRIPT_DIR}/tools/verify_bundle.py" "${VERIFY_ARGS[@]}"
fi

##############################################  THE ARCHIVE  #################################################

# Write "<sha256>  <name>" beside the file, the format `sha256sum -c` reads and
# the one `install.sh` verifies with.
checksum() {
  (cd "$(dirname "$1")" && "${PYTHON}" -c "
import hashlib, pathlib, sys
name = sys.argv[1]
digest = hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()
pathlib.Path(name + '.sha256').write_text(f'{digest}  {name}\n', encoding='utf-8')
print(digest)
" "$(basename "$1")")
}

PRODUCED=""

if [ "${CREATE_ARCHIVE}" = "1" ]; then
  ARCHIVE="${OUTPUT_DIR}/partcad-ide-${VERSION}-${PLATFORM}.${ARCHIVE_EXT}"
  log "==> Packing ${ARCHIVE}"
  rm -f "${ARCHIVE}" "${ARCHIVE}.sha256"
  case "${ARCHIVE_EXT}" in
  tar.gz) tar -czf "${ARCHIVE}" -C "${OUTPUT_DIR}" "${APP_NAME}" ;;
  zip) (cd "${OUTPUT_DIR}" && zip -qry "$(basename "${ARCHIVE}")" "${APP_NAME}") ;;
  esac
  checksum "${ARCHIVE}"
  PRODUCED="${PRODUCED} $(basename "${ARCHIVE}")"

  if [ "${OS_NAME}" = "macos" ] && [ "${CREATE_DMG}" = "1" ]; then
    DMG="${OUTPUT_DIR}/partcad-ide-${VERSION}-${PLATFORM}.dmg"
    log "==> Packing ${DMG}"
    rm -f "${DMG}" "${DMG}.sha256"
    DMG_STAGE="${STAGE_DIR}/dmg"
    rm -rf "${DMG_STAGE}"
    mkdir -p "${DMG_STAGE}"
    cp -R "${APP_ROOT}" "${DMG_STAGE}/"
    # The /Applications alias is the "drag this there" half of the window every
    # MacOS user has seen.
    ln -s /Applications "${DMG_STAGE}/Applications"
    hdiutil create -volname "PartCAD IDE" -srcfolder "${DMG_STAGE}" -ov -quiet -format UDZO "${DMG}"
    checksum "${DMG}"
    PRODUCED="${PRODUCED} $(basename "${DMG}")"
  fi
fi

#############################################  THE INSTALLER  ################################################

# Windows has no equivalent of `install.sh`: a .zip to unpack leaves no Start
# menu entry, nothing on PATH and nothing to uninstall. This is that, built with
# Inno Setup, which is what the editors this one is made from use as well.
if [ "${OS_NAME}" = "windows" ] && [ "${CREATE_INSTALLER}" = "1" ]; then
  ISCC=""
  for candidate in \
    "iscc" \
    "ISCC.exe" \
    "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "/c/Program Files/Inno Setup 6/ISCC.exe"; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      ISCC="${candidate}"
      break
    fi
  done

  if [ -z "${ISCC}" ]; then
    warn "no Inno Setup compiler (ISCC) found; built the .zip but no installer.
         Install it from https://jrsoftware.org/isdl.php, or with:
           choco install innosetup
         Inno Setup 6.3 or newer is needed for the architecture directives."
  else
    INSTALLER_NAME="partcad-ide-${VERSION}-${PLATFORM}-setup"
    INSTALLER="${OUTPUT_DIR}/${INSTALLER_NAME}.exe"
    log "==> Building ${INSTALLER} with ${ISCC}"
    rm -f "${INSTALLER}" "${INSTALLER}.sha256"
    # MSYS2_ARG_CONV_EXCL stops Git Bash from rewriting the /D and /O switches
    # into paths on the way to a native Windows program, which is what turns
    # "/O<dir>" into "O:\<dir>" and the build into a puzzle.
    ISCC_ARGS=("/Qp" "/DVersion=${VERSION}")
    if [ "${ICONS_BUILT}" = "1" ] && [ -f "${APP_ROOT}/partcad-ide.ico" ]; then
      ISCC_ARGS+=("/DHaveIcon=1")
    fi
    ISCC_ARGS+=(
      "/O$(cygpath -w "${OUTPUT_DIR}")"
      "/F${INSTALLER_NAME}"
      "$(cygpath -w "${SCRIPT_DIR}/installer/partcad-ide.iss")"
    )
    MSYS2_ARG_CONV_EXCL="*" "${ISCC}" "${ISCC_ARGS[@]}"
    [ -f "${INSTALLER}" ] || fail "Inno Setup reported success but produced no ${INSTALLER}"
    checksum "${INSTALLER}"
    PRODUCED="${PRODUCED} $(basename "${INSTALLER}")"
  fi
fi

log ""
log "The PartCAD IDE ${VERSION} for ${PLATFORM} is in ${OUTPUT_DIR}:"
log "  ${APP_NAME}"
for produced in ${PRODUCED}; do
  log "  ${produced}"
done
