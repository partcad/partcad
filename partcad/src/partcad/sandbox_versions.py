#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Pinned versions of the CAD packages installed into Python sandboxes.

Every factory that renders a part or a sketch through a sandboxed interpreter
installs the same handful of packages into it. Spelling the versions out here
rather than in each factory means a stack upgrade is one edit instead of a
dozen, and it makes it impossible for two factories to disagree about which
OCP a shared sandbox gets -- a disagreement that surfaces as a native crash
with no Python traceback at all (see runtime_python.PIP_CONSTRAINTS).
"""

import re

# 'cadquery-ocp' and the 'cadquery-ocp-novtk' that build123d 0.11 depends on
# are NOT alternatives pip knows about: they are separate distributions that
# both write the very same OCP native module, so whichever pip installs last
# wins. The novtk build is compiled without the VTK-backed modules, and
# "import cadquery" needs them (OCP.IVtkOCC), so a sandbox that ends up with
# the novtk build fails every CadQuery render with an unrelated-looking
# ImportError. See GUARD_INVALIDATED_BY below for how that is forced to come
# out right.
CADQUERY_OCP = "cadquery-ocp==7.9.3.1.1"
OCPSVG = "ocpsvg==0.6.0"
BUILD123D = "build123d==0.11.1"
CADQUERY = "cadquery==2.8.0"
OCP_TESSELLATE = "ocp-tessellate==3.4.1"
TYPING_EXTENSIONS = "typing_extensions==4.16.0"
NLOPT = "nlopt==2.11.0"
# No single numpy release covers Python 3.10 through 3.14 (2.3 dropped 3.10),
# so this one stays a range and pip picks per interpreter.
NUMPY = "numpy>=2.2,<3"

# The wrapper protocol compresses the BREP payloads it packs, so a sandbox has
# to be able to decompress what the host sends it and vice versa (see
# wrappers/ocp_serialize.py). Python 3.14 has zstd in the standard library as
# 'compression.zstd'; below that this backport of that very module provides it,
# so both ends speak identical frames.
#
# A lower bound rather than a pin: it is a self-contained backport of a standard
# library module, nothing else in the sandbox links against it, and what it
# reads and writes is the zstd frame format itself.
ZSTD = "backports.zstd>=1.6.0"

# The first Python whose standard library makes ZSTD unnecessary.
MIN_PYTHON_VERSION_ZSTD_STDLIB = "3.14"

# The URDF reader/writer used by the 'urdf' assembly type and by the URDF
# exporter. This is ROS's own URDF parser (github.com/ros/urdf_parser_py), the
# same package 'urdfdom_py'/'ros-*-urdfdom-py' ships as, so PartCAD reads and
# writes exactly what the ROS toolchain does rather than a lookalike of it.
#
# Installed only into the sandboxes that touch URDF, so neither PartCAD nor a
# package that never mentions URDF grows a dependency on the ROS stack.
URDF_PARSER_PY = "urdf-parser-py==0.0.4"

# Only needed by the sandboxes that rasterize or export 2D formats.
#
# Deliberately held at the versions this repo already shipped, not bumped to the
# newest releases. These run inside a fixed ~3.11 render sandbox, so they gain
# nothing from the 3.10-3.14 widening, and svglib 2.0 is a ground-up rewrite
# (new lxml/tinycss2 stack) whose behaviour change belongs in its own PR rather
# than riding along in a dependency sweep.
#
# NOTE: bumping these is not what makes PNG rendering work. reportlab renders
# PNG through renderPM's rlPyCairo backend (its wheels carry no compiled
# '_renderPM'), so PNG needs pycairo -> cairo. pycairo has no Linux wheel and
# building it against a system cairo is fragile (it broke on the ubuntu-22.04
# runner); that is solved separately by installing pycairo from conda-forge
# into the sandbox -- see runtime_python_conda. These versions are just the
# proven-stable ones.
SVGLIB = "svglib==1.5.1"
REPORTLAB = "reportlab==4.4.3"
RLPYCAIRO = "rlpycairo==0.3.0"
SVGPATHTOOLS = "svgpathtools==1.7.2"
EZDXF = "ezdxf==1.4.4"

# Installing a package on the left overwrites files owned by the packages on
# the right, so those have to be installed again afterwards -- forcibly, since
# pip otherwise considers them satisfied and leaves the clobbered files alone.
# runtime_python.invalidate_dependent_guards() does the bookkeeping.
#
# The one case today is build123d, which depends on 'cadquery-ocp-novtk' and so
# replaces the OCP native module with a build that has no VTK support. A later
# build123d install cannot undo the repair, because pip by then already
# considers novtk satisfied and does not reinstall it.
#
# Every install list in this package therefore ends with CADQUERY_OCP, so the
# re-assertion happens within the same sequence rather than at some arbitrary
# later point.
#
# The re-assertion makes the VTK build win once a sandbox's installs have all
# settled, but it does not by itself guarantee the VTK build is the one on disk
# at the instant an interpreter starts. When a CadQuery part and a build123d
# part of the same package share a session v-env and render concurrently, a
# build123d (novtk) install must not slip in between another part's re-assertion
# and its "import cadquery". runtime_python.run_onced / run_async_onced close
# that window by serializing a session's installs and its run under one v-env
# lock.
GUARD_INVALIDATED_BY = {
    BUILD123D: (CADQUERY_OCP,),
}

# The CAD stack this module pins, keyed by distribution name. These packages are
# a single, co-dependent generation: 'cadquery' 2.8 calls OCP 7.9 APIs that OCP
# 7.7 does not have ("type object 'OCP.TopoDS.TopoDS' has no attribute 'Vertex'"),
# 'ocp-tessellate' tracks the same generation, and build123d/cadquery-ocp write
# the same native module. Installing any one of them at a different version
# breaks the others.
#
# That matters because a *session* v-env is shared by every part of a package.
# A single part asking for its own version of one of these (part_factory_sdf.py
# used to pin cadquery-ocp==7.7.2, ocp-tessellate==3.0.9 and build123d==0.8.0)
# silently downgraded the stack under every other part in the same package, and
# their renders then failed with errors that named neither the package nor the
# part that caused it. reconcile_requirement() below makes that impossible.
PINNED_REQUIREMENTS = (
    CADQUERY_OCP,
    OCPSVG,
    BUILD123D,
    CADQUERY,
    OCP_TESSELLATE,
    NLOPT,
)


def distribution_name(requirement: str) -> str:
    """The distribution a requirement string names, normalized per PEP 503.

    Only what this module needs: a bare name optionally followed by extras, a
    version specifier or an environment marker. URLs and paths are returned
    unchanged (lowercased), which is enough for them to miss every lookup.

    The normalization is the full PEP 503 rule - lowercase, with every run of
    '.', '-' and '_' collapsed to a single '-' - because pip accepts all of those
    spellings for the same distribution. Anything less lets 'cadquery.ocp==7.7.2'
    or 'cadquery--ocp==7.7.2' name the pinned CAD stack while slipping past the
    lookup below, which is exactly what this guard exists to prevent.
    """
    name = requirement.strip()
    for separator in ("[", "=", "<", ">", "!", "~", ";", " ", "@"):
        name = name.split(separator, 1)[0]
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _split_marker(requirement: str) -> tuple[str, str | None]:
    """Split a requirement into its body and its environment marker, if any."""
    body, separator, marker = requirement.partition(";")
    return body.strip(), (marker.strip() if separator else None)


# Built once: distribution name -> the requirement this module pins for it.
_PINNED_BY_DISTRIBUTION = {distribution_name(requirement): requirement for requirement in PINNED_REQUIREMENTS}


def reconcile_requirement(requirement: str) -> tuple[str, str | None]:
    """Force a CAD-stack requirement to the version this module pins.

    Returns '(requirement_to_install, superseded_requirement)'. The second value
    is the caller's original requirement when it was overridden, and None when
    the requirement was left alone - callers use it to report the substitution.

    An environment marker is carried over onto the pinned requirement: the caller
    asked for the package only under that condition, and dropping the marker
    would install it unconditionally instead. Only the version is overridden.

    Anything outside PINNED_REQUIREMENTS is returned untouched: a package is free
    to install whatever else it needs into its sandbox.
    """
    body, marker = _split_marker(requirement)
    pinned = _PINNED_BY_DISTRIBUTION.get(distribution_name(body))
    if pinned is None:
        return requirement, None
    reconciled = pinned if marker is None else "%s; %s" % (pinned, marker)
    if reconciled == requirement.strip():
        return requirement, None
    return reconciled, requirement


# What a sandbox gets when the package does not ask for a specific interpreter.
# One step ahead of the minimum PartCAD itself supports.
DEFAULT_PYTHON_VERSION = "3.11"

# cadquery 2.8 requires Python 3.11 or newer, so a package that asks for 3.10
# still has to be rendered on 3.11.
MIN_PYTHON_VERSION_CADQUERY = "3.11"

# The first Python CPython publishes a free-threaded ("no-GIL") build of, and so
# the first for which conda-forge carries two ABI variants of one and the same
# release. See python_abi_requirement() for why that has to be disambiguated.
MIN_PYTHON_VERSION_FREE_THREADING = "3.13"


def _parsed(version: str):
    return tuple(int(part) for part in version.split("."))


def _major_minor(version: str) -> str:
    """The bare "<major>.<minor>" of a version that may carry more components.

    Callers are documented to pass "<major>.<minor>", but nothing enforces it:
    the package schema's 'pythonVersion' pattern accepts "3.13.1" and no layer
    between it and a sandbox trims the patch component off. python_abi is
    versioned by ABI rather than by release -- conda-forge publishes
    "python_abi 3.13.* *_cp313" and no 3.13.1 of it at all -- so a patch version
    reaching python_abi_requirement() unedited yields a spec that matches
    nothing and fails the solve with an error naming neither PartCAD nor the
    setting that caused it.

    Built on _parsed() so the components are validated as numbers here, the same
    way is_at_least() validates them.
    """
    major, minor = _parsed(version)[:2]
    return "%d.%d" % (major, minor)


def is_at_least(python_version: str, minimum: str) -> bool:
    """Whether a "<major>.<minor>" version is not older than another.

    Compared numerically: as strings "3.9" sorts after "3.11".
    """
    return _parsed(python_version) >= _parsed(minimum)


def at_least(python_version: str, minimum: str) -> str:
    """Return the newer of two "<major>.<minor>" version strings."""
    return python_version if is_at_least(python_version, minimum) else minimum


def zstd_requirement(python_version: str) -> str | None:
    """What a sandbox has to install for zstd, or None if it already has it.

    Installing the backport where 'compression.zstd' exists would be harmless
    but pointless: the backport declares Python < 3.14, so pip would fail to
    resolve it and take the whole sandbox initialization down with it.

    Decided from the version alone, deliberately. A 3.14 interpreter built
    without libzstd would have no 'compression.zstd' either, but probing for it
    here would ask the wrong Python -- this runs in the PartCAD process, and the
    answer is about the sandbox interpreter. Nor would knowing help: the
    backport refuses to install on 3.14, so there would be nothing to install in
    its place. Such a sandbox instead fails where it is unambiguous, in
    wrappers/ocp_serialize, with a message naming what is missing.
    """
    if is_at_least(python_version, MIN_PYTHON_VERSION_ZSTD_STDLIB):
        return None
    return ZSTD


def python_abi_requirement(python_version: str, exact: bool = True) -> str | None:
    """The conda spec that holds a sandbox to the GIL build of its interpreter.

    NOT redundant, however much it looks it. "python==3.14" names a version and
    nothing else, and from 3.13 onwards conda-forge publishes two builds of every
    single release: the ordinary one ("*_cp314") and the free-threaded, no-GIL
    one ("*_cp314t"). Which one an unconstrained solve lands on is the solver's
    business, and on the CI runners it landed on the free-threaded one -- the
    sandbox came out at "lib/python3.14t/site-packages".

    Nothing in PartCAD wants that build, and the whole CAD stack is unusable in
    it: cadquery-ocp and nlopt publish "cp314-cp314" wheels and no "cp314t" ones,
    so pip finds no candidate at all ("Could not find a version that satisfies
    the requirement nlopt==2.11.0"), and every part defined by a script then dies
    with "No module named 'OCP'". Remove this and that comes back.

    The pin goes on 'python_abi' rather than on the 'python' spec itself. A build
    string can only be given in conda's three-field "name=version=build" form, so
    pinning it on 'python' would mean rewriting the version half of the spec the
    caller asked for as well. 'python_abi' is a package the interpreter already
    depends on -- python 3.14 declares "python_abi 3.14.* *_cp314" -- so pinning
    its build string pins the interpreter's without touching the python spec and
    without adding anything to the environment that was not going in anyway.

    None below 3.13: there CPython has no free-threaded build to disambiguate,
    and conda-forge's build strings end in "_cpython" rather than "_cp312", so a
    "*_cp312" pin would match no package at all and fail the solve outright.

    'exact' picks the spelling of the equality, mirroring the python spec the
    caller builds: mamba is given "==", conda "=". Both select the same package
    here, since python_abi's version is the bare "<major>.<minor>".

    That is also why both halves of the spec are derived from _major_minor()
    rather than from the caller's string: a "3.13.1" would otherwise ask for a
    python_abi release that does not exist and for a "*_cp3131" build that names
    no ABI. See _major_minor() for how such a version gets here.
    """
    if not is_at_least(python_version, MIN_PYTHON_VERSION_FREE_THREADING):
        return None
    equality = "==" if exact else "="
    abi_version = _major_minor(python_version)
    return "python_abi%s%s=*_cp%s" % (equality, abi_version, abi_version.replace(".", ""))


#
# JavaScript (Node.js) sandboxes
#
# The npm counterpart of everything above: one place that decides what a
# JavaScript sandbox gets by default. "By default" is the whole difference from
# the Python side. There, the CAD stack has to be forced (see
# reconcile_requirement) because every part of a package shares one flat
# environment, so one part's choice silently becomes everybody's. A JavaScript
# environment is instead identified by the very set of dependencies it holds
# (see runtime_javascript.env_dir_name), so a part that asks for its own Chili3D
# gets its own tree and cannot reach anyone else's - which means the version can
# simply be a package's or a part's to choose.
#

# Chili3D ships its OCCT kernel as a WebAssembly module ('chili-wasm') plus a
# TypeScript API bundled into 'dist/index.js'. Both live in the one 'chili3d'
# distribution on npm, so a sandbox needs nothing else to model.
#
# An exact version rather than a range: the wrapper reaches into
# 'chili3d/packages/chili-wasm/lib' for the '.wasm' and its Emscripten loader,
# which the package's "exports" map does not expose, so a layout change is a
# breaking change for us even when it is not one for a browser consumer. This is
# the version a package gets when it does not name one - see
# chili3d_requirement().
DEFAULT_CHILI3D_VERSION = "1.1.2"
CHILI3D = "chili3d@" + DEFAULT_CHILI3D_VERSION

# Chili3D's bundle is built for the browser: importing it evaluates modules that
# subclass HTMLElement and register custom elements, so a bare Node process
# fails at import with "HTMLElement is not defined". happy-dom supplies just
# enough DOM for the import to succeed - it is what Chili3D itself uses for its
# own tests - and nothing in the modeling path touches it afterwards.
#
# A range rather than an exact version: it is only a shim for globals whose
# shape has been stable for years, and it carries no native code.
HAPPY_DOM = "happy-dom@^20.11.2"

# What a JavaScript sandbox gets when the package does not ask for a specific
# Node.js. 22 is the active LTS line.
DEFAULT_NODE_VERSION = "22"

# The oldest Node.js the Chili3D wrapper is known to load on: it reads the
# WebAssembly kernel through the Emscripten loader's 'wasmBinary' hook and needs
# 'node:zlib', 'fs.realpathSync' and top-level await, all of which 20 has.
MIN_NODE_VERSION = "20"

# Nothing here pins zstd for the JavaScript side. 'node:zlib' grew the zstd
# helpers in 22.15 and the wrappers feature-detect them: where they are missing
# a wrapper writes BREP uncompressed, which the Python end accepts because it
# sniffs the zstd frame header rather than being told (see
# wrappers/ocp_serialize._decompress).

# What a JavaScript sandbox is provisioned with when nothing asks for anything
# else. Unlike PINNED_REQUIREMENTS above these are defaults, not pins: a package
# or a part that names its own version of one of them gets that version, in an
# environment of its own (see the note at the top of this section).
DEFAULT_JS_REQUIREMENTS = (
    CHILI3D,
    HAPPY_DOM,
)


# What npm accepts that is not "<name>[@<range>]": a URL, a git remote, a
# tarball, or a path. The '@' in one of these is part of the location rather
# than a version separator - 'git+ssh://git@host/org/pkg.git' would otherwise
# come out as 'git+ssh://git', which two unrelated remotes would share.
_NON_REGISTRY_JS_PREFIXES = ("git+", "git:", "http:", "https:", "file:", "./", "../", "/", "~/")
_NON_REGISTRY_JS_SUFFIXES = (".tgz", ".tar.gz", ".git")


def is_registry_js_requirement(requirement: str) -> bool:
    """Whether a requirement names a registry package rather than a location."""
    requirement = requirement.strip()
    if "://" in requirement:
        return False
    if requirement.startswith(_NON_REGISTRY_JS_PREFIXES):
        return False
    return not requirement.endswith(_NON_REGISTRY_JS_SUFFIXES)


def js_package_name(requirement: str) -> str:
    """The npm package a requirement string names.

    Handles the spellings npm accepts for a registry dependency: a bare name, a
    name with a version range ("chili3d@1.1.2"), and a scoped name whose leading
    '@' must not be mistaken for the version separator ("@scope/pkg@1.2.3").

    Anything that names a location rather than a registry package is returned
    untouched, so it stays distinct from every other requirement instead of
    being folded together with them by whatever precedes its first '@'.
    """
    requirement = requirement.strip()
    if not is_registry_js_requirement(requirement):
        return requirement
    if requirement.startswith("@"):
        name, separator, _ = requirement[1:].partition("@")
        return "@" + name if separator else requirement
    return requirement.partition("@")[0] or requirement


def chili3d_requirement(version=None) -> str:
    """The npm requirement for a Chili3D version, or for the default one.

    A bare version ("1.1.2") becomes an exact requirement; anything that already
    looks like a range or a tag ("^1.1", "~1.1.2", "latest") is passed through,
    so a package that wants to float can say so.
    """
    if version is None:
        return CHILI3D
    version = str(version).strip()
    if not version:
        return CHILI3D
    return "chili3d@" + version


def node_major_version(version: str) -> str:
    """The major version of a "<major>[.<minor>...]" Node.js version string.

    Node.js is versioned by major line, and that is the granularity a sandbox is
    provisioned at, so "22", "22.11" and "v22.11.0" all name the same sandbox.
    """
    return str(version).lstrip("v").split(".")[0]


#
# Caching
#


def environment_cache_key(interpreter: str, version: str, requirements) -> str:
    """The identity of a sandbox, as the string a shape is cached under.

    '(interpreter, version)' is what runs the script - "python" and "3.11", or
    "nodejs" and "22" - and 'requirements' is everything installed alongside it.

    Sorted and de-duplicated, so the key is decided by *what* the environment
    contains and not by the order the factories happened to ask for it. Empty
    entries are dropped: a package that declares no dependencies of its own has
    to key the same as one that declares an empty list.

    See Shape.set_environment_cache_key() for what this is for.
    """
    unique = sorted({requirement.strip() for requirement in requirements if requirement and requirement.strip()})
    return "%s==%s;%s" % (interpreter, version, ";".join(unique))
