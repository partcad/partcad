#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What can be checked about this package, with and without FieldCraft in the room.

Without it: the MSH 4.1 file FieldCraft is handed (held to its reader's rules by
`fake_fieldcraft.read_msh`), the engine commands each analysis sends, the MCP
session (against `fake_fieldcraft.py`, a stand-in speaking FieldCraft's
protocol), the VTU reader, fetching a release, and how the flow problem is posed
as a box -- and, through the stand-in, each analysis end to end on a real
part: PartCAD's port imprint, gmsh, the session, the file read back and the
model drawn.

With it -- `fieldcraft-cli` on PATH or named by PARTCAD_FIELDCRAFT_BIN, or
fetched when PARTCAD_FIELDCRAFT_TEST_DOWNLOAD=1 -- the example cantilever and
pipe are solved and compared with their closed forms.

Run with `pytest` from this directory, beside an installed `partcad` (for the
sandbox helpers the scripts import; see `conftest.py`).
"""

import io
import json
import math
import os
import stat
import sys
import tarfile

import pytest

support = pytest.importorskip("cae_support", reason="needs a partcad with wrappers/cae_support.py")

import cfd_fieldcraft  # noqa: E402
import dynamic_fieldcraft  # noqa: E402
import fake_fieldcraft  # noqa: E402
import fea_fieldcraft  # noqa: E402
import fieldcraft_common as fc  # noqa: E402
import thermal_fieldcraft  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _text(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


# --------------------------------------------------------------------------- #
# A part, as PartCAD hands it over                                            #
# --------------------------------------------------------------------------- #


def _cantilever(analysis, **extra):
    """The 100x10x10 mm bar of examples/feature_cae, held at x = -50 and loaded or heated at x = +50."""
    build123d = pytest.importorskip("build123d")
    pytest.importorskip("gmsh")
    root = {"port": "root", "location": [[-50, 0, 0], [0, 0, 1], 0]}
    tip = {"port": "tip", "location": [[50, 0, 0], [0, 0, 1], 0]}
    if analysis == "fea":
        boundary = [dict(root, fix=True, load=0.0), dict(tip, fix=False, load=100.0)]
    elif analysis == "dynamic":
        boundary = [dict(root, fix=True)]
    else:
        boundary = [
            dict(root, temperature=20.0, heat=None, convection=None),
            dict(tip, temperature=None, heat=1.0, convection=None),
        ]
    request = {
        "analysis": analysis,
        "wrapped": build123d.Box(100, 10, 10).wrapped,
        "boundary": boundary,
        "youngs_modulus": 2.0e11,
        "poissons_ratio": 0.3,
        "density": 7850,
        "self_weight": False,
        "mesh_size": 0.1,
        "mesh_order": 2,
        "conductivity": 50.0,
        "modes": 6,
        "download": False,
    }
    request.update(extra)
    assert support.prepare(request) == []
    return request


def _pipe(**extra):
    """The bore of examples/feature_cae: 10 mm across, 100 mm long, along Z, driven by 5 mN."""
    build123d = pytest.importorskip("build123d")
    inlet = {"port": "inlet", "location": [[0, 0, -50], [0, 0, 1], 0], "load": 0.005, "fix": False, "outlet": False}
    outlet = {"port": "outlet", "location": [[0, 0, 50], [0, 0, 1], 0], "load": 0.0, "fix": False, "outlet": True}
    request = {
        "analysis": "cfd",
        "wrapped": build123d.Cylinder(5, 100).wrapped,
        "boundary": [inlet, outlet],
        "density": 900.0,
        "viscosity": 0.1,
        "mesh_size": 0.008,
        "download": False,
    }
    request.update(extra)
    assert support.prepare(request) == []
    return request


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """`fieldcraft-cli` is the stand-in, for this test."""
    cli = tmp_path / "bin" / "fieldcraft-cli"
    cli.parent.mkdir()
    cli.write_text(
        "#!%s\nimport sys\nsys.path.insert(0, %r)\nimport fake_fieldcraft\nsys.exit(fake_fieldcraft.main())\n"
        % (sys.executable, HERE)
    )
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(fc.BIN_ENV, str(cli))
    monkeypatch.setattr(fc, "_found", None)
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setenv("PARTCAD_FIELDCRAFT_CASE", str(case))
    return case


def _sent(case):
    return json.loads(_text(case / "commands.json"))


# --------------------------------------------------------------------------- #
# The mesh                                                                    #
# --------------------------------------------------------------------------- #


def test_the_mesh_is_what_fieldcraft_reads(tmp_path):
    request = _cantilever("fea")
    fixed, _records, _empty = support.condition_groups(request, "fix", "fix")
    loaded, _records, _empty = support.condition_groups(request, "load", "load")
    mesh, path = fc.mesh_part(request, {**fixed, **loaded}, str(tmp_path), 2)
    nodes, volumes, sets = fake_fieldcraft.read_msh(_text(path))

    assert len(nodes) == len(mesh.node_tags)
    assert len(volumes) == mesh.element_count
    # Quadratic tetrahedra, gmsh type 11, which FieldCraft reorders itself.
    assert {code for code, _nodes in volumes.values()} == {11}
    assert sets[fc.BODY] == {"dimension": 3, "elements": mesh.element_count, "faces": 0}
    # Each end face is two or more boundary triangles, every one of them a face of a tetrahedron.
    assert sets["fix0"]["faces"] == len(mesh.groups["fix0"]) >= 2
    assert sets["load0"]["faces"] == len(mesh.groups["load0"]) >= 2
    # In metres, as the SI model expects.
    assert max(abs(xyz[0]) for xyz in nodes.values()) == pytest.approx(0.05)


def test_a_face_in_two_groups_is_in_both(tmp_path):
    """Held and loaded at once: two triangles, one in each group's entity."""
    request = _cantilever("fea")
    fixed, _r, _e = support.condition_groups(request, "fix", "fix")
    mesh, path = fc.mesh_part(request, {**fixed, "also": fixed["fix0"]}, str(tmp_path), 1)
    _nodes, _volumes, sets = fake_fieldcraft.read_msh(_text(path))
    assert sets["also"]["faces"] == sets["fix0"]["faces"] > 0


