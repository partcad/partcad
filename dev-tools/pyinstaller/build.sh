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
#   dev-tools/pyinstaller/build.sh --platform=ubuntu-22.04-x86_64   # name it explicitly
#
# The environment variable PYTHON selects the interpreter to freeze (default
# `python3`); the bundle embeds that exact interpreter, so it decides the
# Python version users end up running.
#
# The environment variable PLATFORM (or --platform=) overrides the platform id
# the archive is named after. It is detected from this machine when unset; CI
# passes it, because the runner image knows its own OS version and this script
# would have to guess it back out of the kernel.
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
OPENSCAD_STAGE_DIR="${REPO_ROOT}/build/openscad"
PYTHON="${PYTHON:-python3}"

# The OpenSCAD the bundle carries. Pinned rather than tracking the latest, so a
# rebuild of a given PartCAD version produces the same bundle, and matching the
# version `partcad.healthcheck.openscad` installs on Windows hosts.
OPENSCAD_VERSION="2021.01"
# The staged payload is keyed by version, so that bumping OPENSCAD_VERSION and
# rebuilding in a tree that still holds an old `build/` fetches the new version
# rather than silently reusing the stale one (`build/` is not wiped between
# builds, and CI aside, nobody wipes it by hand). Stale siblings are harmless:
# `build/` is gitignored, and only the matching directory is ever read.
OPENSCAD_PAYLOAD_DIR="${OPENSCAD_STAGE_DIR}/payload-${OPENSCAD_VERSION}"

INSTALL_DEPENDENCIES=1
CREATE_ARCHIVE=1
PLATFORM="${PLATFORM:-}"
for arg in "$@"; do
  case "${arg}" in
  --no-install) INSTALL_DEPENDENCIES=0 ;;
  --no-archive) CREATE_ARCHIVE=0 ;;
  --platform=*) PLATFORM="${arg#*=}" ;;
  -h | --help)
    sed -n '7,31p' "${BASH_SOURCE[0]}"
    exit 0
    ;;
  *)
    echo "error: unknown option '${arg}'" >&2
    exit 2
    ;;
  esac
done

################################################  PLATFORM  ##################################################

# A frozen bundle is only portable across systems at least as new as the one it
# was built on: it links against the C library and the system frameworks of that
# machine. So a bundle is not "for Linux", it is for the OS *version* it was
# built on and everything newer -- which is why the archive name carries that
# version, and why there is one build per supported OS version rather than one
# per operating system.
#
# The platform id is `<os>-<os-version>-<arch>`, and for the builds CI produces
# it is exactly the runner image label (minus the `-arm` suffix) plus the
# architecture:
#
#   ubuntu-22.04-x86_64   ubuntu-22.04-arm64    macos-15-arm64    windows-2022-x86_64
#   ubuntu-24.04-x86_64   ubuntu-24.04-arm64    macos-26-arm64    windows-2025-x86_64
#
# `install.sh` resolves the same ids from the machine it runs on. Keep the two
# in sync: the list above, the matrix in ".github/workflows/build-standalone.yml",
# and LINUX_BUILDS/MACOS_BUILDS in "install.sh".
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

# Only used when PLATFORM was not passed in. CI always passes it: the runner
# image label is the authoritative answer to "which OS version is this", and
# recovering it from the running system is guesswork on Windows in particular.
detect_os_release() {
  case "${OS_NAME}" in
  linux)
    # Every distribution ships this file; `ID`/`VERSION_ID` are the two fields
    # that are always present. A rolling distribution with no VERSION_ID gets
    # its ID alone, which still names the build uniquely enough for a local one.
    if [ -r /etc/os-release ]; then
      # shellcheck disable=SC1091
      . /etc/os-release
      if [ -n "${VERSION_ID:-}" ]; then
        echo "${ID}-${VERSION_ID}"
      else
        echo "${ID}"
      fi
      return 0
    fi
    echo "error: /etc/os-release is missing, pass --platform=<id>" >&2
    return 1
    ;;
  macos)
    # The major version is the compatibility boundary; the point release is not.
    echo "macos-$(sw_vers -productVersion | cut -d. -f1)"
    ;;
  windows)
    # Git Bash reports the NT build number in `uname -s`, e.g.
    # "MINGW64_NT-10.0-20348". That number identifies the Windows release, but
    # only through a table -- so map the ones CI builds on and ask for
    # --platform for anything else, rather than inventing a name.
    case "$(uname -s)" in
    *-20348) echo "windows-2022" ;;
    *-26100) echo "windows-2025" ;;
    *)
      echo "error: cannot name this Windows version from '$(uname -s)'," >&2
      echo "       pass --platform=windows-<year>-${ARCH_NAME}" >&2
      return 1
      ;;
    esac
    ;;
  esac
}

