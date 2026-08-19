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

One directory, not one file: the bundle is dominated by the ~500MB OCP
extension module and its OpenCASCADE libraries, and a one-file build would
unpack all of that into a temporary directory on every single invocation.

The bundle replaces the *wheels*, not the sandbox. PartCAD still runs CAD
scripts (CadQuery, build123d, OpenSCAD) in a separate Python interpreter it
provisions itself through conda -- see ``partcad.runtime_python``. Freezing
does not change that, which is why the wrapper scripts below are bundled as
data files rather than as frozen modules: they are handed as a path to that
other interpreter.

Build it with ``dev-tools/pyinstaller/build.sh``, which prepares the
environment this spec expects. To run PyInstaller directly, install ``partcad``
and ``partcad-cli`` (with their ``lint`` extra) plus ``pyinstaller``
into the current environment first, then::

    pyinstaller --clean --noconfirm dev-tools/pyinstaller/partcad.spec
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# `SPECPATH` is injected by PyInstaller and holds the directory of this file.
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parents[1]
PARTCAD_SRC = REPO_ROOT / "partcad" / "src"
CLI_SRC = REPO_ROOT / "partcad-cli" / "src"
SERVICE_SRC = REPO_ROOT / "partcad-service-json-rpc" / "src"

IS_WINDOWS = sys.platform == "win32"

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
    root = CLI_SRC / "partcad_cli" / "click" / "commands"
    modules = []
    for path in sorted(root.rglob("*.py")):
        parts = list(path.relative_to(CLI_SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(".".join(parts))
    return modules


#################################################  PARTCAD  ##################################################

# The frozen modules come from the checkout (`pathex` below), so the data files
# have to come from the checkout too, or the two could disagree.
datas += [
    # Executed by the sandbox interpreter, by path. They must exist as files.
    (str(PARTCAD_SRC / "partcad" / "wrappers"), "partcad/wrappers"),
    # Copied into new packages by `pc init`.
    (str(PARTCAD_SRC / "partcad" / "template"), "partcad/template"),
    # Read through `importlib.resources` by `pc lint`.
    (str(PARTCAD_SRC / "partcad" / "schema"), "partcad/schema"),
    # The loader lists this directory to enumerate the available subcommands.
    (str(CLI_SRC / "partcad_cli" / "click" / "commands"), "partcad_cli/click/commands"),
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
hiddenimports += collect_submodules("partcad_client_utils")

# The JSON-RPC service (`partcad-json-rpc`). Its HTTP transport imports aiohttp
# lazily, inside a function that is only reached in HTTP mode, so PyInstaller's
# static analysis does not see it; name it (and the service package) explicitly.
hiddenimports += collect_submodules("partcad_service_json_rpc")
hiddenimports += collect_submodules("aiohttp")

##############################################  DEPENDENCIES  ################################################

# The geometry kernel. OCP is a single extension module that registers all of
# its submodules (`OCP.TopoDS` and friends) at import time, so naming the top
# level module is enough for the bundle -- but PyInstaller cannot see through
# that, hence the explicit entry.
hiddenimports += ["OCP"]
add_package("build123d")
add_package("ocpsvg")
# build123d.mesher imports lib3mf unconditionally, and lib3mf ctypes-loads
# 'lib3mf.so' from its own directory rather than importing it, so PyInstaller's
# analysis never sees the binary. Without this the bundle dies on the very
# first "import partcad" with "The required binary .../lib3mf.so could not be
# found". (Only lib3mf does this; build123d's other native dependencies are
# ordinary extension modules.)
add_package("lib3mf")

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

# Imported lazily, by name, so that a bundle stays useful without them.
# `pc inspect` hands the shape to the OCP CAD Viewer.
add_package("ocp_vscode")

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

# The version PartCAD reports and sends with telemetry.
add_metadata("partcad")
add_metadata("partcad-utils")
add_metadata("partcad-client-utils")
add_metadata("partcad-cli")
add_metadata("partcad-service-json-rpc")

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

###############################################  ANALYSIS  ###################################################

a = Analysis(
    [str(SPEC_DIR / "entrypoint.py")],
    # The checkout comes first so the bundle matches the working tree rather
    # than whatever copy happens to be installed in the build environment.
    pathex=[str(PARTCAD_SRC), str(CLI_SRC), str(SERVICE_SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test and development machinery that nothing in the CLI reaches.
        "pytest",
        "behave",
        "nox",
        "sphinx",
        "tkinter",
        # An IPython dependency, ~30MB of source code completion machinery that
        # is reachable only from an interactive prompt PartCAD never opens.
        "jedi",
    ],
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
        # Stripping is left off: the size it saves is noise next to OCP, and
        # it has broken extension modules on macOS before.
        strip=False,
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
    strip=False,
    upx=False,
    upx_exclude=[],
    name="partcad",
)