def test_a_surface_triangle_off_the_solid_is_refused_as_fieldcraft_would():
    text = """$MeshFormat
4.1 0 8
$EndMeshFormat
$Entities
0 0 1 1
1 0 0 0 1 1 1 0 0
1 0 0 0 1 1 1 0 0
$EndEntities
$Nodes
1 5 1 5
3 1 0 5
1
2
3
4
5
0 0 0
1 0 0
0 1 0
0 0 1
1 1 1
$EndNodes
$Elements
2 2 1 2
2 1 2 1
1 2 3 5
3 1 4 1
2 1 2 3 4
$EndElements
"""
    with pytest.raises(fake_fieldcraft.Refused, match="matches no volume face"):
        fake_fieldcraft.read_msh(text)


# --------------------------------------------------------------------------- #
# The commands                                                                #
# --------------------------------------------------------------------------- #


def _by(commands, name):
    return [c["params"] for c in commands if c["command"] == name]


def test_a_load_is_a_total_force_on_its_faces_and_weight_is_gravity():
    commands, buckling = fea_fieldcraft.commands_for(
        {"self_weight": True, "density": 2700, "youngs_modulus": 7e10},
        "/w/part.msh",
        {"fix0": [1]},
        {"load0": [2], "load1": [3]},
        [{"load": 49.0}, {"load": 10.0, "force": [0, -6, 8]}],
        "/w",
    )
    assert commands[0] == fc.UNITS and commands[0]["params"]["temperature"] == "°C"
    assert _by(commands, "mesh.import.orphan") == [{"path": "/w/part.msh"}]
    material = _by(commands, "model.material.create")[0]
    assert material["elastic"]["young"] == 7e10 and material["density"] == 2700
    assert _by(commands, "model.boundary_condition.create") == [
        {"name": "fix0", "type": "fixed", "target": {"set": "fix0"}}
    ]
    loads = _by(commands, "model.load.create")
    assert loads[0]["vector"] == [0.0, 0.0, -49.0] and loads[0]["distribution"] == "total"
    assert loads[1]["vector"] == [0.0, -6.0, 8.0]
    assert loads[2] == {"name": "weight", "type": "gravity", "acceleration": [0.0, 0.0, -9.81]}
    step = _by(commands, "model.step.create")[0]
    assert step["boundary_conditions"] == ["fix0"] and step["loads"] == ["load0", "load1", "weight"]
    assert commands[-1]["command"] == "results.export.vtu" and not buckling


