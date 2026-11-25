#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae fea`, by FieldCraft: a linear static stress analysis of one part, and optionally its buckling.

`fix:` holds the faces its ports cover still in every direction; `load:` spreads
its force over the faces its ports cover in proportion to their area -- along
the direction the part states, a load written as `[x, y, z]` in its own frame,
and along -Z, where a weight goes, for a load written as a magnitude. Gravity
acts on the part's own mass too: the `gravity:` the part states, in its own
frame, or 9.81 m/s^2 along -Z unless `self_weight` is off.

Quadratic tetrahedra by default, meshed by gmsh with the faces each port covers
named, and solved by FieldCraft's own linear solver (`solve.static`).

With `buckling` on, the same loads are also a preload for a linear buckling
step (`solve.buckle`): the lowest load factor is how many times the loads the
part carries before it buckles, and one under `min_buckling_factor` is a
finding. It is the one question FieldCraft answers here that no other PartCAD
implementation does.
"""

import os
import sys
import tempfile

# `runpy.run_path()` leaves the script's directory off `sys.path`, so the
# sibling module below is not importable without saying where it is.
sys.path.append(os.path.dirname(__file__))
import fieldcraft_common as fc  # noqa: E402
from fieldcraft_common import ERROR, WARNING, support  # noqa: E402

STEP = "Load"
BUCKLE = "Buckle"


def process(path, request):
    try:
        return _analyse(path, request)
    except (support.ToolMissing, support.ToolFailed) as e:
        return support.failed(e)


def _analyse(path, request):
    findings = []
    fixed, fixed_records, fixed_empty = support.condition_groups(request, "fix", "fix")
    loaded, loaded_records, loaded_empty = support.condition_groups(request, "load", "load")
    findings.extend(fc.nothing_covered(record) for record in fixed_empty + loaded_empty)
    if not fixed_records:
        # Nothing to react against: every node would move together and the
        # stiffness matrix is singular.
        raise support.ToolFailed(
            "'fea:' holds nothing, so the part is free to float: name at least one interface under 'fix:', "
            "on a port that covers a surface of the part"
        )

    with tempfile.TemporaryDirectory() as work:
        work = fc.case_dir(work)
        mesh, msh = fc.mesh_part(request, {**fixed, **loaded}, work, int(request.get("mesh_order", 2)))
        commands, buckling = commands_for(request, msh, fixed, loaded, loaded_records, work)
        replies = fc.run(work, commands, request)
        points, cells, fields, _data = fc.read_vtu(os.path.join(work, "result.vtu"))

    displacement = fc.magnitude(fields.get("displacement", []))
    stress = fc.scalar(fields.get("von_mises", []))
    if not displacement or not stress:
        raise support.ToolFailed("FieldCraft wrote no displacements or no von Mises stresses")
    support.write_glb(path, points, fc.surface(points, cells), stress, low=0.0, high=_top(request))

    peak_stress = max(stress)
    peak_displacement = max(displacement) * fc.MM_PER_M
    findings.extend(_verdict(peak_stress, peak_displacement, request))
    warnings = [_summary(peak_stress, peak_displacement, mesh.element_count, request)]
    if buckling:
        factors = load_factors(replies[-1])
        findings.extend(_buckling_verdict(factors, request))
        warnings.append(_buckling_summary(factors))
    return {"success": True, "findings": findings, "warnings": warnings}


def commands_for(request, msh, fixed, loaded, loaded_records, work):
    """The engine commands of the analysis, and whether they end in a buckling solve."""
    density = float(request.get("density", 7850))
    commands = fc.import_mesh(msh)
    commands.append(
        {
            "command": "model.material.create",
            "params": {
                "name": "material",
                "elastic": {
                    "type": "isotropic",
                    "young": float(request.get("youngs_modulus", 2.1e11)),
                    "poisson": float(request.get("poissons_ratio", 0.30)),
                },
                "density": density,
            },
        }
    )
    commands.append(fc.solid_section("material"))

    held = []
    for name in fixed:
        held.append(name)
        commands.append(
            {
                "command": "model.boundary_condition.create",
                "params": {"name": name, "type": "fixed", "target": {"set": name}},
            }
        )

    loads = []
    for name, record in zip(loaded, loaded_records):
        loads.append(name)
        # The total force on the port, split by area over the faces it covers:
        # a finer mesh does not load the part harder.
        commands.append(
            {
                "command": "model.load.create",
                "params": {
                    "name": name,
                    "type": "force",
                    "target": {"set": name},
                    "vector": force_of(record),
                    "distribution": "total",
                },
            }
        )
    gravity = gravity_of(request)
    if any(component != 0.0 for component in gravity):
        loads.append("weight")
        commands.append(
            {"command": "model.load.create", "params": {"name": "weight", "type": "gravity", "acceleration": gravity}}
        )

    commands.append(
        {
            "command": "model.step.create",
            "params": {"name": STEP, "procedure": {"type": "static"}, "boundary_conditions": held, "loads": loads},
        }
    )
    commands.append({"command": "solve.static", "params": {"step": STEP}})
    commands.append(
        {
            "command": "results.export.vtu",
            "params": {"step": STEP, "path": os.path.join(work, "result.vtu"), "encoding": "ascii"},
        }
    )

    buckling = fc.flag(request.get("buckling"), False)
    if buckling:
        commands.append(
            {
                "command": "model.step.create",
                "params": {
                    "name": BUCKLE,
                    "procedure": {"type": "buckle", "modes": int(request.get("buckling_modes", 3))},
                    "boundary_conditions": held,
                    "loads": loads,
                },
            }
        )
        commands.append({"command": "solve.buckle", "params": {"step": BUCKLE}})
    return commands, buckling


def force_of(record):
    """The force on one loaded port, newtons in the part's frame: as stated, or its magnitude straight down."""
    force = record.get("force")
    if isinstance(force, (list, tuple)) and len(force) == 3:
        return [float(component) for component in force]
    return [0.0, 0.0, -float(record["load"])]


