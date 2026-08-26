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

    Optional dependencies (the linter, the two off-machine cache tiers) are
    imported lazily by PartCAD and are not installed in every environment
    PyInstaller might be run from by hand. A bundle built without one of them stays usable,
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

# Telemetry. The OpenTelemetry packages discover propagators and exporters
# through entry points, which only exist if the metadata is bundled.
#
# Sentry is collected whole *except* for its third-party integrations, which are
# both dead weight and a reproducibility hazard here. `telemetry_sentry.py` calls
# `sentry_sdk.init(default_integrations=False, integrations=[LoggingIntegration(...)])`,
# so nothing is ever auto-enabled and the only two that run are imported by name
# in that module. The other ~40 -- django, flask, celery, starlite, openai,
# langchain and the rest -- each `import` the library they instrument at module
# level, so `collect_submodules` on the whole package makes the bundle's contents
# depend on what else the build environment happens to have installed. That is
# how a machine with the AI SDKs on it produced a bundle 16MB larger, carrying
# `pydantic` and `pydantic_core` that nothing in PartCAD can reach.
#
# The filter is passed to `collect_submodules` rather than applied to what it
# returns, because `collect_submodules` imports each module it enumerates: an
# integration whose library is absent raises `DidNotEnable` and prints a warning
# during the build for something deliberate.
hiddenimports += collect_submodules("sentry_sdk", filter=lambda name: not name.startswith("sentry_sdk.integrations."))
hiddenimports += ["sentry_sdk.integrations.logging"]
hiddenimports += collect_submodules("sentry_sdk.integrations.opentelemetry")
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

############################################  COLLECTED TESTS  ###############################################

# `collect_all`/`collect_submodules` take a package whole, tests included, and
# these two are what drags the `unittest` package into a bundle that runs no
# tests. They are dropped from `hiddenimports` rather than named in `excludes`
# below: excluding a module that something asked for as a hidden import makes
# PyInstaller print "Hidden import ... not found" -- a dozen ERROR lines in the
# log of a release build, for something entirely deliberate.
TEST_MODULES = ("jsonschema.tests", "aiohttp.test_utils")
_test_prefixes = TEST_MODULES + tuple(name + "." for name in TEST_MODULES)
hiddenimports = [m for m in hiddenimports if not m.startswith(_test_prefixes)]

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
    # `pydoc`'s database of help topics, read only by `help()` at an interactive
    # prompt. `pydoc` itself stays: `pdb` and `site` reach it.
    "pydoc_data",
]

# Packaging machinery. Nothing in PartCAD imports `setuptools`, and the two
# things that touch `pkg_resources` -- `sentry_sdk.utils` and `wrapt.importer` --
# both do it inside `try: ... except ImportError: return`, as the fallback for an
# interpreter too old to have `importlib.metadata`. It was collected only because
# it happened to be installed in the build environment, and it brought `distutils`
# and `wheel` with it.
#
# Keeping `pkg_resources` out has a second effect worth knowing about: PyInstaller
# adds its `pyi_rth_pkgres` runtime hook only when `pkg_resources` is in the graph,
# and that hook is the sole reason `build.sh` used to pin `setuptools<82`.
EXCLUDES += [
    "setuptools",
    "pkg_resources",
    "_distutils_hack",
    "distutils",
    "wheel",
]

# Whatever the *build machine* keeps in `sitecustomize.py`/`usercustomize.py`.
# `site` imports them, so PyInstaller collects them, and a bundle then carries a
# file that has nothing to do with PartCAD and differs between builders. Same
# reasoning as naming the excluded dependencies below rather than trusting the
# build environment: the bundle should be the same wherever it is frozen.
EXCLUDES += ["sitecustomize", "usercustomize"]

# Optional dependencies of dependencies: every one of these is behind a
# `try: import ... except ImportError` or a `find_spec` check, so a bundle
# without them behaves exactly as the clean build environment behaves, and
# a build environment that happens to have them does not produce a heavier
# bundle than CI's.
#
#   cryptography, OpenSSL - `requests` and `urllib3.contrib.pyopenssl` reach for
#     them to replace the standard library's TLS on interpreters that need it.
#     11MB, and the bundle's TLS comes from the frozen CPython's `_ssl`.
#   httpx, httpcore - `aiobotocore` has an httpx backend beside its aiohttp one
#     ("try: import httpx / except ImportError: httpx = None"). PartCAD does not
#     select it, and `cache_backend_s3` only calls get_object/put_object.
#   pydantic, pydantic_core - reachable only from Sentry's starlite integration
#     (see below) and from a `TYPE_CHECKING` import in `yarl`, which guards its
#     one runtime use with `find_spec("pydantic_core")`. 4.5MB.
EXCLUDES += [
    "cryptography",
    "OpenSSL",
    "httpx",
    "httpcore",
    "pydantic",
    "pydantic_core",
]

# The AI provider SDKs.
#
# PartCAD used to generate parts with an LLM, and the bundle carried the SDKs for
# it because a frozen bundle cannot be extended with pip. PartCAD no longer
# drives a model -- it gives one tools to work with instead (see `ai-agents/`) --
# so the `ai` extra, the `ai-*` part types and these dependencies are all gone,
# the last of them from the monorepo's own `pyproject.toml`.
#
# The list stays as a floor rather than a cleanup that has already happened.
# Nothing here has to be *declared* to arrive: a stale virtualenv still has them,
# and a future transitive edge could reintroduce one without anybody deciding to.
# `googleapiclient` is the one that would actually hurt -- it ships a cached REST
# discovery document for every Google API, ~100MB of JSON, and PyInstaller has a
# hook that collects all of them.
EXCLUDES += [
    "openai",
    "ollama",
    "google.genai",
    "google_genai",
    "googleapiclient",
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
# lot took a Linux x86_64 build from 1010MB unpacked to 78MB, before the
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

# This runs after the analysis rather than on the `datas` above, because the
# files it drops are added by a PyInstaller hook rather than by this spec.
#
# `botocore` ships the API model of every AWS service there is -- 400-odd
# directories, ~25MB -- and its hook collects the lot. PartCAD reaches exactly
# one of them: `cache_backend_s3` opens `session.client("s3")` and calls
# `get_object`/`put_object` on it. The rest is the price of a cache tier that
# most installations never enable.
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

# Distribution metadata is collected by hooks that do not consult `excludes`, so
# a build environment that has one of the excluded packages installed still
# leaves its `.dist-info` behind -- `openai` brings `httpx2`, and its metadata
# arrived in a bundle that contains no httpx at all. It is inert and it is only
# tens of kilobytes, but it is also the last thing that made the bundle depend
# on what else the builder had installed, so drop it.
#
# Every name here is a distribution whose *code* is excluded above, which is
# what makes this safe: nothing that could read the metadata is in the bundle.
_excluded_metadata = (
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore2",
    "pydantic",
    "pydantic_core",
    "cryptography",
    "pyOpenSSL",
    "openai",
    "ollama",
    "google_genai",
    "google_api_python_client",
    "setuptools",
    "wheel",
)
a.datas = [
    entry
    for entry in a.datas
    if not os.path.normpath(entry[0]).startswith(tuple(name + "-" for name in _excluded_metadata))
]

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
