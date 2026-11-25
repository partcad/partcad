#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae thermal`, by FieldCraft: steady heat conduction through one part.

`temperature:` holds the faces its ports cover at a temperature (Celsius);
`heat:` puts a power (W) in through them, spread evenly over their area;
`convection:` cools them by a film coefficient (W/(m^2*K)) towards
`ambient_temperature`. Every other surface is insulated. Solved by FieldCraft's
heat conduction solver (`solve.heat`); the model is the part coloured by
temperature, and a part hotter than `max_temperature` anywhere is a finding.
"""

import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import fieldcraft_common as fc  # noqa: E402
from fieldcraft_common import WARNING, support  # noqa: E402

STEP = "Heat"


def process(path, request):
    try:
        return _analyse(path, request)
    except (support.ToolMissing, support.ToolFailed) as e:
        return support.failed(e)


def _analyse(path, request):
    findings = []
    held, held_records, held_empty = support.condition_groups(request, "temperature", "temperature")
    heated, heated_records, heated_empty = support.condition_groups(request, "heat", "heat")
    cooled, cooled_records, cooled_empty = support.condition_groups(request, "convection", "convection")
    findings.extend(fc.nothing_covered(record) for record in held_empty + heated_empty + cooled_empty)
    if not held_records and not cooled_records:
        raise support.ToolFailed(
            "'thermal:' gives the heat nowhere to go: hold a surface at a 'temperature:', or cool one by "
            "'convection:', on a port that covers a surface of the part. Without one there is no steady state"
        )

    with tempfile.TemporaryDirectory() as work:
        work = fc.case_dir(work)
        mesh, msh = fc.mesh_part(request, {**held, **heated, **cooled}, work, int(request.get("mesh_order", 2)))
        commands = commands_for(request, msh, held, held_records, heated, heated_records, cooled, cooled_records, work)
        fc.run(work, commands, request)
        points, cells, fields, _data = fc.read_vtu(os.path.join(work, "result.vtu"))

    temperature = fc.scalar(fields.get("temperature", []))
    if not temperature:
        raise support.ToolFailed("FieldCraft wrote no temperatures")
    support.write_glb(path, points, fc.surface(points, cells), temperature)

    hottest, coldest = max(temperature), min(temperature)
    limit = request.get("max_temperature")
    if limit is not None and hottest > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part reaches %.4g C, past the %.4g C it may." % (hottest, float(limit)),
                "where": "hottest point",
            }
        )
    put_in = sum(float(record["heat"]) for record in heated_records)
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Temperature from %.4g C to %.4g C, %.4g W put in, over %d elements"
            % (coldest, hottest, put_in, mesh.element_count)
        ],
    }


def commands_for(request, msh, held, held_records, heated, heated_records, cooled, cooled_records, work):
    """The engine commands: the conductor, a condition per group, a steady heat step, its solve and its export."""
    ambient = float(request.get("ambient_temperature", 20.0))
    commands = fc.import_mesh(msh)
    commands.append(
        {
            "command": "model.material.create",
            "params": {
                "name": "material",
                "thermal": {"conductivity": float(request.get("conductivity", 50.0))},
                "density": float(request.get("density", 7850)),
            },
        }
    )
    commands.append(fc.solid_section("material"))

    conditions, loads = [], []
    for name, record in zip(held, held_records):
        conditions.append(name)
        commands.append(
            {
                "command": "model.boundary_condition.create",
                "params": {
                    "name": name,
                    "type": "temperature",
                    "target": {"set": name},
                    "value": float(record["temperature"]),
                },
            }
        )
    for name, record in zip(heated, heated_records):
        # A power over the area it goes in through: a flux, into the part.
        loads.append(name)
        flux = float(record["heat"]) / (float(record["area"]) * fc.M2_PER_MM2)
        commands.append(
            {
                "command": "model.load.create",
                "params": {"name": name, "type": "surface_flux", "set": name, "flux": flux},
            }
        )
    for name, record in zip(cooled, cooled_records):
        loads.append(name)
        commands.append(
            {
                "command": "model.load.create",
                "params": {
                    "name": name,
                    "type": "convection",
                    "set": name,
                    "film": float(record["convection"]),
                    "sink": ambient,
                },
            }
        )

    commands.append(
        {
            "command": "model.step.create",
            "params": {
                "name": STEP,
                "procedure": {"type": "heat_transfer"},
                "boundary_conditions": conditions,
                "loads": loads,
            },
        }
    )
    commands.append({"command": "solve.heat", "params": {"step": STEP}})
    commands.append(
        {
            "command": "results.export.vtu",
            "params": {"step": STEP, "path": os.path.join(work, "result.vtu"), "encoding": "ascii"},
        }
    )
    return commands


if __name__ == "__partcad_export__":
    pass
