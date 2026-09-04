#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae fea`, by CalculiX: a linear static stress analysis of one part.

What PartCAD hands over is in the request:

    wrapped        the part, as a live CAD object
    analysis       "fea"
    fix            what is held still, by interface type
    load           what is pulled on, in newtons -- always newtons, whatever
                   unit the package wrote and whether it wrote a mass or a force
    boundary       one record per port those two named, carrying where it is
                   and which of the two named it
    <parameters>   everything declared on the `fea:` file type in partcad.yaml

and what goes back is a coloured glTF at `path` plus `findings`: what the
analysis has to say about the part. An empty `findings` is a pass, and is what
`pc test`'s `fea` check requires.

Two decisions are worth stating because they are the ones that make an answer
mean something:

* **The loads are what the part declared, and gravity.** A `load:` written as a
  mass is a thing being carried, so it arrives here already weighed
  (`partcad.cae` does that, at 9.8 N/kg). Whether the part's own weight is added
  is `self_weight`, on by default: a shelf that carries 5 kg is also a shelf.

* **A port is a neighbourhood, not a face.** A PartCAD port is a coordinate
  frame -- it says where a bolt goes, not which surface it clamps -- so a fixed
  port becomes the mesh nodes within `port_radius` of it, and a loaded port
  spreads its force over the nodes in the same neighbourhood. A port that
  reaches no material at all is reported as a finding, because a solver told to
  hold nothing still answers with nonsense rather than with an error.
