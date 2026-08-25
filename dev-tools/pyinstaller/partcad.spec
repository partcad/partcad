# -*- mode: python ; coding: utf-8 -*-
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PyInstaller spec for the standalone PartCAD command line tools.

Produces a one-directory bundle that carries its own Python interpreter, so
``pc`` and ``partcad`` run on a machine where no Python is installed and no
Python environment has to be managed. It is what ``install.sh`` downloads.

One directory, not one file: a one-file build unpacks the whole payload into a
temporary directory on every single invocation, which for a bundle this size is
seconds of start-up per command.

The bundle replaces the *wheels*, not the sandbox. PartCAD runs every CAD
script (CadQuery, build123d, OpenSCAD) in a separate Python interpreter it
provisions itself through conda -- see ``partcad.runtime_python`` -- and carries
geometry between the two as BREP-byte envelopes it never opens. Freezing does
not change that, which is why the wrapper scripts below are bundled as data
files rather than as frozen modules: they are handed as a path to that other
interpreter.

And it is why **no CAD library is frozen in**. See ``EXCLUDES`` below.

Build it with ``dev-tools/pyinstaller/build.sh``, which prepares the
environment this spec expects. To run PyInstaller directly, install ``partcad``
(with its ``lint`` extra) plus ``pyinstaller`` into the current environment
first, then::

    pyinstaller --clean --noconfirm dev-tools/pyinstaller/partcad.spec
"""

import os
import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# `SPECPATH` is injected by PyInstaller and holds the directory of this file.
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parents[1]
# One wheel, one source root: every package the bundle freezes lives under it.
SRC = REPO_ROOT / "src"

IS_WINDOWS = sys.platform == "win32"

# Stripping the collected shared libraries, on Linux only.
#
# The spec used to leave this off everywhere, on the grounds that what it saves
# is noise next to the geometry kernel. The kernel is gone (see EXCLUDES) and it
# was never noise: measured on a Linux x86_64 build, stripping takes the ~44MB of
# shared objects the bundle collects down to ~25MB. Wheels routinely ship their
# native code unstripped, and pygit2's libgit2 and the CPython extensions are
# most of what is left here.
#
# macOS stays out because stripping has broken extension modules there before,
# and Windows has no `strip` at all. The `which` check keeps a build environment
# without binutils producing an unstripped bundle rather than failing: PyInstaller
# aborts the COLLECT when it is told to strip and cannot.
STRIP = sys.platform == "linux" and shutil.which("strip") is not None
if sys.platform == "linux" and not STRIP:
    print("partcad.spec: no 'strip' on PATH, the bundle will carry its symbol tables")

datas = []
binaries = []
hiddenimports = []


def add_package(name, include_metadata=False):
    """Pull in everything a distribution needs, tolerating its absence.

    Optional dependencies (the AI provider SDKs, the linter) are imported
    lazily by PartCAD and are not installed in every environment PyInstaller
    might be run from by hand. A bundle built without one of them stays usable,
    it just reports the same "not installed" error the wheels report, so this
    is a warning rather than a build failure. `build.sh`, which is how release
    bundles are built, refuses to build an incomplete one.
    """
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(name)
    except Exception as e:  # pragma: no cover - build-time diagnostics
        print(f"partcad.spec: skipping '{name}': {e}")
        return
    if not pkg_hiddenimports:
        # `collect_all` imports the package to enumerate it and, when that
        # import fails, returns its data files and no modules at all -- with a
        # warning easily lost in the build log, and a bundle that only breaks
        # once a user reaches that feature. `build.sh` checks these imports
        # before the build for the same reason.
        print(f"partcad.spec: WARNING: no modules collected for '{name}', it will be missing from the bundle")
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hiddenimports)
    if include_metadata:
        add_metadata(name)


def add_metadata(distribution):
    """Ship a distribution's metadata, for code that reads its own version."""
    try:
        datas.extend(copy_metadata(distribution))
    except Exception as e:  # pragma: no cover - build-time diagnostics
        print(f"partcad.spec: no metadata for '{distribution}': {e}")