if [ -z "${PLATFORM}" ]; then
  PLATFORM="$(detect_os_release)-${ARCH_NAME}"
fi

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

# setuptools 82 removed `pkg_resources` outright, and PyInstaller's
# `pyi_rth_pkgres` runtime hook still expects it: the bundle then aborts at
# start-up with "module 'pkg_resources' has no attribute 'NullProvider'".
# Passed to every install below, because installing PartCAD is otherwise free to
# pull the newest setuptools back in. Drop the bound once PyInstaller ships a
# hook that copes.
SETUPTOOLS_BOUND="setuptools<82"

if [ "${INSTALL_DEPENDENCIES}" = "1" ]; then
  echo "==> Installing build dependencies"
  "${PYTHON}" -m pip install --upgrade pip wheel "${SETUPTOOLS_BOUND}"
  # PyInstaller only learned about Python 3.14 in 6.15; older releases cap
  # themselves at "<3.14" and would refuse to install on the interpreter the
  # bundle is built with.
  "${PYTHON}" -m pip install "pyinstaller>=6.15" "${SETUPTOOLS_BOUND}"

  # `partcad-cli`, `partcad-service-json-rpc`, and `partcad-utils` each declare
  # their license by a path inside their own directory, but the file itself only
  # exists in the repository root. The wheel build in "deploy.yml" copies it the
  # same way.
  cp "${REPO_ROOT}/LICENSE.txt" "${REPO_ROOT}/partcad-cli/"
  cp "${REPO_ROOT}/LICENSE.txt" "${REPO_ROOT}/partcad-service-json-rpc/"
  cp "${REPO_ROOT}/LICENSE.txt" "${REPO_ROOT}/partcad-utils/"

  echo "==> Installing PartCAD from this checkout"
  # The shared partcad-utils is installed first: partcad (and the CLI/service)
  # pin it, and it is not on PyPI, so it must come from this checkout.
  "${PYTHON}" -m pip install "${REPO_ROOT}/partcad-utils" "${SETUPTOOLS_BOUND}"
  # A frozen bundle cannot be extended with pip afterwards, so the optional
  # extras that the wheels leave to the user are all built in.
  "${PYTHON}" -m pip install "${REPO_ROOT}/partcad[lint]" "${SETUPTOOLS_BOUND}"
  # The CAD kernel is NOT a dependency of the 'partcad' wheel - the core runs all
  # CAD in sandboxes. The standalone bundle, however, freezes it in so that 'pc'
  # works on a machine with no Python: 'show'/'pc inspect' (via ocp_vscode) need
  # OCP in-process, and the "imported by name" check below refuses to build the
  # bundle without OCP/build123d/ocp_vscode. Pinned to the sandbox versions (see
  # partcad/src/partcad/sandbox_versions.py).
  # TODO(clairbee): drop this CAD install once the OCP CAD Viewer (ocp_vscode) is
  # no longer a dependency - the bundle would then need no in-process CAD either.
  "${PYTHON}" -m pip install \
    "cadquery-ocp==7.9.3.1.1" "build123d==0.11.1" "ocpsvg==0.6.0" "${SETUPTOOLS_BOUND}"
  # The JSON-RPC service (the bundle's third executable) is installed before
  # partcad-cli: the CLI pins partcad-service-json-rpc, which is not on PyPI, so
  # it must be satisfied from this checkout. Both pins (partcad, and the service)
  # resolve to the local builds this way.
  "${PYTHON}" -m pip install "${REPO_ROOT}/partcad-service-json-rpc" "${SETUPTOOLS_BOUND}"
  "${PYTHON}" -m pip install "${REPO_ROOT}/partcad-cli" "${SETUPTOOLS_BOUND}"
