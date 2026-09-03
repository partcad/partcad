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
CONDA_STAGE_DIR="${REPO_ROOT}/build/conda"
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

# The conda the bundle carries, as the tag of a `micromamba-releases` release --
# "<micromamba version>-<build>", where `micromamba --version` prints only the
# first half. Pinned rather than tracking "latest" for the same reason OpenSCAD
# is: a rebuild of a given PartCAD version has to produce the same bundle.
MICROMAMBA_VERSION="2.9.0-0"
# Keyed by version like the OpenSCAD payload, so a bump refetches rather than
# silently reusing whatever an old `build/` still holds.
CONDA_PAYLOAD_DIR="${CONDA_STAGE_DIR}/payload-${MICROMAMBA_VERSION}"

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
# it is exactly the runner image label (minus the `-arm` or `-intel` suffix) plus
# the architecture -- the macOS labels are not symmetric, `macos-15` being the
# Apple silicon image and `macos-15-intel` the x86_64 one of the same release:
#
#   ubuntu-22.04-x86_64   ubuntu-22.04-arm64    macos-15-arm64    windows-2022-x86_64
#   ubuntu-24.04-x86_64   ubuntu-24.04-arm64    macos-15-x86_64
#
# macOS is one build per architecture rather than one per OS version: both are
# frozen on macOS 15 and cover macOS 15 and 26 between them. CI installs each of
# them on both releases rather than assuming that.
#
# Which of these a release carries is published with it, as `platforms.json`;
# `install.sh` and the other clients read that rather than keeping a list. The
# matrix in ".github/workflows/build-standalone.yml" is where the list lives.
# Windows is one build on purpose -- see the note beside that matrix.
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
  # xz rather than gzip. The bundle is native code and an unpacked OpenSCAD,
  # neither of which gzip does well on: measured on a Linux x86_64 build, xz -6
  # takes the download from 78MB to 57MB for a few seconds more at either end.
  # Every consumer of this name reads the extension from one
  # place of its own (`install.sh`, `partcad_client.selfupdate`,
  # `provision.ts`, the FreeCAD addon's `provision.py`); all four say "tar.xz"
  # and unpack by content rather than by name, so there is no format to agree
  # on beyond the file name itself.
  #
  # Windows stays a zip: it is what a machine with no tar can open, and the
  # portable OpenSCAD in it is already compressed.
  ARCHIVE_EXT="tar.xz"
  EXE_SUFFIX=""
fi

VERSION="$("${PYTHON}" -c "
import re, pathlib
source = pathlib.Path('${REPO_ROOT}/src/partcad/__init__.py').read_text()
print(re.search(r'__version__: str = \"([^\"]+)\"', source).group(1))
")"

echo "==> Building PartCAD ${VERSION} for ${PLATFORM} with $("${PYTHON}" --version)"

##############################################  DEPENDENCIES  ################################################

# There used to be a "setuptools<82" bound on every install below. setuptools 82
# removed `pkg_resources`, PyInstaller's `pyi_rth_pkgres` runtime hook expects it,
# and a bundle built without it aborted at start-up with "module 'pkg_resources'
# has no attribute 'NullProvider'".
#
# It is gone because the hook is: PyInstaller adds `pyi_rth_pkgres` only when
# `pkg_resources` is in the module graph, and "partcad.spec" now excludes it
# along with the rest of setuptools -- nothing in PartCAD imports either, and the
# two dependencies that reach for `pkg_resources` both do it inside
# `try: ... except ImportError`. A bundle frozen against setuptools 8x builds and
# runs.