def command_modules():
    """Name every CLI subcommand module, for `partcad_cli.click.loader`.

    The loader discovers subcommands by listing the ``commands`` directory and
    imports the one that was asked for by name, so nothing references these
    modules statically and PyInstaller cannot find them on its own.

    They are enumerated from the source tree rather than with
    ``collect_submodules`` because one of the packages is named ``import``,
    which is a keyword: it is reachable through ``importlib.import_module``
    (which is how the loader loads it) but not through an import statement.
    """
    root = SRC / "partcad_cli" / "click" / "commands"
    modules = []
    for path in sorted(root.rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(".".join(parts))
    return modules


#################################################  PARTCAD  ##################################################

# The frozen modules come from the checkout (`pathex` below), so the data files
# have to come from the checkout too, or the two could disagree.
datas += [
    # Executed by the sandbox interpreter, by path. They must exist as files.
    (str(SRC / "partcad" / "wrappers"), "partcad/wrappers"),
    # The packages PartCAD ships inside itself, loaded from disk as '//builtin'
    # and executed by path in a sandbox. Both their configuration and their
    # scripts must exist as files.
    (str(SRC / "partcad" / "builtin"), "partcad/builtin"),
    # Copied into new packages by `pc init`.
    (str(SRC / "partcad" / "template"), "partcad/template"),
    # Read through `importlib.resources` by `pc lint`. The ASSY schema is in
    # `partcad_utils` because both ends check ASSY files -- the daemon over a
    # package, `pc lint --file` in the client over one file.
    (str(SRC / "partcad" / "schema"), "partcad/schema"),
    (str(SRC / "partcad_utils" / "schema"), "partcad_utils/schema"),
    # The loader lists this directory to enumerate the available subcommands.
    (str(SRC / "partcad_cli" / "click" / "commands"), "partcad_cli/click/commands"),
    # Redistributing a binary bundle means redistributing its dependencies.
    (str(REPO_ROOT / "LICENSE.txt"), "."),
]

hiddenimports += collect_submodules("partcad")
hiddenimports += command_modules()

# The shared lightweight utilities (logging, telemetry, user config). `partcad`
# aliases these back under its own namespace, and the thin CLI/service clients
# import them directly (some, like the telemetry backends, only by name), so
# collect the whole package.
hiddenimports += collect_submodules("partcad_utils")
hiddenimports += collect_submodules("partcad_client")

# The JSON-RPC service (`partcad-json-rpc`). Its HTTP transport imports aiohttp
# lazily, inside a function that is only reached in HTTP mode, so PyInstaller's
# static analysis does not see it; name it (and the service package) explicitly.
hiddenimports += collect_submodules("partcad_service_json_rpc")
hiddenimports += collect_submodules("aiohttp")

##############################################  DEPENDENCIES  ################################################

# `pygit2`, which is how PartCAD clones and reads package repositories, is a
# cffi extension: `pygit2.ffi` imports `pygit2._libgit2`, a *compiled*
# (out-of-line) cffi module whose `.so` links `_cffi_backend` from C when it is
# loaded. No Python source anywhere writes `import _cffi_backend`, so
# PyInstaller's analysis has nothing to see, and a bundle without it dies with
# "No module named '_cffi_backend'" on the first thing that touches git -- which
# is the daemon start behind very nearly every `pc` command.
#
# This used to arrive by accident. The CAD stack the bundle carried imported
# `cffi` in Python, and the backend came along with it; dropping the kernel
# (see EXCLUDES) took the accident away and left `pygit2` broken. Name it.
hiddenimports += ["_cffi_backend"]

# zstd for the BREP payloads of the wrapper protocol and the shape cache. CI
# freezes with 3.14 (see build-standalone.yml), whose standard library carries
# 'compression.zstd', so this collects nothing there. On an older interpreter
# PartCAD imports the backport of that module instead, and it lives under the
# 'backports' namespace package, which PyInstaller does not follow into on its
# own.
if sys.version_info < (3, 14):
    add_package("backports.zstd")

# Data-driven packages: they resolve resources or plugins at runtime, so their
# non-Python files have to travel with them.
add_package("jsonschema")
add_package("jsonschema_specifications")
add_package("referencing")
add_package("vyper")

# Telemetry. Sentry discovers its integrations by module name, and the
# OpenTelemetry packages discover propagators and exporters through entry
# points, which only exist if the metadata is bundled.
hiddenimports += collect_submodules("sentry_sdk")
for _dist in ("opentelemetry-api", "opentelemetry-sdk", "opentelemetry-semantic-conventions"):
    add_metadata(_dist)
hiddenimports += collect_submodules("opentelemetry")

# Imported lazily, by name, so PyInstaller cannot see it from the import graph.
# `pc inspect` sends the tessellated shape to the PartCAD IDE through this. It
# ships inside the `partcad` wheel, so installing that is what puts it here.
add_package("partcad_ide_client")

# `pc lint` runs the linter as a subprocess. `ruff.__main__.find_ruff_bin()`
# looks in `sysconfig.get_path("scripts")` first, which inside a frozen bundle
# resolves to `bin` (`Scripts` on Windows) next to the bundled interpreter, so
# putting the executable there is enough for it to be found.
add_package("ruff")
_ruff_bin = Path(sys.prefix) / ("Scripts" if IS_WINDOWS else "bin") / ("ruff.exe" if IS_WINDOWS else "ruff")
if _ruff_bin.is_file():
    binaries += [(str(_ruff_bin), "Scripts" if IS_WINDOWS else "bin")]
else:
    print(f"partcad.spec: no ruff executable at '{_ruff_bin}', `pc lint` will not lint Python files")

# The clients of the two off-machine cache tiers. Both are imported inside the
# backend that needs them (see partcad/cache_backend_memcache.py and
# cache_backend_s3.py), so PyInstaller cannot see them from the import graph.
add_package("aiomcache")
add_package("aioboto3")

# The version PartCAD reports and sends with telemetry. One distribution now
# carries every package, so there is one set of metadata to ship.
add_metadata("partcad")

###############################################  OPENSCAD  ###################################################

# OpenSCAD is deliberately NOT declared here, even though the bundle ships it:
# `build.sh` copies it into the bundle after this spec has been built.
#
# Declaring the unpacked AppImage in `datas` does not keep PyInstaller's hands
# off it. Shared libraries found among data files are reclassified as binaries
# and collected into the top level of the bundle, so OpenSCAD's Qt, ICU and
# glib end up beside the ones Python needs -- on the frozen application's own
# library search path, and duplicated, at ~100MB. Copying the tree in
# afterwards keeps OpenSCAD's libraries where only OpenSCAD will find them.

###############################################  EXCLUDES  ###################################################

EXCLUDES = [
    # Test and development machinery that nothing in the CLI reaches.
    "pytest",
    "behave",
    "nox",
    "sphinx",
    "tkinter",
    # An IPython dependency, ~30MB of source code completion machinery that
    # is reachable only from an interactive prompt PartCAD never opens.
    "jedi",
]

# The CAD stack, kept out on purpose.
#
# PartCAD builds, renders, exports, converts and tessellates every shape in a
# conda sandbox, and moves the results between processes as BREP-byte envelopes
# the core carries without opening (`partcad.shape_envelope`). Three code paths
# in the core do hold a live shape, and none of them is reachable from a frozen
# bundle:
#
#   * `Shape.convert("build123d"/"cadquery")` and `Shape.show()`'s live-object
#     ancestry are library APIs, and this bundle is three console programs, not
#     an importable library. `convert()` already warns and re-raises when the
#     library is absent, which is what a wheel user without it sees too.
#   * `Shape._to_envelope()` encodes a live shape a factory built in-process.
#     No factory does: not one module under `partcad/` outside `wrappers/` and
#     `builtin/` imports a CAD library, and those two run in the sandbox.
#   * `partcad.geom` builds an OCCT transform on demand. `_from_ocp()` treats
#     the ImportError as "this is not an OCP object", which is right in a
#     process that has no OCP, and nothing calls the other two.
#
# So the kernel was carried unimported -- and it was most of the bundle. OCP is
# ~250MB of extension module and OpenCASCADE libraries, `build123d` pulls scipy,
# sympy, scikit-learn, numpy, IPython and ezdxf in at *import* time, and the
# VTK-enabled OCP the bundle used to pin pulls VTK on top of that. Dropping the
# lot took a Linux x86_64 build from 1010MB unpacked to 80MB, before the
# bundled OpenSCAD is copied in beside it.
#
# Naming them here rather than just not installing them is what makes the bundle
# the same wherever it is frozen: a developer building from a virtualenv that
# has build123d in it for other reasons would otherwise ship a different, much
# larger bundle than CI does. `build.sh` no longer installs any of this.
#
# `partcad/wrappers/ocp_serialize.py` still imports OCP at module level. It is
# bundled as a *data* file, not analyzed as a module, and it is imported by the
# sandbox interpreter -- which has the kernel -- so nothing here reaches it.
EXCLUDES += [
    "OCP",
    "build123d",
    "cadquery",
    "ocpsvg",
    "ocp_gordon",
    "ocp_tessellate",
    "lib3mf",
    "vtk",
    "vtkmodules",
    # Pulled in only by build123d and by VTK, and nothing else in the bundle
    # asks for them. Named so that a stray transitive edge cannot quietly bring
    # back the hundreds of megabytes they weigh together.
    "scipy",
    "sympy",
    "scikit-learn",
    "sklearn",
    "matplotlib",
    "IPython",
]

###############################################  ANALYSIS  ###################################################

a = Analysis(
    [str(SPEC_DIR / "entrypoint.py")],
    # The checkout comes first so the bundle matches the working tree rather
    # than whatever copy happens to be installed in the build environment.
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

##################################################  TRIM  ####################################################

# `google-api-python-client` ships a cached copy of the REST discovery document
# of every Google API, ~100MB of JSON, and PyInstaller has a hook that collects
# all of them. They are only read by `googleapiclient.discovery.build()`, which
# nothing here calls. `google-genai` does not depend on that package at all -
# unlike the `google-generativeai` it replaced - so this normally matches
# nothing now. It is kept as a guard: the filter costs nothing, and without it
# any transitive dependency that reintroduces the package silently adds an
# eighth to the bundle. This runs after the analysis because that is where the
# hook adds them; filtering the `datas` above would not see them.
_discovery_documents = os.path.join("googleapiclient", "discovery_cache", "documents")
a.datas = [entry for entry in a.datas if _discovery_documents not in os.path.normpath(entry[0])]

# The same shape of problem, one that does match: `botocore` ships the API model
# of every AWS service there is -- 400-odd directories, ~25MB -- and PyInstaller's
# hook collects the lot. PartCAD reaches exactly one of them: `cache_backend_s3`
# opens `session.client("s3")` and calls `get_object`/`put_object` on it. The
# rest is the price of a cache tier that most installations never enable.
#
# So keep the four files at the top of `data/` (`endpoints.json` and
# `partitions.json` resolve the endpoint, `_retry.json` and
# `sdk-default-configuration.json` are read for every client), keep `s3`, and
# keep the three services credential resolution can go through on the way to it:
# `sts` for assume-role, `sso`/`sso-oidc` for an SSO profile. Botocore loads a
# model by name at client construction, so a service left out here is one whose
# client raises `UnknownServiceError` -- not a silent wrong answer.
_botocore_data = os.path.join("botocore", "data") + os.sep
_botocore_keep = {"s3", "sts", "sso", "sso-oidc"}


def _botocore_wanted(destination):
    """Whether a collected `botocore/data` file is one PartCAD can reach."""
    path = os.path.normpath(destination)
    index = path.find(_botocore_data)
    if index < 0:
        return True
    relative = path[index + len(_botocore_data) :].split(os.sep)
    # A file directly in `data/` is configuration, not a service model.
    return len(relative) == 1 or relative[0] in _botocore_keep


a.datas = [entry for entry in a.datas if _botocore_wanted(entry[0])]

pyz = PYZ(a.pure)


def executable(name):
    """One console executable per name the CLI is invoked as."""
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        # See STRIP above: on Linux only, and only when binutils is present.
        strip=STRIP,
        # UPX is left off deliberately: it does not help a bundle this size and
        # it makes every start-up slower.
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


coll = COLLECT(
    executable("pc"),
    executable("partcad"),
    executable("partcad-json-rpc"),
    a.binaries,
    a.datas,
    strip=STRIP,
    upx=False,
    upx_exclude=[],
    name="partcad",
)
