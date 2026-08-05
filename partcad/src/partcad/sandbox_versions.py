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


def _parsed(version: str):
    return tuple(int(part) for part in version.split("."))


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