def test_a_stated_gravity_replaces_self_weight_and_nought_weighs_nothing():
    assert fea_fieldcraft.gravity_of({"gravity": [0, 0, 0]}) == [0.0, 0.0, 0.0]
    assert fea_fieldcraft.gravity_of({"gravity": [1, 2, 3], "self_weight": False}) == [1.0, 2.0, 3.0]
    assert fea_fieldcraft.gravity_of({"self_weight": "false"}) == [0.0, 0.0, 0.0]
    commands, _ = fea_fieldcraft.commands_for({"self_weight": False}, "m", {"fix0": [1]}, {}, [], "/w")
    assert not [c for c in _by(commands, "model.load.create") if c["type"] == "gravity"]


def test_buckling_is_a_second_step_under_the_same_loads():
    commands, buckling = fea_fieldcraft.commands_for(
        {"buckling": "yes", "buckling_modes": 2}, "m", {"fix0": [1]}, {"load0": [2]}, [{"load": 5.0}], "/w"
    )
    assert buckling and commands[-1] == {"command": "solve.buckle", "params": {"step": fea_fieldcraft.BUCKLE}}
    static, buckle = _by(commands, "model.step.create")
    assert buckle["procedure"] == {"type": "buckle", "modes": 2}
    assert buckle["loads"] == static["loads"] and buckle["boundary_conditions"] == static["boundary_conditions"]


def test_buckling_findings():
    assert fea_fieldcraft.load_factors(
        {"modes": [{"mode": 1, "load_factor": 4.0}, {"mode": 2, "load_factor": 1.5}]}
    ) == [
        1.5,
        4.0,
    ]
    assert fea_fieldcraft._buckling_verdict([0.5], {})[0]["severity"] == fc.ERROR
    assert fea_fieldcraft._buckling_verdict([2.0], {"min_buckling_factor": 3})[0]["severity"] == fc.WARNING
    assert fea_fieldcraft._buckling_verdict([4.0], {"min_buckling_factor": 3}) == []
    assert "no load factor" in fea_fieldcraft._buckling_verdict([], {})[0]["message"]


def test_heat_is_a_flux_over_the_port_area_and_convection_a_film():
    commands = thermal_fieldcraft.commands_for(
        {"ambient_temperature": 25.0, "conductivity": 200.0},
        "m",
        {"temperature0": [1]},
        [{"temperature": 20.0}],
        {"heat0": [2]},
        [{"heat": 1.0, "area": 100.0}],
        {"convection0": [3]},
        [{"convection": 10.0}],
        "/w",
    )
    assert _by(commands, "model.material.create")[0]["thermal"] == {"conductivity": 200.0}
    held = _by(commands, "model.boundary_condition.create")[0]
    assert held == {"name": "temperature0", "type": "temperature", "target": {"set": "temperature0"}, "value": 20.0}
    flux, film = _by(commands, "model.load.create")
    # 1 W over 100 mm^2 is 10 kW/m^2.
    assert flux == {"name": "heat0", "type": "surface_flux", "set": "heat0", "flux": pytest.approx(1e4)}
    assert film == {"name": "convection0", "type": "convection", "set": "convection0", "film": 10.0, "sink": 25.0}
    assert _by(commands, "model.step.create")[0]["procedure"] == {"type": "heat_transfer"}