if [ "${INSTALL_DEPENDENCIES}" = "1" ]; then
  echo "==> Installing build dependencies"
  "${PYTHON}" -m pip install --upgrade pip wheel
  # PyInstaller only learned about Python 3.14 in 6.15; older releases cap
  # themselves at "<3.14" and would refuse to install on the interpreter the
  # bundle is built with.
  "${PYTHON}" -m pip install "pyinstaller>=6.15"

  echo "==> Installing PartCAD from this checkout"
  # One install: `partcad` ships every package the bundle needs and declares all
  # three of its executables. This used to be five installs in dependency order,
  # because each distribution pinned the ones below it at `==` and none of them
  # was on PyPI, so every pin had to be satisfied from this checkout.
  #
  # A frozen bundle cannot be extended with pip afterwards, so the optional
  # extras the wheel leaves to the user are all built in.
  "${PYTHON}" -m pip install "${REPO_ROOT}[lint,aws]"
  #
  # No CAD kernel is installed here, and none is frozen into the bundle.
  #
  # It used to be: 'cadquery-ocp', 'build123d' and 'ocpsvg' were pinned to the
  # sandbox versions and pulled in so that `convert("build123d"/"cadquery")`
  # could hand a caller a live object. That is a *library* API, and this bundle
  # is not importable as a library -- it is three console programs. Every path
  # the programs do reach builds, renders, exports, converts and tessellates in
  # a conda sandbox and carries geometry between them as BREP-byte envelopes the
  # core never opens (see requirements.txt and `Shape._to_envelope`), so the
  # kernel sat in the bundle unimported.
  #
  # It was not cheap to carry. OCP drags in the whole scientific stack through
  # build123d -- scipy, sympy, scikit-learn, numpy, IPython, ezdxf -- and the
  # VTK-enabled OCP drags in VTK on top of that. Measured on Linux x86_64, all
  # of it together was about two thirds of the bundle.
  #
  # What this does *not* change: `pc` still needs conda for any CAD, exactly as
  # the wheel does and exactly as it did before, because that is where the CAD
  # ran either way. `pc healthcheck` reports it.
fi

#############################################  PAYLOAD FETCH  ################################################

# Fetch a URL and the ".sha256" its upstream publishes beside it, and check the
# one against the other. Used for both payloads the bundle carries -- OpenSCAD
# and conda -- so that neither can be staged from a truncated or substituted
# download.
#
# Fetched and verified with the Python this script already depends on, rather
# than with curl and sha256sum, whose presence and flags differ across the three
# platforms this runs on. The two upstreams do not publish the checksum in the
# same shape -- OpenSCAD's reads "<hash>  releases/<name>", micromamba's is the
# bare hash with no trailing newline -- so the first whitespace-separated field
# is what is compared and anything after it ignored.
fetch_and_verify() {
  local url="$1" destination="$2"

  "${PYTHON}" - "${url}" "${destination}" <<'FETCH'
import sys
import urllib.request

for url, destination in ((sys.argv[1], sys.argv[2]), (sys.argv[1] + ".sha256", sys.argv[2] + ".sha256")):
    urllib.request.urlretrieve(url, destination)
FETCH

  "${PYTHON}" - "${destination}" <<'VERIFY'
import hashlib
import pathlib
import sys

artifact = pathlib.Path(sys.argv[1])
expected = pathlib.Path(str(artifact) + ".sha256").read_text().split()[0]
actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
if actual != expected:
    sys.exit(f"error: checksum mismatch for {artifact.name}: expected {expected}, got {actual}")
print(f"    checksum verified: {artifact.name}")
VERIFY
}

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

  fetch_and_verify "https://files.openscad.org/${artifact}" "${download_dir}/${artifact}"

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

################################################  CONDA  #####################################################

