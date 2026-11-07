#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The native CAD formats PartCAD reads through cadmpeg, as parts and as assemblies.

What is declared is checked without a sandbox: which formats are built-in part
and assembly types, that every one of them requires a solid, and that the
scripts' cache versions move with the cadmpeg they run. What they read is
checked by reading real files, and is held against cadmpeg's own account of
those files ('cadmpeg_oracle'): 'cadmpeg measure' of the native file says which
bodies it holds, which of them the document shows and how big each is; 'cadmpeg
diff' of two files PartCAD wrote says whether they are the same geometry.
"""

import asyncio
import importlib.util
import os
import runpy
import sys

import cadmpeg_oracle
import pytest
import yaml
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

import partcad as pc
from partcad import code_version, output

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402

PACKAGE = "tests/partcad/unit/data/import_cadmpeg/partcad.yaml"
DATA = os.path.dirname(PACKAGE)
BUILTIN_IMPORT = cadmpeg_oracle.BUILTIN_IMPORT

# The formats cadmpeg reads into connected solids -- its level L3 and above --
# and the extension each one's parts are stored in, spelled as its own
# application spells it. IGES is one of them too, and is a built-in part type,
# but OpenCASCADE reads it ('test_part_iges.py').
NATIVE_PART_TYPES = {
    "fcstd": "FCStd",
    "f3d": "f3d",
    "sldprt": "SLDPRT",
    "ipt": "ipt",
    "catpart": "CATPart",
    "sat": "sat",
    "pvz": "pvz",
}

# The cadmpeg each script that runs one was last keyed for, and the cache version
# it was keyed with. A new cadmpeg reads a format further, so what these scripts
# produce changes with it: a pin moved without raising them would go on serving
# the parts the last release read.
CADMPEG_KEYED_FOR = "0.6.7"
KEYED_FOR = {"part_fcstd.py": 2, "part_cadmpeg.py": 1, "import_cadmpeg.py": 1}


def _module(script):
    spec = importlib.util.spec_from_file_location("%s_under_test" % script[:-3], os.path.join(BUILTIN_IMPORT, script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builtin():
    with open(os.path.join(BUILTIN_IMPORT, "partcad.yaml")) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# What is declared
# ---------------------------------------------------------------------------


def test_every_format_cadmpeg_reads_into_solids_is_a_builtin_part_type(builtin):
    declared = {name: config["extension"] for name, config in builtin["partTypes"].items()}
    # OpenUSD is a built-in part type too, and cadmpeg reads it, but into
    # meshes rather than solids ('test_part_usd.py').
    assert declared == {**NATIVE_PART_TYPES, "iges": "iges", "usd": "usd"}


def test_every_one_of_them_fails_a_part_that_is_not_a_solid(builtin):
    """How a broken read is caught: by the check every part goes through, made binding."""
    scripts = {"fcstd": "part_fcstd.py", "iges": "part_iges.py"}
    for name, config in builtin["partTypes"].items():
        if name == "usd":
            # What a renderer draws need not close (see 'test_part_usd.py').
            assert not config.get("requireSolid")
            continue
        assert config.get("requireSolid") is True, name
        assert config["path"] == scripts.get(name, "part_cadmpeg.py"), name


def test_the_assembly_types_are_the_formats_cadmpeg_reads_the_components_of(builtin):
    readers = {name: config for name, config in builtin["import"].items() if config["path"] == "import_cadmpeg.py"}
    assert set(readers) == {"f3d", "pvz"}
    for name, config in readers.items():
        assert config["kinds"] == ["assembly"], name
        assert config["binary"] is True, name
        assert config["requireSolid"] is True, name
        assert config["extension"] == name, name
    # Left out on purpose: cadmpeg leaves the files an Inventor assembly's
    # components are in unopened, and does not read a SolidWorks one's tree yet.
    assert not {"iam", "sldasm"} & (set(builtin["import"]) | set(builtin["partTypes"]))


def test_the_scripts_are_keyed_for_the_cadmpeg_they_run():
    tool = _module("cadmpeg_tool.py")
    assert tool.VERSION == CADMPEG_KEYED_FOR, (
        "cadmpeg_tool.py pins cadmpeg %s, and the scripts that run it were keyed for %s. Raise CACHE_VERSION in "
        "each of %s, then update CADMPEG_KEYED_FOR and KEYED_FOR here."
        % (tool.VERSION, CADMPEG_KEYED_FOR, ", ".join(sorted(KEYED_FOR)))
    )
    assert {script: code_version.declared(os.path.join(BUILTIN_IMPORT, script)) for script in KEYED_FOR} == KEYED_FOR


def test_a_cadmpeg_that_never_returns_is_given_up_on(monkeypatch):
    """A converter stuck on a file it cannot read fails the read rather than holding the sandbox forever."""
    step = _module("cadmpeg_step.py")
    monkeypatch.setattr(step, "RUN_TIMEOUT_SECONDS", 1)
    with pytest.raises(RuntimeError, match="did not finish in 1 seconds"):
        step.run([sys.executable, "-c", "import time; time.sleep(60)"])


def test_what_cadmpeg_says_is_read_as_utf8_whatever_the_locale(monkeypatch):
    """A Windows locale's cp1252 cannot decode the units cadmpeg reports in, and the message was lost."""
    step = _module("cadmpeg_step.py")
    cadmpeg_oracle.decode_as_windows_does(monkeypatch)
    says = "import sys; sys.stderr.buffer.write('off by 1e-14 mm\\u2075\\n'.encode()); sys.exit(1)"
    with pytest.raises(RuntimeError, match="off by 1e-14 mm\u2075"):
        step.run([sys.executable, "-c", says])