def test_frequencies_come_from_the_reply_or_the_mode_file():
    assert dynamic_fieldcraft.frequencies_of({"modes": [{"frequency": 900.0}, {"frequency": 813.2}]}) == [813.2, 900.0]
    assert dynamic_fieldcraft.frequencies_of({}, {"frequency": [815.0]}) == [815.0]
    assert dynamic_fieldcraft.first_mode({"mode_shape": [(0, 0, 0), (0, 0, 2), (0, 0, 4)]}) == [0.0, 0.5, 1.0]


def test_nothing_held_is_said_rather_than_solved():
    for module in (fea_fieldcraft, dynamic_fieldcraft):
        result = module.process("/nonexistent.glb", {"boundary": []})
        assert result["success"] is False and "holds nothing" in result["exception"]
    result = thermal_fieldcraft.process("/nonexistent.glb", {"boundary": [{"heat": 1.0, "faces": [{"index": 0}]}]})
    assert result["success"] is False and "nowhere to go" in result["exception"]
    result = cfd_fieldcraft.process("/nonexistent.glb", {"boundary": [{"load": 1.0, "faces": [{"index": 0}]}]})
    assert result["success"] is False and "no outlet" in result["exception"]


# --------------------------------------------------------------------------- #
# The session, and what comes back                                            #
# --------------------------------------------------------------------------- #


def test_a_refused_command_is_named_with_fieldcrafts_reason():
    result = {
        "content": [{"type": "text", "text": json.dumps({"ok": False, "failed": {"index": 1, "error": "no set `x`"}})}],
        "isError": True,
    }
    with pytest.raises(support.ToolFailed, match="'model.section.create': no set `x`"):
        fc.parse_batch(result, [{"command": "model.units"}, {"command": "model.section.create"}])
    with pytest.raises(support.ToolFailed, match="batch too long"):
        fc.parse_batch({"content": [{"type": "text", "text": "batch too long"}], "isError": True}, [])


def test_the_session_speaks_mcp(fake):
    with fc.Session(str(fake)) as session:
        replies = session.batch([fc.UNITS, {"command": "model.material.create", "params": {"name": "m"}}])
        assert replies[1] == {"name": "m"}
        with pytest.raises(support.ToolFailed, match="no set `nowhere`"):
            session.batch(
                [{"command": "model.section.create", "params": {"set": "nowhere", "material": "m", "name": "s"}}]
            )
        # The session survives a refused batch, as FieldCraft's does.
        assert session.batch([{"command": "model.material.create", "params": {"name": "n"}}]) == [{"name": "n"}]
    # What was sent is kept as a script `fieldcraft-cli run` replays.
    script = json.loads(_text(fake / fc.SCRIPT))
    assert [step["command"] for step in script] == [
        "model.units",
        "model.material.create",
        "model.section.create",
        "model.material.create",
    ]


def test_a_cli_that_dies_is_reported_with_what_it_said(tmp_path, monkeypatch):
    cli = tmp_path / "fieldcraft-cli"
    cli.write_text("#!/bin/sh\necho 'error: no GPU and no luck' >&2\nexit 3\n")
    cli.chmod(0o755)
    with pytest.raises(support.ToolFailed, match="no GPU and no luck"):
        with fc.Session(str(tmp_path), executable=str(cli)) as session:
            session.batch([fc.UNITS])