# The bundle carries a conda, so that `pc` can build the CAD sandbox on a machine
# that has none.
#
# It did not, and that was the flaw this fixes. PartCAD imports no CAD kernel: it
# provisions a Python environment and runs every CAD script in that, and conda is
# the only sandbox that provisions an *interpreter* along with it. The bundle
# exists so that a machine with no Python can run PartCAD -- and it then asked
# that machine for conda, which the PartCAD IDE discovered by launching the
# daemon out of a bundle on a clean machine and failing.
#
# The `venv` sandbox is not the fallback here that it is for a wheel: a virtual
# environment is built *from* an interpreter, and the machine this artifact is
# for is the one with no Python to build it from (see `partcad_utils.conda`).
#
# What is staged is micromamba: mamba in its single-file, dependency-free build,
# published by the mamba project. mamba because that is the implementation CI
# provisions through Miniforge (`use-mamba: true` in
# `.github/actions/setup-all/action.yml`) and the one `partcad_utils.conda`
# already preferred over conda. Not the Miniforge installer itself, for two
# reasons that both matter here:
#
#   1. A conda *installation* is not relocatable. Its entry points hardcode the
#      prefix they were installed into, and this bundle is unpacked to a path
#      nobody knows at build time -- `~/.local/share/partcad/<version>` for
#      `install.sh`, somewhere else for the extension, the addon and the IDE.
#      One static executable has no prefix to hardcode.
#   2. Miniforge is around 500MB installed, against 12-22MB here. The bundle is
#      ~200MB unpacked precisely because the CAD kernel was taken out of it; a
#      conda distribution would put three times that back.
#
# micromamba also resolves from conda-forge with no configuration at all, which
# is the channel policy the comments in that CI action insist on -- mixing
# Anaconda's `defaults` into a conda-forge environment is what made the macOS
# jobs segfault. A Miniforge install would have had to carry a `.condarc` saying
# the same thing.
#
# Unlike OpenSCAD, there is no platform that goes without: upstream builds
# micromamba for every platform this bundle is built for, and a bundle without a
# conda is the bug. An unmapped platform therefore fails the build rather than
# quietly producing one.
#
# `partcad_utils.conda` is the other half of this: where the payload is looked
# for at run time, and why the host's conda still comes first when there is one.
stage_conda() {
  local artifact download_dir payload_dir entry_point
  download_dir="${CONDA_STAGE_DIR}/download-${MICROMAMBA_VERSION}"
  payload_dir="${CONDA_PAYLOAD_DIR}"

  # Keyed on the operating system and architecture rather than on PLATFORM: one
  # micromamba build serves every version of an operating system, exactly as one
  # OpenSCAD build does.
  case "${OS_NAME}-${ARCH_NAME}" in
  linux-x86_64) artifact="micromamba-linux-64" ;;
  linux-arm64) artifact="micromamba-linux-aarch64" ;;
  macos-x86_64) artifact="micromamba-osx-64" ;;
  macos-arm64) artifact="micromamba-osx-arm64" ;;
  # The release also publishes "micromamba-win-64.exe", byte for byte the same
  # file -- but only the name without the suffix has a ".sha256" beside it, and
  # a payload nobody can verify is not one worth having. The staged copy is
  # renamed to "micromamba.exe" below, which is the name that matters.
  windows-x86_64) artifact="micromamba-win-64" ;;
  *)
    echo "error: no micromamba build is mapped for ${PLATFORM}, and a bundle" >&2
    echo "       without a conda cannot build a CAD sandbox on a host that" >&2
    echo "       has none -- add the mapping rather than shipping without it" >&2
    exit 1
    ;;
  esac

  entry_point="${payload_dir}/micromamba${EXE_SUFFIX}"
  if [ -e "${entry_point}" ]; then
    echo "==> micromamba ${MICROMAMBA_VERSION} already staged"
    return 0
  fi

  echo "==> Fetching micromamba ${MICROMAMBA_VERSION} for ${PLATFORM}"
  rm -rf "${payload_dir}"
  mkdir -p "${download_dir}" "${payload_dir}"

  fetch_and_verify \
    "https://github.com/mamba-org/micromamba-releases/releases/download/${MICROMAMBA_VERSION}/${artifact}" \
    "${download_dir}/${artifact}"

  cp "${download_dir}/${artifact}" "${entry_point}"
  chmod +x "${entry_point}"

  echo "    staged $(du -sh "${payload_dir}" | cut -f1) in ${payload_dir}"
}

stage_conda

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

