#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae cfd`, by CalculiX: incompressible flow through one part.

The part is read as the **fluid volume** -- the space the fluid is in, not the
wall around it. That is the one thing worth understanding before reading a
result out of this: a duct is analysed by declaring the bore as a part, not the
casting.

The boundary conditions are the same two keys `fea:` takes, and they mean the
corresponding things:

* `fix:` names the **walls**: no slip, the fluid is held still against them.
* `load:` names where the flow is **driven**, as a force. A force on a boundary
  divided by the area of that boundary is a pressure, and pressure is what an
  incompressible solver is driven by -- so a `load:` of 30 N on an inlet whose
  neighbourhood covers 300 mm2 is a 100 kPa inlet. This is why `cfd:` takes a
  force and not a velocity: it is the same declaration the part already makes
  for FEA, in the same units, meaning the same physical thing.

CalculiX solves incompressible flow transiently and is marched to a steady state
rather than asked for one, which is what `duration` and `time_step` are.
"""

import math
import tempfile

import calculix_common as ccx

ERROR = "error"
WARNING = "warning"
INFO = "info"


def process(path, request):
    try:
        return _analyse(path, request)
    except (ccx.SolverMissing, ccx.SolverFailed) as e:
        return ccx.failed(e)


def _analyse(path, request):
    import numpy as np

    findings = []
    shape = request.get("wrapped")
    if shape is None:
        raise ccx.SolverFailed("No shape was handed to the analysis")

    # First order and nothing else: CalculiX's CFD solver takes linear elements.
    mesh = ccx.mesh_shape(shape, request.get("mesh_size", 0.05), 1)
    mesh.element_type = "F3D4"

    boundary = request.get("boundary") or []
    walls = [record for record in boundary if record.get("fix")]
    driven = [record for record in boundary if record.get("load")]

    if not walls:
        raise ccx.SolverFailed(
            "'cfd:' names no wall, so the fluid has nothing to flow along: name the wall interfaces under 'fix:'"
        )
    if not driven:
        raise ccx.SolverFailed(
            "'cfd:' names nothing to drive the flow: name an inlet under 'load:' with the force behind it"
        )

    radius = request.get("port_radius", 0.05)
    wall_sets, wall_empty = ccx.port_node_sets(mesh, walls, radius)
    driven_sets, driven_empty = ccx.port_node_sets(mesh, driven, radius)
    for record in wall_empty + driven_empty:
        findings.append(
            {
                "severity": WARNING,
                "message": (
                    "The port is not near any material, so the condition on it did nothing. "
                    "Check where the port is placed, or raise 'port_radius'."
                ),
                "where": record.get("port") or record.get("interface_label") or "a port",
            }
        )
    if not wall_sets or not driven_sets:
        raise ccx.SolverFailed(
            "None of the walls or none of the driven ports is near any material. "
            "Check where 'implements:' places them, or raise 'port_radius'."
        )

    with tempfile.TemporaryDirectory() as work:
        deck = _deck(mesh, wall_sets, driven_sets, request, radius)
        results = ccx.run_ccx(deck, work)
        fields = ccx.read_frd(results, {"VELO": 3, "PRESSURE": 1, "STRESS": 1})

        velocities = {
            node: math.sqrt(values[0] ** 2 + values[1] ** 2 + values[2] ** 2) for node, values in fields["VELO"].items()
        }
        if not velocities:
            raise ccx.SolverFailed(
                "CalculiX produced no velocities: the flow did not converge. "
                "A smaller 'time_step' or a longer 'duration' is the usual remedy."
            )
        # CalculiX writes static pressure under 'PRESSURE' for a CFD step, and
        # older versions under 'STRESS'; take whichever came back.
        pressures = fields["PRESSURE"] or fields["STRESS"]

        speed_field = ccx.field_per_node(mesh, velocities)
        ccx.write_glb(path, mesh.coordinates, mesh.surface_triangles(), speed_field, low=0.0)

    peak_speed = float(np.max(speed_field))
    values = [entry[0] for entry in pressures.values()] if pressures else []
    pressure_drop = (max(values) - min(values)) if values else 0.0

    findings.extend(_verdict(peak_speed, pressure_drop, request))
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Peak speed %.3g m/s, pressure drop %.3g Pa, over %d elements"
            % (peak_speed, pressure_drop, len(mesh.elements))
        ],
    }


def _verdict(peak_speed, pressure_drop, request):
    findings = []

    limit = request.get("max_velocity")
    if limit is not None and peak_speed > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": (
                    "The flow reaches %.3g m/s, past the %.3g m/s this geometry is meant to hold."
                    % (peak_speed, float(limit))
                ),
                "where": "peak velocity",
            }
        )

    limit = request.get("max_pressure_drop")
    if limit is not None and pressure_drop > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": (
                    "The pressure drop across the part is %.3g Pa, past the %.3g Pa allowed."
                    % (pressure_drop, float(limit))
                ),
                "where": "pressure drop",
            }
        )
    return findings


def _deck(mesh, wall_sets, driven_sets, request, radius_fraction):
    """The CalculiX CFD deck: the mesh, the fluid, the boundaries, the step."""
    lines = ccx.deck_mesh(mesh)
    for name, nodes, _record in wall_sets + driven_sets:
        lines.extend(ccx.deck_nset(name, nodes))

    lines.extend(
        [
            "*MATERIAL, NAME=FLUID",
            "*FLUID CONSTANTS",
            # Specific heat and conductivity: an isothermal incompressible run
            # does not use either, and CalculiX wants the card all the same.
            "1005., %.9g, 293." % float(request.get("viscosity", 1.82e-5)),
            "*DENSITY",
            "%.9g" % float(request.get("density", 1.204)),
            "*SOLID SECTION, ELSET=EALL, MATERIAL=FLUID",
            "*PHYSICAL CONSTANTS, ABSOLUTE ZERO=0.",
            "*INITIAL CONDITIONS, TYPE=FLUID VELOCITY",
            "NALL, 1, 0.",
            "NALL, 2, 0.",
            "NALL, 3, 0.",
            "*STEP, INCF=1000000",
            "*CFD, STEADY STATE, COMPRESSIBLE=NO",
            "%.9g, %.9g" % (float(request.get("time_step", 0.01)), float(request.get("duration", 1.0))),
        ]
    )

    # No slip: the fluid is held still at every wall node.
    for name, _nodes, _record in wall_sets:
        lines.append("*BOUNDARY")
        lines.append("%s, 1, 3, 0." % name)

    # The driven boundaries, as a static pressure. The area a port's
    # neighbourhood stands for is the disc of the search radius, which is the
    # only area a coordinate frame implies; a port that means something else
    # should say so with its own `port_radius`.
    area = math.pi * (mesh.extent * float(radius_fraction) / ccx.MM_PER_M) ** 2
    for name, _nodes, record in driven_sets:
        pressure = float(record["load"]) / max(area, 1e-12)
        lines.append("*BOUNDARY")
        # Degree of freedom 8 is the static pressure of a CFD node.
        lines.append("%s, 8, 8, %.9g" % (name, pressure))

    lines.extend(
        [
            "*NODE FILE",
            "VF, PSF",
            "*END STEP",
        ]
    )
    return lines


if __name__ == "__partcad_export__":
    pass
