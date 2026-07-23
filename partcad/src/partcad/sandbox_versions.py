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

# Only needed by the sandboxes that rasterize or export 2D formats.
SVGLIB = "svglib==2.0.2"
REPORTLAB = "reportlab==5.0.0"
RLPYCAIRO = "rlpycairo==0.4.0"
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
GUARD_INVALIDATED_BY = {
    BUILD123D: (CADQUERY_OCP,),
}

# What a sandbox gets when the package does not ask for a specific interpreter.
# One step ahead of the minimum PartCAD itself supports.
DEFAULT_PYTHON_VERSION = "3.11"

# cadquery 2.8 requires Python 3.11 or newer, so a package that asks for 3.10
# still has to be rendered on 3.11.
MIN_PYTHON_VERSION_CADQUERY = "3.11"


def at_least(python_version: str, minimum: str) -> str:
    """Return the newer of two "<major>.<minor>" version strings."""

    def parsed(version):
        return tuple(int(part) for part in version.split("."))

    return python_version if parsed(python_version) >= parsed(minimum) else minimum