# No CAD library is listed: none is frozen in. See the note beside the pip
# installs above, and the `excludes` in "partcad.spec" that keep one out even
# when the build environment happens to have it.
REQUIRED = {
    "partcad_ide_client": "`pc inspect` displaying into the PartCAD IDE",
    # pygit2's compiled cffi module loads this from C, so nothing in the import
    # graph names it -- see the note beside the hidden import in "partcad.spec".
    "_cffi_backend": "pygit2, and so every repository PartCAD clones",
    "ruff.__main__": "`pc lint` of Python files",
    "aiomcache": "the 'cacheRemote' cache tier",
    "aioboto3": "the 'cacheS3' cache tier",
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
# The same directory, and the same reasoning, for the conda payload:
# `partcad_utils.conda.BUNDLED_SUBPATH` is where it is looked for.
CONDA_BUNDLED_DIR="${BUNDLE_DIR}/_internal/conda"

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

# conda is copied in the same way and for the same reason -- it is a payload
# PyInstaller has no business analysing -- but unconditionally: `stage_conda`
# either staged it or stopped the build.
echo "==> Installing the bundled conda"
rm -rf "${CONDA_BUNDLED_DIR}"
cp -a "${CONDA_PAYLOAD_DIR}" "${CONDA_BUNDLED_DIR}"

##############################################  ONE PAYLOAD  #################################################

# PyInstaller emits `pc`, `partcad` and `partcad-json-rpc` byte for byte
# identical -- since PyInstaller 6 an `EXE` carries the whole `PYZ`, so each is
# a full ~38MB copy of the compiled Python rather than the bootloader stub the
# one-directory layout suggests. Three of them cost ~76MB unpacked and about as
# much again in the archive, because a stream compressor cannot see across
# files that far apart.
#
# So keep one and point the other two at it. `entrypoint.py` dispatches on
# `sys.argv[0]`, which is the name the user typed and therefore survives the
# symlink, and PyInstaller's bootloader finds `_internal` beside the resolved
# executable, which is the same directory either way. Both the tar and the
# unpackers preserve the link: it is relative and stays inside the bundle,
# which is what `tarfile`'s "data" filter allows.
#
# Windows keeps three real copies. Its archive is a zip, which stores a symlink
# as a copy of its target anyway, and creating one there needs a privilege a
# runner does not have.
if [ "${OS_NAME}" != "windows" ]; then
  echo "==> Pointing the duplicate executables at 'pc'"
  for alias_name in partcad partcad-json-rpc; do
    if cmp -s "${BUNDLE_DIR}/pc" "${BUNDLE_DIR}/${alias_name}"; then
      rm -f "${BUNDLE_DIR}/${alias_name}"
      ln -s pc "${BUNDLE_DIR}/${alias_name}"
    else
      # A PyInstaller that starts emitting per-name executables would land
      # here. Nothing breaks; the bundle is just as big as it used to be.
      echo "    '${alias_name}' is not a copy of 'pc', leaving it alone"
    fi
  done
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

# The bundled conda: that the payload runs, that it is the version pinned above
# (which catches a stale `build/` from a different MICROMAMBA_VERSION and a copy
# that arrived without its executable bit), and then that `pc` resolves a conda
# at all. `micromamba --version` prints the version without the release's build
# number, so only the half before the "-" is compared.
conda_version_output="$(cd "${SMOKE_DIR}" && "${CONDA_BUNDLED_DIR}/micromamba${EXE_SUFFIX}" --version 2>&1)"
echo "    micromamba ${conda_version_output}"
# A prefix match rather than an equality: micromamba prints the version and
# nothing else, but it prints it through a stream that Windows opens in text
# mode, so what comes back there ends in a carriage return.
case "${conda_version_output}" in
"${MICROMAMBA_VERSION%-*}"*) ;;
*)
  echo "error: bundled micromamba is not ${MICROMAMBA_VERSION%-*}: '${conda_version_output}'" >&2
  exit 1
  ;;
esac

# What this proves is the same as for OpenSCAD, and no more: the health check
# reports that a conda was resolved, so it demonstrates the *bundled* one was
# used only on a machine that has none of its own -- hence the host is reported
# beside it. That a host conda still wins over the bundled copy, which is the
# ordering `partcad_utils.conda` deliberately has, is pinned down by the unit
# tests, where both can be made to exist at once.
echo "    host conda: $(command -v mamba || command -v conda || echo "none, so the check below can only pass via the bundle")"
(cd "${SMOKE_DIR}" && "${BUNDLE_DIR}/pc${EXE_SUFFIX}" --no-ansi healthcheck --filters conda 2>&1) |
  tee "${SMOKE_DIR}/healthcheck-conda.log"
grep -q "CondaAvailable: Passed" "${SMOKE_DIR}/healthcheck-conda.log" || {
  echo "error: PartCAD did not resolve a conda executable" >&2
  exit 1
}

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
  #
  # `-T0` gives xz every core, which is what keeps this to under a minute on a
  # runner; GNU tar passes XZ_OPT on to xz, and the bsdtar on macOS ignores it
  # and compresses single-threaded. `-6` is xz's default and already within a
  # couple of percent of `-9` here, which would cost far more memory per thread.
  XZ_OPT="${XZ_OPT:--6 -T0}" tar -cJf "${ARCHIVE_PATH}" -C "${OUTPUT_DIR}" partcad
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
echo "    bundle:   ${BUNDLE_DIR} ($(du -sh "${BUNDLE_DIR}" | cut -f1) unpacked)"
echo "    archive:  ${ARCHIVE_PATH} ($(du -h "${ARCHIVE_PATH}" | cut -f1))"
echo "    checksum: ${ARCHIVE_PATH}.sha256"