def gravity_of(request):
    """The acceleration of free fall the part is weighed under, m/s^2 in its own frame.

    The part's own `gravity:` where it stated one -- a gravity of nought weighs
    nothing -- and otherwise 9.81 m/s^2 along -Z, unless `self_weight` is off.
    """
    stated = request.get("gravity")
    if isinstance(stated, (list, tuple)) and len(stated) == 3:
        return [float(component) for component in stated]
    return [0.0, 0.0, -9.81 if fc.flag(request.get("self_weight"), True) else 0.0]


def load_factors(reply):
    """The load factors a `solve.buckle` reply lists, lowest first, whatever it calls them."""
    found = []

    def collect(value):
        if isinstance(value, dict):
            for key in ("load_factor", "factor", "eigenvalue", "lambda"):
                if isinstance(value.get(key), (int, float)):
                    found.append(float(value[key]))
                    return
            for key in ("load_factors", "factors", "eigenvalues", "modes"):
                if key in value:
                    collect(value[key])
                    return
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (int, float)):
                    found.append(float(item))
                else:
                    collect(item)

    collect(reply)
    return sorted(found, key=abs)


def _buckling_verdict(factors, request):
    limit = float(request.get("min_buckling_factor", 3.0))
    positive = [factor for factor in factors if factor > 0]
    if not factors:
        return [
            {
                "severity": WARNING,
                "message": "FieldCraft's buckling solve reported no load factor, so buckling was not checked.",
                "where": "buckling",
            }
        ]
    if positive and positive[0] < 1.0:
        return [
            {
                "severity": ERROR,
                "message": "The part buckles under this load: the lowest load factor is %.3g." % positive[0],
                "where": "buckling",
            }
        ]
    if positive and positive[0] < limit:
        return [
            {
                "severity": WARNING,
                "message": "The part buckles at %.3g times this load, under the %.3g it is held to."
                % (positive[0], limit),
                "where": "buckling",
            }
        ]
    return []


def _buckling_summary(factors):
    if not factors:
        return "Buckling: no load factor was reported"
    return "Buckling load factors %s" % ", ".join("%.4g" % factor for factor in factors)


def _summary(peak_stress, peak_displacement, elements, request):
    """The one line said of every run: its peaks, and the peak stress as a share of what the part is held to."""
    allowable = _allowable(request)
    if allowable > 0:
        share = "%.0f%% of the allowable %.3g MPa" % (100.0 * peak_stress / allowable, allowable / 1e6)
    else:
        share = "no allowable stress: 'yield_strength' is not positive"
    return "Peak von Mises stress %.4g MPa (%s), peak displacement %.4g mm, over %d elements" % (
        peak_stress / 1e6,
        share,
        peak_displacement,
        elements,
    )


def _allowable(request):
    """The stress a part is held to: its yield strength over the safety factor, in Pa."""
    yield_strength = float(request.get("yield_strength", 2.5e8))
    safety_factor = float(request.get("safety_factor", 1.5))
    return yield_strength / max(safety_factor, 1e-9)


def _top(request):
    """The stress the top of the colour ramp stands for: the allowable one, or None for this run's own peak."""
    if not fc.flag(request.get("scale_to_allowable"), False):
        return None
    allowable = _allowable(request)
    return allowable if allowable > 0 else None


def _verdict(peak_stress, peak_displacement, request):
    """What the numbers mean, as findings: the thresholds the package configured."""
    findings = []
    yield_strength = float(request.get("yield_strength", 2.5e8))
    safety_factor = float(request.get("safety_factor", 1.5))
    allowable = _allowable(request)
    if peak_stress > yield_strength:
        findings.append(
            {
                "severity": ERROR,
                "message": "The part yields under this load: peak stress %.3g MPa against a yield strength of %.3g MPa."
                % (peak_stress / 1e6, yield_strength / 1e6),
                "where": "peak von Mises stress",
            }
        )
    elif peak_stress > allowable:
        findings.append(
            {
                "severity": WARNING,
                "message": "The part does not reach the safety factor of %.2f: peak stress %.3g MPa against an "
                "allowable %.3g MPa." % (safety_factor, peak_stress / 1e6, allowable / 1e6),
                "where": "peak von Mises stress",
            }
        )
    limit = request.get("max_displacement")
    if limit is not None and peak_displacement > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part moves %.3g mm under this load, past the %.3g mm it is allowed."
                % (peak_displacement, float(limit)),
                "where": "peak displacement",
            }
        )
    return findings


# Importable as a module by its tests, and executed by PartCAD's meta-wrapper
# under the run name below -- so nothing here runs on import.
if __name__ == "__partcad_export__":
    pass