fi

###############################################  OPENSCAD  ###################################################

# The bundle carries OpenSCAD, so `pc` can build .scad parts on a machine that
# has none, and prefers it over any copy installed on the host (see
# `partcad.healthcheck.openscad`).
#
# Linux takes the upstream AppImage but ships it *extracted*: running an
# AppImage as an image needs FUSE, which a minimal host may not have, while the
# extracted tree runs anywhere. Note that the AppImage is not fully
# self-contained -- it resolves libGL, libX11, libxcb, fontconfig, freetype,
# glib and harfbuzz from the host -- so on a stripped-down Linux system the
# bundled OpenSCAD still needs those present. Windows takes the upstream portable
# build, a single statically linked executable that needs nothing at all.
#
# Linux arm64 carries none either: upstream publishes the 2021.01 AppImage for
# x86_64 only, and running an x86_64 AppImage under emulation is not something
# a bundle should be quietly requiring. `pc` there uses the host's OpenSCAD,
# exactly as the wheels do.
#
# macOS is deliberately excluded for the same shape of reason. The 2021.01
# release predates Apple Silicon and ships an x86_64-only .dmg, which on the
# arm64 bundle would require Rosetta 2 -- absent from a clean machine, and not
# something an installer should be quietly requiring. The current development snapshots may well be
# universal binaries, but they are snapshots, and their architecture has not
# been confirmed. Until that is settled, `pc` on macOS uses the host's
# OpenSCAD, exactly as the wheels do.
stage_openscad() {
  local artifact download_dir payload_dir entry_point
  download_dir="${OPENSCAD_STAGE_DIR}/download-${OPENSCAD_VERSION}"
  payload_dir="${OPENSCAD_PAYLOAD_DIR}"

  # Keyed on the operating system and architecture rather than on PLATFORM,
  # which now also carries the OS version: which OpenSCAD to fetch does not
  # depend on whether this is Ubuntu 22.04 or 24.04.
  case "${OS_NAME}-${ARCH_NAME}" in
  linux-x86_64)
    artifact="OpenSCAD-${OPENSCAD_VERSION}-x86_64.AppImage"
    entry_point="${payload_dir}/AppRun"
    ;;
  windows-x86_64)
    artifact="OpenSCAD-${OPENSCAD_VERSION}-x86-64.zip"
    entry_point="${payload_dir}/openscad.exe"
    ;;
  *)
    echo "==> Not bundling OpenSCAD on ${PLATFORM} (see the comment in build.sh)"
    rm -rf "${payload_dir}"
    return 0
    ;;
  esac

  if [ -e "${entry_point}" ]; then
    echo "==> OpenSCAD ${OPENSCAD_VERSION} already staged"
    return 0
  fi

  echo "==> Fetching OpenSCAD ${OPENSCAD_VERSION} for ${PLATFORM}"
  rm -rf "${payload_dir}"
  mkdir -p "${download_dir}" "${payload_dir}"

  # Fetched and verified with the Python this script already depends on, rather
  # than with curl and sha256sum, whose presence and flags differ across the
  # three platforms this runs on.
  "${PYTHON}" - "https://files.openscad.org/${artifact}" "${download_dir}/${artifact}" <<'FETCH'
import sys
import urllib.request

for url, destination in ((sys.argv[1], sys.argv[2]), (sys.argv[1] + ".sha256", sys.argv[2] + ".sha256")):
    urllib.request.urlretrieve(url, destination)
FETCH

  "${PYTHON}" - "${download_dir}/${artifact}" <<'VERIFY'
import hashlib
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
# Published as "<hash>  releases/<name>": take the hash, ignore the path, which
# names the location on the upstream server rather than the local file.
expected = pathlib.Path(str(archive) + ".sha256").read_text().split()[0]
actual = hashlib.sha256(archive.read_bytes()).hexdigest()
if actual != expected:
    sys.exit(f"error: checksum mismatch for {archive.name}: expected {expected}, got {actual}")