def test_a_node_is_named_after_what_the_file_calls_it():
    reader = _module("import_cadmpeg.py")
    assert reader.node_name("Lid", "x") == "Lid"
    assert reader.node_name("Lid (2):1", "x") == "Lid_2_1"
    # What OpenCASCADE calls a label nobody named is no name.
    assert reader.node_name("=>[0:1:1:2]", "x") == "x"
    assert reader.node_name("=>[0:1:1:2]_solid3", "x") == "solid3"
    assert reader.node_name("COMPOUND", "x") == "x"
    assert reader.node_name(None, "x") == "x"


def test_a_node_nobody_named_is_named_after_its_place():
    reader = _module("import_cadmpeg.py")
    tree = {
        "type": "assembly",
        "name": "cadmpeg_model",
        "children": [
            {"type": "assembly", "name": "=>[0:1:1:2]", "children": [{"type": "part", "name": "Base"}]},
            {"type": "part", "name": "=>[0:1:1:3]"},
        ],
    }
    named = reader.named(tree, "controller")
    assert named["name"] == "controller"
    assert [child["name"] for child in named["children"]] == ["controller_component1", "controller_part2"]
    assert named["children"][0]["children"][0]["name"] == "Base"


def test_a_part_is_named_after_the_file_it_is_read_from():
    """Two placements of one body are one part; two bodies called alike are two."""
    reader = _module("import_cadmpeg.py")
    tree = {
        "type": "assembly",
        "name": "m",
        "links": [
            {"type": "part", "name": "Bolt", "part_file": "/g/Bolt.step", "location": [[0, 0, 0], [1, 0, 0], 0]},
            {"type": "part", "name": "Bolt", "part_file": "/g/Bolt_1.step", "location": [[5, 0, 0], [1, 0, 0], 0]},
        ],
    }
    links = reader.with_part_types(tree)["links"]
    assert [(link["name"], link["part_type"]) for link in links] == [("Bolt", "step"), ("Bolt_1", "step")]