"""

import tempfile

import calculix_common as ccx

# The severities a finding carries. PartCAD does not interpret them -- any
# finding at all fails `pc test` -- but they order the list `pc cae` prints and
# colour the one the IDE shows.
ERROR = "error"
WARNING = "warning"
INFO = "info"


def process(path, request):
    try:
        return _analyse(path, request)
    except (ccx.SolverMissing, ccx.SolverFailed) as e:
        # Not a verdict on the part: the machine has no solver, or the solver
        # could not answer. Reported as the sentence it carries, which is what
        # `pc cae` prints and the IDE's FEA tab shows.
        return ccx.failed(e)


def _analyse(path, request):
    import numpy as np

    findings = []
    shape = request.get("wrapped")
    if shape is None:
        raise ccx.SolverFailed("No shape was handed to the analysis")

    mesh = ccx.mesh_shape(shape, request.get("mesh_size", 0.05), request.get("mesh_order", 2))

    boundary = request.get("boundary") or []
    fixed = [record for record in boundary if record.get("fix")]
    loaded = [record for record in boundary if record.get("load")]

    if not fixed:
        # Nothing to react against: every node would move together and the
        # stiffness matrix is singular. Said here rather than left to CalculiX,
        # which reports it as a numbering error about a node.
        raise ccx.SolverFailed(
            "'fea:' fixes nothing, so the part is free to float: name at least one interface under 'fix:'"
        )

    fixed_sets, fixed_empty = ccx.port_node_sets(mesh, fixed, request.get("port_radius", 0.05))
    loaded_sets, loaded_empty = ccx.port_node_sets(mesh, loaded, request.get("port_radius", 0.05))
    for record in fixed_empty + loaded_empty:
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
    if not fixed_sets:
        raise ccx.SolverFailed(
            "None of the fixed ports is near any material: the part is free to float. "
            "Check where 'implements:' places them, or raise 'port_radius'."
        )

    with tempfile.TemporaryDirectory() as work:
        deck = _deck(mesh, fixed_sets, loaded_sets, request)
        results = ccx.run_ccx(deck, work)
        fields = ccx.read_frd(results, {"DISP": 3, "STRESS": 6})

        stress = {node: ccx.von_mises(values) for node, values in fields["STRESS"].items()}
        displacement = {
            node: (values[0] ** 2 + values[1] ** 2 + values[2] ** 2) ** 0.5 for node, values in fields["DISP"].items()
        }
        if not stress:
            raise ccx.SolverFailed("CalculiX produced no stresses: the analysis did not converge")

        stress_field = ccx.field_per_node(mesh, stress)
        ccx.write_glb(path, mesh.coordinates, mesh.surface_triangles(), stress_field, low=0.0)

    peak_stress = float(np.max(stress_field))
    # Displacement comes back in metres, like everything else in the deck; a
    # reader thinks in millimetres.
    peak_displacement = max(displacement.values(), default=0.0) * ccx.MM_PER_M

    findings.extend(_verdict(peak_stress, peak_displacement, request))
    return {
        "success": True,
        "findings": findings,
        # Reported whether or not there is a finding: "it passed, at 62% of
        # yield" and "it passed, at 3%" are different answers.
        "warnings": [
            "Peak von Mises stress %.3g MPa, peak displacement %.3g mm, over %d elements"
            % (peak_stress / 1e6, peak_displacement, len(mesh.elements))
        ],
    }


def _verdict(peak_stress, peak_displacement, request):
    """What the numbers mean, as findings.

    The thresholds are parameters of the file type, so a package that knows its
    own material and its own tolerance for movement says so once in its `cae:`
    section instead of arguing with a default on every part.
    """
    findings = []
    yield_strength = float(request.get("yield_strength", 2.5e8))
    safety_factor = float(request.get("safety_factor", 1.5))
    allowable = yield_strength / max(safety_factor, 1e-9)

    if peak_stress > yield_strength:
        findings.append(
            {
                "severity": ERROR,
                "message": (
                    "The part yields under this load: peak stress %.3g MPa against a yield strength "
                    "of %.3g MPa." % (peak_stress / 1e6, yield_strength / 1e6)
                ),
                "where": "peak von Mises stress",
            }
        )
    elif peak_stress > allowable:
        findings.append(
            {
                "severity": WARNING,
                "message": (
                    "The part does not reach the safety factor of %.2f: peak stress %.3g MPa against "
                    "an allowable %.3g MPa." % (safety_factor, peak_stress / 1e6, allowable / 1e6)
                ),
                "where": "peak von Mises stress",
            }
        )

    limit = request.get("max_displacement")
    if limit is not None and peak_displacement > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": (
                    "The part moves %.3g mm under this load, past the %.3g mm it is allowed."
                    % (peak_displacement, float(limit))
                ),
                "where": "peak displacement",
            }
        )
    return findings


def _deck(mesh, fixed_sets, loaded_sets, request):
    """The CalculiX input deck: the mesh, the material, the conditions, the step."""
    lines = ccx.deck_mesh(mesh)

    for name, nodes, _record in fixed_sets + loaded_sets:
        lines.extend(ccx.deck_nset(name, nodes))

    lines.extend(
        [
            "*MATERIAL, NAME=PART",
            "*ELASTIC",
            "%.9g, %.9g" % (float(request.get("youngs_modulus", 2.1e11)), float(request.get("poissons_ratio", 0.30))),
            "*DENSITY",
            "%.9g" % float(request.get("density", 7850)),
            "*SOLID SECTION, ELSET=EALL, MATERIAL=PART",
            "*STEP",
            "*STATIC",
        ]
    )

    # Every degree of freedom of every node of a fixed port. A PartCAD 'fix:' is
    # "held", with no way to say "held in one direction only" -- and a fixture
    # that is described more loosely than it is built is the one that flatters
    # the part, so the encastre is the honest reading.
    for name, _nodes, _record in fixed_sets:
        lines.append("*BOUNDARY")
        lines.append("%s, 1, 3, 0.0" % name)

    for name, nodes, record in loaded_sets:
        # The force is spread evenly over the neighbourhood, and it is a force on
        # the port rather than per node: a finer mesh must not load the part
        # harder. Along -Z, which is where a weight goes: PartCAD's `load:` is a
        # magnitude, and a direction is not something a part can state yet.
        share = float(record["load"]) / len(nodes)
        lines.append("*CLOAD")
        lines.append("%s, 3, %.9g" % (name, -share))

    if request.get("self_weight", True):
        # 9.81 m/s^2 along -Z. Note that this is the solver's gravity and not
        # `partcad.cae.GRAVITY`, which is the number a *declaration* of a mass is
        # weighed by; they are the same quantity to two figures and neither
        # should be derived from the other.
        lines.append("*DLOAD")
        lines.append("EALL, GRAV, 9.81, 0., 0., -1.")

    lines.extend(
        [
            "*NODE FILE",
            "U",
            "*EL FILE",
            "S",
            "*END STEP",
        ]
    )
    return lines


# Importable as a module by its sibling, and executed by PartCAD's meta-wrapper
# under the run name below -- so nothing here runs on import.
if __name__ == "__partcad_export__":
    pass