def test_binary_and_ascii_vtu_read_alike(tmp_path):
    import base64
    import struct

    def binary(code, values):
        raw = struct.pack("<%d%s" % (len(values), code), *values)
        return base64.b64encode(struct.pack("<Q", len(raw)) + raw).decode()

    points = [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]
    text = (
        '<VTKFile type="UnstructuredGrid" header_type="UInt64"><UnstructuredGrid>'
        '<FieldData><DataArray type="Float64" Name="frequency" format="binary">%s</DataArray></FieldData>'
        '<Piece><PointData><DataArray type="Float64" Name="temperature" format="binary">%s</DataArray></PointData>'
        '<Points><DataArray type="Float64" NumberOfComponents="3" format="binary">%s</DataArray></Points>'
        '<Cells><DataArray type="Int64" Name="connectivity" format="ascii">0 1 2 3</DataArray>'
        '<DataArray type="Int64" Name="offsets" format="ascii">4</DataArray>'
        '<DataArray type="UInt8" Name="types" format="ascii">10</DataArray></Cells></Piece>'
        "</UnstructuredGrid></VTKFile>"
    ) % (binary("d", [813.25]), binary("d", [1, 2, 3, 4]), binary("d", points))
    path = tmp_path / "r.vtu"
    path.write_text(text)
    read_points, cells, fields, data = fc.read_vtu(str(path))
    assert read_points[3] == (0, 0, 1)
    assert cells == {4: [[0, 1, 2, 3]]}
    assert fc.scalar(fields["temperature"]) == [1, 2, 3, 4]
    assert data["frequency"] == [813.25]
    assert len(fc.surface(read_points, cells)) == 4


# --------------------------------------------------------------------------- #
# Each analysis end to end, against the stand-in                              #
# --------------------------------------------------------------------------- #


def test_fea_end_to_end(fake, tmp_path):
    out = tmp_path / "c.fea.glb"
    result = fea_fieldcraft.process(str(out), _cantilever("fea", buckling=True))
    assert result["success"], result.get("exception")
    assert out.stat().st_size > 0 and out.read_bytes()[:4] == b"glTF"
    assert "Peak von Mises stress 60 MPa" in result["warnings"][0]
    assert "peak displacement 0.2 mm" in result["warnings"][0]
    assert result["warnings"][1] == "Buckling load factors 2.5, 9"
    # 2.5 times the load, under the 3 the part is held to.
    assert [f["where"] for f in result["findings"]] == ["buckling"]
    names = [c["command"] for c in _sent(fake)]
    assert names[:2] == ["model.units", "mesh.import.orphan"] and names[-1] == "solve.buckle"


def test_dynamic_end_to_end(fake, tmp_path):
    out = tmp_path / "c.dynamic.glb"
    result = dynamic_fieldcraft.process(str(out), _cantilever("dynamic", min_frequency=1000))
    assert result["success"], result.get("exception")
    assert result["warnings"][0].startswith("Natural frequencies 900, 1000, 1100")
    assert result["findings"][0]["where"] == "first mode"
    assert out.read_bytes()[:4] == b"glTF"


def test_thermal_end_to_end(fake, tmp_path):
    out = tmp_path / "c.thermal.glb"
    result = thermal_fieldcraft.process(str(out), _cantilever("thermal", max_temperature=30))
    assert result["success"], result.get("exception")
    assert result["warnings"][0].startswith("Temperature from 20 C to 40 C, 1 W put in")
    assert result["findings"][0]["where"] == "hottest point"


def test_cfd_end_to_end(fake, tmp_path):
    out = tmp_path / "p.cfd.glb"
    result = cfd_fieldcraft.process(str(out), _pipe())
    assert result["success"], result.get("exception")
    assert result["warnings"][0].startswith("Flow rate 1.5e-06 m^3/s")
    assert out.read_bytes()[:4] == b"glTF"
    sent = _sent(fake)
    domain = _by(sent, "model.fluid_domain.create")[0]
    # The pipe runs along Z: its ends are the box's Z faces, 5 mN over the bore is 63.66 Pa.
    assert set(domain["faces"]) == {"z_min", "z_max"}
    assert domain["faces"]["z_min"]["pressure"] == pytest.approx(63.66, rel=1e-3)
    assert domain["faces"]["z_max"]["pressure"] == 0.0
    assert domain["min"][2] == pytest.approx(-0.05) and domain["max"][2] == pytest.approx(0.05)
    assert domain["obstacles"] == ["obstacle.stl"]
    assert _by(sent, "solve.fluid")[0]["backend"] == "cpu"