def test_an_assembly_s_closed_shell_is_its_solid_and_an_open_one_is_left_to_be_judged():
    """As a part type's are: its parts are STEP files, which PartCAD never converts once they are written."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
    from OCP.TopoDS import TopoDS_Compound

    reader = _module("import_cadmpeg.py")
    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    shell = TopExp_Explorer(box, TopAbs_SHELL).Current()
    face = TopExp_Explorer(box, TopAbs_FACE).Current()
    both = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(both)
    builder.Add(both, shell)
    builder.Add(both, face)

    found = reader.bodies(both)

    assert [body.ShapeType() for body in found] == [TopAbs_SOLID, TopAbs_FACE]


def test_a_file_opencascade_cannot_read_is_an_error(tmp_path):
    step = _module("cadmpeg_step.py")
    path = tmp_path / "broken.step"
    path.write_text("not a STEP file\n")
    with pytest.raises(RuntimeError, match="OpenCASCADE could not read broken.step"):
        step.read(str(path))


def test_one_body_is_itself_and_several_are_one_compound():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopAbs import TopAbs_COMPOUND

    step = _module("cadmpeg_step.py")
    small = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    large = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    assert step.compound([small]).IsSame(small)
    both = step.compound([small, large])
    assert both.ShapeType() == TopAbs_COMPOUND
    assert len(step.solids(both)) == 2


def _mapped(shape, kind):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found


def test_what_the_step_file_says_its_bodies_are_in_follows_them_into_the_part(tmp_path):
    """The colours of the file's faces and solids, said of the part's in the part's own order.

    'bodies' regroups what the file holds (solids first, then what bounds no
    solid), so the part's faces and solids are the file's in another order:
    here the two boxes are put back the other way round, and every face and
    solid of the part still carries what the file says of that one.
    """
    import cmf_section
    import step_cmf
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID

    step = _module("cadmpeg_step.py")
    red = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    plain = BRepPrimAPI_MakeBox(gp_Pnt(20.0, 0.0, 0.0), 5.0, 5.0, 5.0).Shape()
    path = str(tmp_path / "two.step")
    step_cmf.write(
        path,
        step.compound([red, plain]),
        cmf_section.Section(
            [cmf_section.CmfSet(color="#C91A09", rgba=(201, 26, 9, 1.0), origin="raw:step")],
            cmf_section.NONE,
            faces=[0] * 6 + [cmf_section.NONE] * 6,
        ),
    )

    shape, facts = step.read(path)
    whole = step_cmf.section_of(shape, facts)
    part = step.compound(list(reversed(step.bodies(shape))))
    stated = step.stated_cmf(part, facts)

    assert stated["convention"] == "step"
    for key, kind, said_of in (("faces", TopAbs_FACE, whole.face_set), ("solids", TopAbs_SOLID, whole.solid_set)):
        in_file, in_part = _mapped(shape, kind), _mapped(part, kind)
        assert len(stated[key]) == in_part.Extent()
        for index in range(1, in_part.Extent() + 1):
            expected = said_of(in_file.FindIndex(in_part.FindKey(index)) - 1).color
            assert (stated[key][index - 1] or {}).get("color") == expected, (key, index)
    # The uncoloured box comes first now, and the red one's faces are the last six.
    assert stated["faces"][:6] == [None] * 6
    assert stated["faces"][6:] == [{"color": "#C91A09", "rgba": [201, 26, 9, 1.0]}] * 6

    assert step.stated_cmf(part, None) is None


def test_the_installer_says_how_it_is_run(monkeypatch, capsys):
    """'cadmpeg_tool.py <directory>' is what the sandbox image's Dockerfile runs."""
    monkeypatch.setattr(sys, "argv", ["cadmpeg_tool.py"])
    with pytest.raises(SystemExit) as exit:
        runpy.run_path(os.path.join(BUILTIN_IMPORT, "cadmpeg_tool.py"), run_name="__main__")
    assert exit.value.code == 2
    said = capsys.readouterr().err  # runpy sets argv[0] to the script's path
    assert said.startswith("usage: ") and said.rstrip().endswith("cadmpeg_tool.py <directory>")


# ---------------------------------------------------------------------------
# The readers as the sandbox runs them, in this process
# ---------------------------------------------------------------------------

