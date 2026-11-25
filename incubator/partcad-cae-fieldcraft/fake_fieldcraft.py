#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A stand-in for `fieldcraft-cli mcp`, for the tests: the protocol and the checks, not the physics.

It speaks what FieldCraft's MCP server speaks (`crates/mcp` in its repository):
JSON-RPC 2.0, one message per line, `initialize`, `notifications/initialized`
and `tools/call` of `batch`, answering a batch as `{"ok", "completed",
"results"}` in one text block, or `isError` with `failed.index`,
`failed.command` and `failed.error`.

What makes it worth more than a mock is what it refuses. `mesh.import.orphan`
reads the MSH file with the rules FieldCraft's reader applies
(`crates/io/src/gmsh.rs`): MSH 4.1 ASCII only, every count and tag range
checked, every entity an element or a node names declared, every element type
one FieldCraft reads, and every surface element the face of a volume element.
The definitions are held to their names: a section, a condition or a load
naming a set the mesh did not bring is refused, and so is a step naming a
condition or a load nobody created. The solves answer with made-up numbers in
the shape FieldCraft's replies have, and `results.export.vtu` writes the
imported mesh back with made-up fields, so that everything after the solve --
reading the file, drawing the model -- is exercised for real.

Every command received is appended to `commands.json` in the read root.
"""

import json
import math
import os
import sys

SUPPORTED = {1: 2, 8: 3, 2: 3, 9: 6, 3: 4, 16: 8, 4: 4, 11: 10, 6: 6, 5: 8, 17: 20}
DIMENSION = {1: 1, 8: 1, 2: 2, 9: 2, 3: 2, 16: 2, 4: 3, 11: 3, 6: 3, 5: 3, 17: 3}
CORNERS = {1: 2, 8: 2, 2: 3, 9: 3, 3: 4, 16: 4, 4: 4, 11: 4, 6: 6, 5: 8, 17: 8}


class Refused(Exception):
    pass


def read_msh(text):
    """Nodes, elements and sets, by FieldCraft's reader's rules; 'Refused' naming the first broken one."""
    sections = {}
    lines = text.splitlines()
    k = 0
    while k < len(lines):
        header = lines[k].strip()
        k += 1
        if not header:
            continue
        if not header.startswith("$") or header.startswith("$End"):
            raise Refused("MSH line %d: expected a section header" % k)
        name = header[1:]
        body = []
        while k < len(lines) and lines[k].strip() != "$End" + name:
            body.append(lines[k])
            k += 1
        if k >= len(lines):
            raise Refused("missing $End%s" % name)
        k += 1
        sections[name] = body

    form = " ".join(sections.get("MeshFormat", [])).split()
    if form[:1] != ["4.1"]:
        raise Refused("MSH version %s not supported; expected 4.1" % (form[:1] or ["?"])[0])
    if form[1:2] != ["0"]:
        raise Refused("MSH file type must be 0 (ASCII)")
    if form[2:3] not in (["4"], ["8"]):
        raise Refused("MSH data size must be 4 or 8")

    names = {}
    for line in sections.get("PhysicalNames", [])[1:]:
        dim, tag, quoted = line.split(None, 2)
        if not (quoted.startswith('"') and quoted.endswith('"')):
            raise Refused("expected a quoted physical name")
        if (int(dim), int(tag)) in names:
            raise Refused("duplicate physical name")
        names[(int(dim), int(tag))] = quoted[1:-1]

    entities = {}
    if "Entities" in sections:
        tokens = " ".join(sections["Entities"]).split()
        counts = [int(t) for t in tokens[:4]]
        at = 4
        for d, n in enumerate(counts):
            for _ in range(n):
                tag = int(tokens[at])
                at += 1 + (3 if d == 0 else 6)
                nphys = int(tokens[at])
                physical = [int(t) for t in tokens[at + 1 : at + 1 + nphys]]
                at += 1 + nphys
                if d > 0:
                    at += 1 + int(tokens[at])
                if (d, tag) in entities:
                    raise Refused("duplicate entity tag %d in dimension %d" % (tag, d))
                entities[(d, tag)] = physical
        if at != len(tokens):
            raise Refused("unexpected trailing section data in $Entities")

    referenced = set()
    tokens = " ".join(sections.get("Nodes", [])).split()
    if not tokens:
        raise Refused("missing $Nodes or $Elements")
    blocks, count, low, high = (int(t) for t in tokens[:4])
    at = 4
    nodes = {}
    for _ in range(blocks):
        dim, entity, parametric, n = (int(t) for t in tokens[at : at + 4])
        at += 4
        referenced.add((dim, entity))
        tags = [int(t) for t in tokens[at : at + n]]
        at += n
        for tag in tags:
            xyz = [float(t) for t in tokens[at : at + 3]]
            at += 3 + parametric * dim
            if tag in nodes:
                raise Refused("duplicate node tag %d" % tag)
            if not all(math.isfinite(v) for v in xyz):
                raise Refused("coordinate must be finite")
            nodes[tag] = xyz
    if at != len(tokens) or len(nodes) != count or min(nodes) != low or max(nodes) != high:
        raise Refused("node count or tag range does not match the $Nodes header")

    tokens = " ".join(sections.get("Elements", [])).split()
    if not tokens:
        raise Refused("missing $Nodes or $Elements")
    blocks, count, low, high = (int(t) for t in tokens[:4])
    at = 4
    records = {}
    for _ in range(blocks):
        dim, entity, code, n = (int(t) for t in tokens[at : at + 4])
        at += 4
        referenced.add((dim, entity))
        if code not in SUPPORTED:
            raise Refused("unsupported element type %d" % code)
        if DIMENSION[code] != dim:
            raise Refused("element type %d does not have entity dimension %d" % (code, dim))
        for _ in range(n):
            tag = int(tokens[at])
            connectivity = [int(t) for t in tokens[at + 1 : at + 1 + SUPPORTED[code]]]
            at += 1 + SUPPORTED[code]
            for node in connectivity:
                if node not in nodes:
                    raise Refused("element %d: missing node %d" % (tag, node))
            if len(set(connectivity)) != len(connectivity):
                raise Refused("element %d: duplicate node" % tag)
            if tag in records:
                raise Refused("duplicate element tag %d" % tag)
            records[tag] = (dim, entity, code, connectivity)
    if at != len(tokens) or len(records) != count or min(records) != low or max(records) != high:
        raise Refused("element count or tag range does not match the $Elements header")

    if entities:
        for key in referenced:
            if key not in entities:
                raise Refused("missing entity (%d, %d)" % key)

    dimension = max(dim for dim, _e, _c, _n in records.values())
    if dimension != 3:
        raise Refused("this stand-in reads volume meshes only")
    faces = set()
    for dim, _entity, code, connectivity in records.values():
        if dim == 3:
            corners = connectivity[: CORNERS[code]]
            if CORNERS[code] == 4:
                for skip in range(4):
                    faces.add(tuple(sorted(c for i, c in enumerate(corners) if i != skip)))
    sets = {}
    for tag, (dim, entity, code, connectivity) in records.items():
        if dim == 2 and tuple(sorted(connectivity[: CORNERS[code]])) not in faces:
            raise Refused("surface element %d matches no volume face" % tag)
        for physical in entities.get((dim, entity), []):
            name = names.get((dim, physical), "physical_%d_%d" % (dim, physical))
            members = sets.setdefault(name, {"dimension": dim, "elements": 0, "faces": 0})
            members["faces" if dim == 2 else "elements"] += 1
    volumes = {tag: (code, connectivity) for tag, (dim, _e, code, connectivity) in records.items() if dim == 3}
    return nodes, volumes, sets


class Model:
    def __init__(self, root):
        self.root = root
        self.nodes, self.volumes, self.sets = {}, {}, {}
        self.names = {"material": set(), "boundary_condition": set(), "load": set(), "step": {}, "surface": set()}
        self.solved = set()

    def execute(self, command, params):
        handler = getattr(self, command.replace(".", "_"), None)
        if handler is None:
            raise Refused("unknown command `%s`" % command)
        return handler(params)

    def _path(self, params):
        path = params.get("path", "")
        if not os.path.abspath(path).startswith(self.root):
            raise Refused("`%s` is outside the automation roots" % path)
        return path

    def _set(self, name):
        if name not in self.sets:
            raise Refused("no set `%s` (sets: %s)" % (name, ", ".join(sorted(self.sets))))

    def model_units(self, params):
        if params.get("system") != "m-kg-s-N-Pa":
            raise Refused("this stand-in answers in SI only")
        return {"system": params["system"], "temperature": params.get("temperature")}

    def mesh_import_orphan(self, params):
        with open(self._path(params)) as f:
            self.nodes, self.volumes, self.sets = read_msh(f.read())
        return {
            "nodes": len(self.nodes),
            "elements": len(self.volumes),
            "sets": [dict(name=k, **v) for k, v in self.sets.items()],
        }

    def model_material_create(self, params):
        self.names["material"].add(params["name"])
        return {"name": params["name"]}

    def model_section_create(self, params):
        self._set(params["set"])
        if params["material"] not in self.names["material"]:
            raise Refused("no material `%s`" % params["material"])
        return {"name": params["name"]}

    def model_boundary_condition_create(self, params):
        self._set(params["target"]["set"])
        self.names["boundary_condition"].add(params["name"])
        return {"name": params["name"]}

    def model_load_create(self, params):
        if params.get("type") != "gravity":
            self._set((params.get("target") or {}).get("set") or params.get("set"))
        self.names["load"].add(params["name"])
        return {"name": params["name"]}

    def model_step_create(self, params):
        for kind, key in (("boundary_condition", "boundary_conditions"), ("load", "loads")):
            for name in params.get(key) or []:
                if name not in self.names[kind]:
                    raise Refused("step `%s` names no %s `%s`" % (params["name"], kind, name))
        self.names["step"][params["name"]] = params["procedure"]
        return {"name": params["name"]}

    def _solve(self, params, kind):
        step = params.get("step")
        if self.names["step"].get(step, {}).get("type") != kind:
            raise Refused("no %s step `%s`" % (kind, step))
        self.solved.add(step)

    def solve_static(self, params):
        self._solve(params, "static")
        return {
            "step": params["step"],
            "max_von_mises": {"node": 1, "value": 6.0e7},
            "max_displacement": {"node": 1, "value": 2.0e-4},
        }

    def solve_buckle(self, params):
        self._solve(params, "buckle")
        return {"step": params["step"], "modes": [{"mode": 1, "load_factor": 2.5}, {"mode": 2, "load_factor": 9.0}]}

    def solve_frequency(self, params):
        self._solve(params, "frequency")
        modes = self.names["step"][params["step"]].get("modes", 6)
        return {
            "step": params["step"],
            "modes": [{"mode": k, "frequency": 800.0 + 100.0 * k} for k in range(1, modes + 1)],
        }

    def solve_heat(self, params):
        self._solve(params, "heat_transfer")
        return {"step": params["step"], "min_temperature": {"value": 20.0}, "max_temperature": {"value": 40.0}}

    def results_export_vtu(self, params):
        step = params.get("step")
        if step not in self.solved:
            raise Refused("step `%s` is not solved" % step)
        kind = self.names["step"][step]["type"]
        path = self._path(params)
        write_vtu(path, self.nodes, self.volumes, kind)
        return {"files": [path], "points": len(self.nodes), "cells": len(self.volumes)}

    def geometry_import_mesh(self, params):
        name = os.path.basename(self._path(params))
        self.names["surface"].add(name)
        return {"surfaces": [{"index": 0, "name": name}], "unit": params.get("unit", "mm")}

    def model_fluid_domain_create(self, params):
        for name in params.get("obstacles") or []:
            if name not in self.names["surface"]:
                raise Refused("no obstacle `%s`" % name)
        for axis in range(3):
            cells = (params["max"][axis] - params["min"][axis]) / params["spacing"]
            if abs(cells - round(cells)) > 1e-6:
                raise Refused("every extent must be a whole number of spacings")
        self.domain = params
        return {"name": params["name"]}

    def solve_fluid(self, params):
        self._solve(params, "fluid")
        faces = []
        for face, condition in self.domain["faces"].items():
            out = 1.5e-6 if condition.get("pressure", 0) == 0 else 0.0
            faces.append({"face": face, "inflow": {"volume_flow": 1.5e-6 - out}, "outflow": {"volume_flow": out}})
        return {
            "execution": "completed",
            "max_speed": 0.04,
            "final_max_speed": 0.04,
            "stop": {"reason": "steady"},
            "ports": {"faces": faces},
        }

    def solve_probe(self, params):
        points = params.get("points", [])
        if len(points) > 10000:
            raise Refused("at most 10000 points")
        return {
            "step": params["step"],
            "points": [{"point": p, "cell": k, "solid": False, "pressure": 30.0 + p[2]} for k, p in enumerate(points)],
        }


def write_vtu(path, nodes, volumes, kind):
    labels = sorted(nodes)
    index = {label: k for k, label in enumerate(labels)}
    xmin = min(nodes[label][0] for label in labels)
    span = (max(nodes[label][0] for label in labels) - xmin) or 1.0
    points = " ".join("%r %r %r" % tuple(nodes[label]) for label in labels)
    connectivity, offsets, types, end = [], [], [], 0
    for _tag, (code, connectivity_tags) in sorted(volumes.items()):
        connectivity.extend(index[t] for t in connectivity_tags)
        end += len(connectivity_tags)
        offsets.append(end)
        types.append({4: 10, 11: 24, 5: 12, 17: 25, 6: 13}[code])
    # Nought at the end with the smallest X, one at the other: a made-up field
    # with known extremes, so that what is read back can be checked.
    along = [(nodes[label][0] - xmin) / span for label in labels]
    arrays = []
    if kind == "static":
        arrays.append(("displacement", 3, " ".join("0 0 %r" % (-2e-4 * a) for a in along)))
        arrays.append(("von_mises", 1, " ".join("%r" % (6e7 * (1 - a)) for a in along)))
    elif kind == "frequency":
        arrays.append(("mode_shape", 3, " ".join("0 0 %r" % a for a in along)))
    elif kind == "heat_transfer":
        arrays.append(("temperature", 1, " ".join("%r" % (20 + 20 * a) for a in along)))
    arrays.append(("has_result", 1, " ".join("1" for _ in labels)))
    point_data = "".join(
        '<DataArray type="Float64" Name="%s" NumberOfComponents="%d" format="ascii">%s</DataArray>' % array
        for array in arrays
    )
    field = '<FieldData><DataArray type="Float64" Name="frequency" NumberOfTuples="1" format="ascii">900</DataArray></FieldData>'
    with open(path, "w") as f:
        f.write(
            '<?xml version="1.0"?>\n<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" '
            'header_type="UInt64"><UnstructuredGrid>%s<Piece NumberOfPoints="%d" NumberOfCells="%d">'
            '<PointData>%s</PointData><Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">%s'
            '</DataArray></Points><Cells><DataArray type="Int64" Name="connectivity" format="ascii">%s</DataArray>'
            '<DataArray type="Int64" Name="offsets" format="ascii">%s</DataArray>'
            '<DataArray type="UInt8" Name="types" format="ascii">%s</DataArray></Cells></Piece>'
            "</UnstructuredGrid></VTKFile>\n"
            % (
                field if kind == "frequency" else "",
                len(labels),
                len(types),
                point_data,
                points,
                " ".join(map(str, connectivity)),
                " ".join(map(str, offsets)),
                " ".join(map(str, types)),
            )
        )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] != ["mcp", "--headless"] or "--automation-read-root" not in argv:
        sys.stderr.write("fake fieldcraft-cli: unexpected arguments %s\n" % argv)
        return 2
    root = os.path.abspath(argv[argv.index("--automation-read-root") + 1])
    model = Model(root)
    log = os.path.join(root, "commands.json")
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        method, params = message.get("method"), message.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion"), "serverInfo": {"name": "fieldcraft"}}
        elif method == "tools/call" and params.get("name") == "batch":
            commands = params["arguments"]["commands"]
            done = []
            if os.path.exists(log):
                with open(log) as f:
                    done = json.load(f)
            with open(log, "w") as f:
                json.dump(done + commands, f, indent=1)
            results, failure = [], None
            for index, step in enumerate(commands):
                try:
                    results.append(model.execute(step["command"], step.get("params") or {}))
                except (Refused, KeyError, OSError, ValueError) as e:
                    failure = {"index": index, "command": step.get("command"), "error": str(e)}
                    break
            body = {"ok": failure is None, "completed": len(results), "results": results}
            if failure:
                body["failed"] = failure
            result = {"content": [{"type": "text", "text": json.dumps(body)}]}
            if failure:
                result["isError"] = True
        else:
            print(
                json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": method}}),
                flush=True,
            )
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