# --------------------------------------------------------------------------- #
# The flow as a box                                                           #
# --------------------------------------------------------------------------- #


def test_a_port_off_the_box_or_curved_is_refused():
    low, high = [-5, -5, -50], [5, 5, 50]
    good = {"port": "a", "faces": [{"normal": [0, 0, -1], "centroid": [0, 0, -50], "area": 78.5}]}
    assert cfd_fieldcraft.box_face(good, low, high) == "z_min"
    inside = {"port": "b", "faces": [{"normal": [0, 0, 1], "centroid": [0, 0, 10], "area": 78.5}]}
    with pytest.raises(support.ToolFailed, match="inside the part's bounding box"):
        cfd_fieldcraft.box_face(inside, low, high)
    curved = {"port": "c", "faces": [{"normal": None, "centroid": [5, 0, 0], "area": 3000}]}
    with pytest.raises(support.ToolFailed, match="curved"):
        cfd_fieldcraft.box_face(curved, low, high)
    slanted = {"port": "d", "faces": [{"normal": [0, 0.6, 0.8], "centroid": [0, 0, 50], "area": 1}]}
    with pytest.raises(support.ToolFailed, match="not along an axis"):
        cfd_fieldcraft.box_face(slanted, low, high)


def test_the_box_is_whole_cells_and_grows_away_from_the_ports():
    low, high = [-5, -5, -50], [5, 5, 50]
    records = [{"area": math.pi * 25}]
    size = cfd_fieldcraft.cell_size({"mesh_size": 0.008}, low, high, records, ["z_min", "z_max"])
    # 0.8 mm asked, 100 mm long: 125 cells exactly.
    assert 100.0 / size == pytest.approx(125)
    box_low, box_high, counts = cfd_fieldcraft.domain(low, high, size, ["z_min", "z_max"])
    assert counts == [13, 13, 125]
    assert box_low[2] == pytest.approx(-0.05) and box_high[2] == pytest.approx(0.05)
    # 13 cells of 0.8 mm across a 10 mm bore: grown 0.2 mm on each side.
    assert box_high[0] - box_low[0] == pytest.approx(0.0104)
    # With the outlet on +X only, X grows towards -X, leaving the outlet where it is.
    box_low, box_high, _ = cfd_fieldcraft.domain([0, 0, 0], [10.3, 1, 1], 1.0, ["x_max"])
    assert box_high[0] == pytest.approx(0.0103) and box_low[0] == pytest.approx(-0.0007)


def test_the_narrowest_port_sets_the_cell():
    size = cfd_fieldcraft.cell_size(
        {"mesh_size": 0.1, "cells_across": 10}, [0, 0, 0], [100, 10, 10], [{"area": math.pi}], []
    )
    assert size == pytest.approx(0.2)


def test_the_obstacle_is_the_box_less_the_part(tmp_path):
    request = _pipe()
    path = tmp_path / "o.stl"
    cfd_fieldcraft.write_obstacle(request["wrapped"], [-0.006, -0.006, -0.05], [0.006, 0.006, 0.05], 0.8, str(path))
    assert path.stat().st_size > 84
    samples, triangles, points = cfd_fieldcraft.wall_samples(request["wrapped"], 0.8, 4000)
    assert len(samples) == len(triangles) == len(points) // 3 > 0
    # Every sample is inside the bore: within its radius, between its ends.
    for x, y, z in samples:
        assert math.hypot(x, y) < 0.005 and -0.05 < z < 0.05