# A FreeCAD document of sketches and nothing else: cadmpeg converts it to a STEP
# file with curves in it and no face, which is no body at all.
SKETCHES = "tests/partcad/unit/data/import_fcstd/sketch_constraints.FCStd"


@pytest.fixture(scope="module")
def cache_dir(ctx):
    """Where the sandbox keeps cadmpeg, with the pinned release fetched into it."""
    cadmpeg_oracle.executable(ctx)
    return output.package_cache_dir(ctx, output.builtin_project(ctx, output.IMPORT))


@pytest.mark.slow
def test_the_part_reader_answers_with_the_bodies_or_why_there_are_none(cache_dir, tmp_path):
    """'part_cadmpeg.py' as 'wrapper_part_type.py' runs it: the shape of what a file shows, or the reason."""
    script = os.path.join(BUILTIN_IMPORT, "part_cadmpeg.py")

    def run(path):
        request = {"path": str(path), "cache_dir": cache_dir}
        return runpy.run_path(script, init_globals={"request": request}, run_name="__partcad_part__")["output"]

    shape = run(os.path.join(DATA, "controller.f3d"))["shape"]
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    solids = 0
    while explorer.More():
        solids += 1
        explorer.Next()
    assert solids == 3, "the three bodies the design shows, and not the one it hides"
    # With the colours the design draws them in, from the STEP cadmpeg wrote.
    stated = run(os.path.join(DATA, "controller.f3d"))["cmf"]
    assert stated["convention"] == "step"
    assert "#191919" in {entry["color"] for entry in stated["faces"] if entry}

    assert "holds no solid" in run(SKETCHES)["exception"]

    unreadable = tmp_path / "unreadable.f3d"
    unreadable.write_bytes(b"not a design")
    assert "failed" in run(unreadable)["exception"]


@pytest.mark.slow
def test_the_colours_the_design_states_ride_on_the_part_built_of_it(cache_dir, monkeypatch):
    """'part_cadmpeg.py' run by 'wrapper_part_type' as the sandbox runs it: the part's payload carries its colours."""
    import ocp_serialize
    import wrapper_common

    written = []
    request = {"path": os.path.join(DATA, "controller.f3d"), "cache_dir": cache_dir}
    monkeypatch.setattr(
        wrapper_common, "handle_input", lambda *_a, **_k: (os.path.join(BUILTIN_IMPORT, "part_cadmpeg.py"), request)
    )
    monkeypatch.setattr(wrapper_common, "handle_output", written.append)
    # The wrapper is a script: importing it runs the request it is handed.
    sys.modules.pop("wrapper_part_type", None)
    try:
        importlib.import_module("wrapper_part_type")
    finally:
        sys.modules.pop("wrapper_part_type", None)

    (said,) = written
    assert said["success"], said["exception"]
    (shape,) = said["shapes"]
    carried = ocp_serialize.cmf_of_payload(shape[ocp_serialize.KEY_BREP])
    assert "#191919" in {carried.face_set(index).color for index in range(len(carried.faces))}
    assert {cmf_set.origin for cmf_set in carried.sets} == {"raw:step"}


def _part_nodes(node):
    if node["type"] == "part":
        yield node
    for child in node.get("links") or []:
        yield from _part_nodes(child)


@pytest.mark.slow
def test_the_assembly_reader_writes_a_part_per_body_and_the_tree_that_places_them(cache_dir, tmp_path):
    reader = _module("import_cadmpeg.py")
    request = {
        "source_file": os.path.join(DATA, "controller.f3d"),
        "cache_dir": cache_dir,
        "output_folder": str(tmp_path / "parts"),
    }

    result = reader.process(None, request)

    parts = list(_part_nodes(result["root"]))
    assert len(parts) == 3
    for part in parts:
        assert part["part_type"] == "step"
        assert os.path.isfile(part["part_file"])
        assert part["name"] == os.path.splitext(os.path.basename(part["part_file"]))[0]
    assert result["model_name"] == result["root"]["name"]

    with pytest.raises(RuntimeError, match="shows no body"):
        reader.process(None, {**request, "source_file": SKETCHES})