print(f"    checksum verified: {archive.name}")
VERIFY

  case "${artifact}" in
  *.AppImage)
    chmod +x "${download_dir}/${artifact}"
    # Extraction writes "squashfs-root" into the working directory.
    (cd "${download_dir}" && "./${artifact}" --appimage-extract >/dev/null)
    mv "${download_dir}/squashfs-root"/* "${payload_dir}/"
    mv "${download_dir}/squashfs-root"/.[!.]* "${payload_dir}/" 2>/dev/null || true
    rm -rf "${download_dir}/squashfs-root"
    ;;
  *.zip)
    "${PYTHON}" -m zipfile -e "${download_dir}/${artifact}" "${download_dir}/unpacked"
    # The zip holds a single "openscad-<version>" directory; the executable
    # needs its sibling data directories, so the contents move up together.
    mv "${download_dir}/unpacked/openscad-${OPENSCAD_VERSION}"/* "${payload_dir}/"
    rm -rf "${download_dir}/unpacked"
    ;;
  esac

  [ -e "${entry_point}" ] || {
    echo "error: OpenSCAD staged but '${entry_point}' is missing" >&2
    exit 1
  }
  echo "    staged $(du -sh "${payload_dir}" | cut -f1) in ${payload_dir}"
}

stage_openscad

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
    "ocp_vscode": "`pc inspect`",
    "ruff.__main__": "`pc lint` of Python files",
}

# Python 3.14 has zstd in the standard library as 'compression.zstd'; below
# that PartCAD reads and writes its compressed BREP payloads through this
# backport of the same module, and a bundle frozen without it cannot decode
# what a sandbox hands back.
if sys.version_info < (3, 14):
    REQUIRED["backports.zstd"] = "the BREP payloads of the wrapper protocol"

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

# The other way this build environment can produce a bundle that looks complete
# and is not: on Apple arm64, `_cffi_backend` has to be the PyPI build.
#
# `pygit2` reads the libgit2 config search path through
# `git_libgit2_opts(GIT_OPT_GET_SEARCH_PATH, level, git_buf *)`, a variadic C
# call that cffi cannot wrap statically and so dispatches at run time through
# `_cffi_backend`/libffi. Apple arm64 passes variadic arguments on the stack
# rather than in registers, and the conda-forge cffi 2.x build mis-marshals them
# there: libgit2 is handed a garbage pointer to write through and the process
# segfaults. The PyPI wheel links Apple's system libffi and marshals them
# correctly, which is why the wheels are unaffected. Distinguishing the two is
# exactly this: the PyPI build loads '/usr/lib/libffi.dylib', the conda-forge
# build loads '@rpath/libffi.8.dylib' from its own prefix.
#
# CI builds with `actions/setup-python`, so it always gets the PyPI wheel. A
# developer building on their own Mac is the exposed case: PartCAD needs conda
# for the CAD sandbox, so a conda `python3` is usually first on PATH, its cffi
# already satisfies `pygit2`'s floor (so pip leaves it in place), and PyInstaller
# then freezes both that `_cffi_backend` and the conda `libffi.8.dylib` beside
# it. The bundle's own CI cannot catch this: the crashing path only runs when a
# clone fails to authenticate and PartCAD retries it with the ambient git config
# ignored (`_clone_ignoring_ambient_config` in `partcad/project_factory_git.py`),
# which no anonymous clone of a public repository reaches. It would ship, and
# segfault for users only.
if [ "${OS_NAME}-${ARCH_NAME}" = "macos-arm64" ]; then
  echo "==> Checking that _cffi_backend is the PyPI build"
  # Read with macholib rather than `otool`, so this needs no Xcode command line
  # tools; PyInstaller depends on macholib, so it is already installed.
  "${PYTHON}" - <<'CFFI_PROVENANCE'
import _cffi_backend
from macholib.MachO import MachO
from macholib.mach_o import LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB

SYSTEM_LIBFFI = "/usr/lib/libffi.dylib"

loaded = []
for header in MachO(_cffi_backend.__file__).headers:
    for load_command, _command, data in header.commands:
        if load_command.cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB):
            loaded.append(data.decode("utf-8").rstrip("\0"))

if SYSTEM_LIBFFI not in loaded:
    print(f"error: '{_cffi_backend.__file__}'")
    print(f"       does not load {SYSTEM_LIBFFI}, it loads:")
    print("\n".join(f"         {name}" for name in loaded))
    print()
    print("       This is not the PyPI cffi wheel. A conda-forge build mis-marshals")
    print("       variadic arguments on Apple arm64, which makes pygit2 segfault when")
    print("       PartCAD retries a clone with the ambient git config ignored -- and")
    print("       freezing it here would ship that crash to every user of the bundle.")
    print()
    print("       Build from a non-conda interpreter, or force the PyPI wheel into")
    print("       this environment:")
    print()
    print("         python -m pip install --upgrade --force-reinstall --no-deps \\")
    print("             --only-binary=:all: cffi")
    raise SystemExit(1)

print(f"    {_cffi_backend.__file__} loads {SYSTEM_LIBFFI}")
CFFI_PROVENANCE
fi

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
# `sys._MEIPASS`, which is where `partcad.healthcheck.openscad` looks for the payload.
OPENSCAD_BUNDLED_DIR="${BUNDLE_DIR}/_internal/openscad"

# OpenSCAD is copied in after the freeze rather than declared in the spec.
# PyInstaller reclassifies shared libraries found among data files as binaries
# and collects them into the top level of the bundle, which would put
# OpenSCAD's Qt, ICU and glib beside the ones Python needs -- on the frozen
# application's own library search path, and duplicated, at ~100MB. Copying the
# tree in here keeps OpenSCAD's libraries where only OpenSCAD will find them.
# `cp -a` also carries the executable bits over, which the tar and the zip then
# preserve; PyInstaller would have dropped them.
if [ -d "${OPENSCAD_PAYLOAD_DIR}" ]; then
  echo "==> Installing the bundled OpenSCAD"
  rm -rf "${OPENSCAD_BUNDLED_DIR}"
  cp -a "${OPENSCAD_PAYLOAD_DIR}" "${OPENSCAD_BUNDLED_DIR}"
fi

echo "==> Smoke testing the bundle"
# Run from a directory that is not the checkout: a bundle that accidentally
# depends on the source tree still works when started next to it.
SMOKE_DIR="$(mktemp -d)"
trap 'rm -rf "${SMOKE_DIR}"' EXIT
(cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/pc${EXE_SUFFIX}" version)
(cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/partcad${EXE_SUFFIX}" --help >/dev/null)
(cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/partcad-json-rpc${EXE_SUFFIX}" --version >/dev/null)

if [ -d "${OPENSCAD_BUNDLED_DIR}" ]; then
  # First that the payload itself runs, and that it is the version we pinned:
  # this catches a data file that shipped without its executable bit, an
  # AppImage tree that lost a piece on the way in, and a stale payload left in
  # `build/` from a different OPENSCAD_VERSION. OpenSCAD prints its version to
  # stderr.
  if [ "${OS_NAME}" = "windows" ]; then
    openscad_version_output="$(cd "${SMOKE_DIR}" && "${OPENSCAD_BUNDLED_DIR}/openscad.exe" --version 2>&1)"
  else
    openscad_version_output="$(cd "${SMOKE_DIR}" && "${OPENSCAD_BUNDLED_DIR}/AppRun" --version 2>&1)"
  fi
  echo "    ${openscad_version_output}"
  case "${openscad_version_output}" in
  *"OpenSCAD version ${OPENSCAD_VERSION}"*) ;;
  *)
    echo "error: bundled OpenSCAD is not ${OPENSCAD_VERSION}: '${openscad_version_output}'" >&2
    exit 1
    ;;
  esac

  # Then that `pc` resolves an OpenSCAD at all. Note what this does and does not
  # prove: the health check reports only that `partcad.healthcheck.openscad` found one, so
  # it demonstrates the bundled copy was used only on a machine that has no
  # OpenSCAD of its own, which is why the host is reported alongside. That the
  # bundled copy *wins* over a host one is pinned down by the unit tests, where
  # both can be made to exist on demand.
  echo "    host openscad: $(command -v openscad || echo "none, so the check below can only pass via the bundle")"
  (cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/pc${EXE_SUFFIX}" --no-ansi healthcheck --filters openscad 2>&1) |
    tee "${SMOKE_DIR}/healthcheck.log"
  grep -q "OpenSCAD: Passed" "${SMOKE_DIR}/healthcheck.log" || {
    echo "error: PartCAD did not resolve an OpenSCAD executable" >&2
    exit 1
  }
fi

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