def test_the_run_is_long_enough_to_settle():
    inlets = [("z_min", {"area": math.pi * 25, "faces": [{"centroid": [0, 0, -50], "area": math.pi * 25}]})]
    outlets = [("z_max", {"area": math.pi * 25, "faces": [{"centroid": [0, 0, 50], "area": math.pi * 25}]})]
    timing = cfd_fieldcraft.timing_of({}, inlets, outlets, {"z_min": 63.66}, 900.0, 0.1, [-5, -5, -50], [5, 5, 50])
    # Viscous: R^2/nu = 0.225 s, much shorter than the 5 s the oil takes to pass.
    assert timing["end_time"] == pytest.approx(2.25, rel=1e-3)
    assert timing["window"] < timing["end_time"] / 2


def test_only_fluid_cells_colour_the_walls():
    reply = {
        "points": [
            {"point": [0, 0, 0], "cell": 3, "solid": False, "pressure": 12.5},
            {"point": [0, 0, 1], "cell": 4, "solid": True, "pressure": 0.0},
            {"point": [9, 9, 9], "cell": None},
        ]
    }
    assert cfd_fieldcraft._pressures(reply, 3) == [12.5, None, None]
    # An answer of another length is not matched up point by point.
    assert cfd_fieldcraft._pressures(reply, 2) == []


def test_the_flow_rate_is_what_leaves_through_the_outlets():
    reply = {
        "ports": {
            "faces": [
                {"face": "z_min", "inflow": {"volume_flow": 1.5e-6}, "outflow": {"volume_flow": 0.0}},
                {"face": "z_max", "inflow": {"volume_flow": 1e-9}, "outflow": {"volume_flow": 1.501e-6}},
            ]
        }
    }
    assert cfd_fieldcraft.outflow(reply, ["z_max"]) == pytest.approx(1.5e-6)
    with pytest.raises(support.ToolFailed, match="no flow"):
        cfd_fieldcraft.outflow({}, ["z_max"])


# --------------------------------------------------------------------------- #
# Finding and fetching FieldCraft                                             #
# --------------------------------------------------------------------------- #


def test_a_machine_with_no_fieldcraft_and_no_download_is_told_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "_found", None)
    monkeypatch.delenv(fc.BIN_ENV, raising=False)
    monkeypatch.setenv(fc.CACHE_ENV, str(tmp_path))
    monkeypatch.setattr(fc.shutil, "which", lambda _name: None)
    monkeypatch.setattr(fc, "DIRECTORIES", ())
    with pytest.raises(support.ToolMissing) as raised:
        fc.find_fieldcraft({"download": False})
    message = str(raised.value)
    assert fc.BIN_ENV in message and "releases" in message and fc.FIELDCRAFT_VERSION in message