# ---------------------------------------------------------------------------
# What is read, held against cadmpeg's own account of the files
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(PACKAGE)


@pytest.fixture(scope="module")
def cadmpeg(ctx):
    return cadmpeg_oracle.executable(ctx)


def _built(ctx, shape):
    envelope = asyncio.run(shape.get_wrapped(ctx))
    assert envelope is not None, shape.errors
    return envelope


def _solid_volumes(envelope):
    """What OpenCASCADE measures each solid of a built part at."""
    volumes = []
    explorer = TopExp_Explorer(ocp_serialize.decode_shape(envelope), TopAbs_SOLID)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), props)
        volumes.append(props.Mass())
        explorer.Next()
    return volumes


def _matches(expected, volume):
    """Whether OpenCASCADE's 'volume' is the one cadmpeg measured, within what cadmpeg says it may be off by."""
    return cadmpeg_oracle.same_volume(expected, {"value": volume})


def _exported(ctx, shape, path):
    asyncio.run(shape.render_async(ctx, "step", filepath=str(path)))
    assert os.path.isfile(path)
    return path


def _leaves(assembly):
    for child in assembly.children:
        if getattr(child.item, "children", None):
            yield from _leaves(child.item)
        else:
            yield child.item


@pytest.mark.slow
def test_a_fusion_design_is_the_bodies_it_shows(ctx, cadmpeg):
    """cadmpeg measures the design itself; OpenCASCADE measures the part PartCAD read out of it."""
    read = _solid_volumes(_built(ctx, ctx.get_part(":controller")))

    native = cadmpeg_oracle.measure(cadmpeg, os.path.join(DATA, "controller.f3d"))
    solids = [body for body in native if body["kind"] == "solid"]
    shown = [body for body in solids if body.get("visible") is not False]
    hidden = [body for body in solids if body.get("visible") is False]
    assert hidden, "the fixture holds a hidden body, which is what is left out here"
    assert len(native) > len(solids), "and sketch curves, which are left out too"
    assert len(read) == len(shown)

    matched = 0
    for body in shown:
        expected = cadmpeg_oracle.volume(body)
        if expected is None:
            continue  # cadmpeg could not measure it: data, not a verdict
        assert any(_matches(expected, volume) for volume in read), (expected, read)
        matched += 1
    assert matched, "cadmpeg measured none of the bodies, so nothing was compared"
    for body in hidden:
        expected = cadmpeg_oracle.volume(body)
        assert expected is not None
        assert not any(_matches(expected, volume) for volume in read), "a hidden body was read"


@pytest.mark.slow
def test_a_fusion_design_as_an_assembly_places_each_body_where_the_part_has_it(ctx, cadmpeg, tmp_path):
    assembly = ctx.get_assembly(":controller_assembly")
    # Its tree, which a shape served from the cache does not build.
    asyncio.run(assembly.do_instantiate())
    parts = list(_leaves(assembly))
    assert len(parts) == 3
    # The parts it registers are held to a solid, as the part type's are.
    assert all(part.solid_required for part in parts)

    status, comparison = cadmpeg_oracle.diff(
        cadmpeg,
        _exported(ctx, ctx.get_part(":controller"), tmp_path / "part.step"),
        _exported(ctx, assembly, tmp_path / "assembly.step"),
    )
    assert cadmpeg_oracle.disagreements(comparison) == []
    assert comparison["unmatched_a"] == comparison["unmatched_b"] == comparison["ambiguous"] == []
    # The one thing it may leave undecided is a body it cannot measure at all,
    # and then that body is one of the three on both sides.
    if status != 0:
        assert comparison["verdict"] == "inconclusive"
        assert comparison["inconclusive_causes"] == ["compare.unmeasured-body"]
    assert len(comparison["unmeasured_a"]) == len(comparison["unmeasured_b"])
    assert len(comparison["pairs"]) + len(comparison["unmeasured_a"]) == 3
