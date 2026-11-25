#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae dynamic`, by FieldCraft: the natural frequencies of one part as it is held.

`fix:` holds the faces its ports cover still in every direction; FieldCraft's
block Lanczos eigensolver (`solve.frequency`) finds the lowest `modes`
frequencies, and the model is the part coloured by its first mode shape, scaled
so that the largest motion is one. A first frequency under `min_frequency` is a
finding: the part would ring with whatever drives it there.
"""

import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import fieldcraft_common as fc  # noqa: E402
from fieldcraft_common import WARNING, support  # noqa: E402

STEP = "Modes"


def process(path, request):
    try:
        return _analyse(path, request)
    except (support.ToolMissing, support.ToolFailed) as e:
        return support.failed(e)


def _analyse(path, request):
    findings = []
    fixed, fixed_records, fixed_empty = support.condition_groups(request, "fix", "fix")
    findings.extend(fc.nothing_covered(record) for record in fixed_empty)
    if not fixed_records:
        # A free part has six rigid-body modes at nought; FieldCraft would find
        # them and nothing about how the part is held.
        raise support.ToolFailed(
            "'dynamic:' holds nothing, so the part is free to float: name at least one interface under 'fix:', "
            "on a port that covers a surface of the part"
        )

    with tempfile.TemporaryDirectory() as work:
        work = fc.case_dir(work)
        mesh, msh = fc.mesh_part(request, fixed, work, int(request.get("mesh_order", 2)))
        replies = fc.run(work, commands_for(request, msh, fixed, work), request)
        points, cells, fields, data = fc.read_vtu(os.path.join(work, "mode1.vtu"))

    frequencies = frequencies_of(replies[-2], data)
    if not frequencies:
        raise support.ToolFailed("FieldCraft found no natural frequency")
    shape = first_mode(fields)
    support.write_glb(path, points, fc.surface(points, cells), shape, low=0.0, high=1.0)

    limit = request.get("min_frequency")
    if limit is not None and frequencies[0] < float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part's first natural frequency is %.4g Hz, under the %.4g Hz it must stay above."
                % (frequencies[0], float(limit)),
                "where": "first mode",
            }
        )
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Natural frequencies %s Hz, over %d elements"
            % (", ".join("%.6g" % f for f in frequencies), mesh.element_count)
        ],
    }


def commands_for(request, msh, fixed, work):
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
                "density": float(request.get("density", 7850)),
            },
        }
    )
    commands.append(fc.solid_section("material"))
    for name in fixed:
        commands.append(
            {
                "command": "model.boundary_condition.create",
                "params": {"name": name, "type": "fixed", "target": {"set": name}},
            }
        )
    procedure = {"type": "frequency", "modes": int(request.get("modes", 6))}
    if request.get("max_frequency") is not None:
        procedure["max_hz"] = float(request["max_frequency"])
    commands.append(
        {
            "command": "model.step.create",
            "params": {"name": STEP, "procedure": procedure, "boundary_conditions": list(fixed), "loads": []},
        }
    )
    solve = {"step": STEP}
    if request.get("mass") in ("consistent", "lumped"):
        solve["mass"] = request["mass"]
    commands.append({"command": "solve.frequency", "params": solve})
    commands.append(
        {
            "command": "results.export.vtu",
            "params": {"step": STEP, "path": os.path.join(work, "mode1.vtu"), "mode": 1, "encoding": "ascii"},
        }
    )
    return commands


def frequencies_of(reply, data=None):
    """The frequencies, Hz, lowest first: from the solve's reply, else from the exported mode's field data."""
    found = []
    for mode in (reply or {}).get("modes") or []:
        if isinstance(mode, dict) and isinstance(mode.get("frequency"), (int, float)):
            found.append(float(mode["frequency"]))
    if not found and data and data.get("frequency"):
        found = [float(value) for value in data["frequency"]]
    return sorted(found)


def first_mode(fields):
    """The first mode's displacement magnitude at every point, the largest one."""
    shape = fc.magnitude(fields.get("mode_shape") or fields.get("displacement") or [])
    if not shape:
        raise support.ToolFailed("FieldCraft wrote no mode shape")
    top = max(shape) or 1.0
    return [value / top for value in shape]


if __name__ == "__partcad_export__":
    pass