def _release(member):
    data = b"#!/bin/sh\necho fieldcraft-cli 0.8.1\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as t:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_a_release_is_fetched_checked_and_unpacked(tmp_path, monkeypatch):
    archive = _release("fieldcraft-0.8.1-linux-x86_64/bin/fieldcraft-cli")
    import hashlib

    monkeypatch.setenv(fc.CACHE_ENV, str(tmp_path))
    monkeypatch.setattr(fc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(fc.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(fc, "EXECUTABLE", "fieldcraft-cli")
    name = fc.DOWNLOADS[("Linux", "x86_64")][0]
    monkeypatch.setitem(fc.DOWNLOADS, ("Linux", "x86_64"), (name, hashlib.sha256(archive).hexdigest()))
    asked = []

    def urlopen(url, timeout):
        asked.append(url)
        return io.BytesIO(archive)

    path = fc.download(urlopen)
    assert asked == [fc.RELEASES + name]
    assert path == os.path.join(fc.cache_dir(), "fieldcraft-cli") and os.access(path, os.X_OK)
    assert _text(path, "rb").startswith(b"#!/bin/sh")


def test_a_release_with_the_wrong_checksum_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setenv(fc.CACHE_ENV, str(tmp_path))
    monkeypatch.setattr(fc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(fc.platform, "machine", lambda: "x86_64")
    archive = _release("bin/fieldcraft-cli")
    with pytest.raises(support.ToolFailed, match="does not have the SHA-256"):
        fc.download(lambda url, timeout: io.BytesIO(archive))
    assert not os.path.exists(os.path.join(fc.cache_dir(), fc.EXECUTABLE))


def test_the_pins_are_for_one_version_and_look_like_sha256():
    for name, digest in fc.DOWNLOADS.values():
        assert fc.FIELDCRAFT_VERSION in name
        assert len(digest) == 64 and int(digest, 16) >= 0


def test_the_package_declares_every_analysis_with_its_script():
    import yaml

    config = yaml.safe_load(_text(os.path.join(HERE, "partcad.yaml")))
    for analysis in ("fea", "dynamic", "thermal", "cfd"):
        declared = config["cae"][analysis]
        assert os.path.isfile(os.path.join(HERE, declared["path"]))
        assert declared["extension"] == "glb"
    assert config["cae"]["fea"]["reads"] == ["force", "gravity"]


# --------------------------------------------------------------------------- #
# The analyses themselves, where FieldCraft is                                #
# --------------------------------------------------------------------------- #


def _fieldcraft_here():
    try:
        fc._found = None
        fc.find_fieldcraft({"download": os.environ.get("PARTCAD_FIELDCRAFT_TEST_DOWNLOAD") == "1"})
        return True
    except (support.ToolMissing, support.ToolFailed):
        return False
    finally:
        fc._found = None


needs_fieldcraft = pytest.mark.skipif(not _fieldcraft_here(), reason="needs fieldcraft-cli")


def _measured(result, label):
    assert result["success"], result.get("exception")
    return float(result["warnings"][0].split(label)[1].split()[0].rstrip(","))


@needs_fieldcraft
def test_the_cantilever_deflects_as_a_beam(tmp_path):
    """100 N on a 100x10x10 mm steel bar: PL^3/3EI = 0.2000 mm, 0.2016 mm with shear."""
    request = _cantilever("fea", mesh_size=0.03, download=True)
    result = fea_fieldcraft.process(str(tmp_path / "c.glb"), request)
    assert _measured(result, "peak displacement") == pytest.approx(0.2016, rel=0.01)


@needs_fieldcraft
def test_the_cantilever_rings_as_a_beam(tmp_path):
    """The first bending frequency: (1.875^2 / 2 pi L^2) sqrt(EI / rho A) = 815.4 Hz."""
    request = _cantilever("dynamic", mesh_size=0.03, download=True)
    result = dynamic_fieldcraft.process(str(tmp_path / "c.glb"), request)
    expected = 1.875104**2 / (2 * math.pi * 0.1**2) * math.sqrt(2.0e11 * 0.01**4 / 12 / (7850 * 1e-4))
    assert _measured(result, "Natural frequencies") == pytest.approx(expected, rel=0.01)


@needs_fieldcraft
def test_the_cantilever_warms_as_a_rod(tmp_path):
    """1 W through a 10x10 mm steel bar 100 mm long: P L / k A = 20 K over the root."""
    result = thermal_fieldcraft.process(str(tmp_path / "c.glb"), _cantilever("thermal", download=True))
    assert result["success"], result.get("exception")
    hottest = float(result["warnings"][0].split(" C to ")[1].split(" C")[0])
    assert hottest == pytest.approx(40.0, rel=1e-3)


@needs_fieldcraft
def test_oil_flows_through_the_pipe_as_poiseuille_says(tmp_path):
    """Hagen-Poiseuille: Q = pi R^4 dp / 8 mu L = 1.5625 mL/s."""
    result = cfd_fieldcraft.process(str(tmp_path / "p.glb"), _pipe(download=True))
    flow = _measured(result, "Flow rate")
    assert flow == pytest.approx(1.5625e-6, rel=0.05)
