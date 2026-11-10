#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An assembly or a scene as one part: its compound (see 'partcad.assembly_compound').

Pinned here:

- what the sandbox makes of a tree ('wrapper_transform.flatten'): every leaf
  placed where the tree puts it, in one shape, and each leaf's CMF on its own
  faces there, the colour a node lends included;
- that the transform's other operations are still handed live geometry, now
  that the wrapper reads its request raw;
- what the core makes of an object: a part under the object's name, keyed on it
  and on the code that flattens it, that is the object itself for anything that
  is one shape already, and that a file type and a run both ask for;
- end to end, through the sandbox: a 'compound' part is one shape, and an
  assembly exported '--compound' to STEP is one product.
"""

import asyncio
import os
import re
import sys
import types

import pytest

import partcad as pc
from partcad import assembly_compound, output
from partcad.assembly import Assembly
from partcad.part import Part

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))


def _kernel():
    pytest.importorskip("OCP")
    pytest.importorskip("build123d")
    import build123d as bd

    return bd


# ---------------------------------------------------------------- the sandbox


def _wall():
    """An assembly: a red aluminium brick placed twice, a peg its node draws blue, and the same peg in nothing."""
    bd = _kernel()
    import ocp_serialize
    from cmf_section import CmfSet, Section

    red = CmfSet(color="//src:signal-red", origin="declared", rgba=(201, 26, 9, 1.0))
    aluminium = CmfSet(material="//src:al-6061", origin="declared")
    brick = ocp_serialize.encode_shape(
        bd.Box(10, 20, 30).wrapped, name="//src:brick", label="brick", cmf=Section([red.filled_from(aluminium)], 0)
    )
    peg = ocp_serialize.encode_shape(bd.Cylinder(3, 10).wrapped, name="//src:peg", label="peg")
    return ocp_serialize.encode_assembly(
        [
            dict(brick, location=[[0, 0, 0], [0, 0, 1], 0], label="left"),
            dict(brick, location=[[0, 40, 0], [0, 0, 1], 0], label="right"),
            dict(peg, location=[[0, 0, 40], [0, 0, 1], 0], label="peg", properties={"color": "#0000FF"}),
            dict(peg, location=[[0, 0, 80], [0, 0, 1], 0], label="bare"),
        ],
        name="//src:wall",
        label="wall",
    )


def _count(shape, kind):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found.Extent()


def _box(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    return [round(value, 6) for value in box.Get()]


def test_a_flattened_tree_is_every_leaf_where_the_tree_puts_it():
    _kernel()
    import wrapper_transform
    from OCP.TopAbs import TopAbs_SOLID

    whole, _cmf = wrapper_transform.flatten(_wall())

    assert _count(whole, TopAbs_SOLID) == 4
    # The bricks from y=0 to y=60, the pegs up to z=90 (centred cylinders of
    # radius 3 and height 10, the second at z=80).
    assert _box(whole) == [-5.0, -10.0, -15.0, 5.0, 50.0, 85.0]


def test_a_flattened_tree_keeps_each_leaf_s_cmf_on_its_own_faces():
    _kernel()
    import wrapper_transform
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS_Iterator
    from OCP.TopTools import TopTools_IndexedMapOfShape

    whole, cmf = wrapper_transform.flatten(_wall())
    assert cmf is not None

    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(whole, TopAbs_FACE, faces)
    pieces = []
    iterator = TopoDS_Iterator(whole)
    while iterator.More():
        pieces.append(iterator.Value())
        iterator.Next()

    def sets_of(piece):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(piece, TopAbs_FACE, found)
        return {cmf.face_set(faces.FindIndex(found.FindKey(i + 1)) - 1) for i in range(found.Extent())}

    left, right, peg, bare = (sets_of(piece) for piece in pieces)
    # Both placements of the brick, in what the brick states.
    assert {(s.color, s.material) for s in left} == {("//src:signal-red", "//src:al-6061")}
    assert left == right
    # The peg in the colour its node lends it, which is a display and no reference.
    assert {(s.color, s.rgba) for s in peg} == {(None, (0, 0, 255, 1.0))}
    # And the same peg, placed where no node colours it, in nothing.
    assert {(s.color, s.material, s.rgba) for s in bare} == {(None, None, None)}


def test_a_flattened_tree_that_states_no_cmf_has_none():
    bd = _kernel()
    import ocp_serialize
    import wrapper_transform

    box = ocp_serialize.encode_shape(bd.Box(1, 1, 1).wrapped, name="//src:box", label="box")
    tree = ocp_serialize.encode_assembly([box, dict(box, location=[[5, 0, 0], [0, 0, 1], 0])], name="//src:two")

    _whole, cmf = wrapper_transform.flatten(tree)

    assert cmf is None


def test_flatten_answers_one_shape_carrying_its_cmf():
    _kernel()
    import ocp_serialize
    import wrapper_transform

    answer = wrapper_transform.process({"operation": "flatten", "shape": _wall()})

    assert ocp_serialize.is_shape_object(answer)
    assert ocp_serialize.cmf_of_payload(answer[ocp_serialize.KEY_BREP]) is not None
    assert answer[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_MEASUREMENTS]["solids"] == 4


def test_the_other_operations_are_still_handed_live_geometry():
    """The wrapper reads its request raw now, for 'flatten'; every other operation decodes it as before."""
    bd = _kernel()
    import ocp_serialize
    import wrapper_transform
    from OCP.TopAbs import TopAbs_SOLID

    box = ocp_serialize.encode_shape(bd.Box(1, 1, 1).wrapped, name="//src:box", label="box")
    other = dict(box, location=[[5, 0, 0], [0, 0, 1], 0])

    assert _count(wrapper_transform.process({"operation": "compound", "shapes": [box, other]}), TopAbs_SOLID) == 2
    moved = wrapper_transform.process({"operation": "offset", "shape": box, "offset": [[10, 0, 0], [0, 0, 1], 0]})
    assert _box(moved)[0] == pytest.approx(9.5)


# ---------------------------------------------------------------- the core


def _assembly(name="wall", **config):
    config = dict({"name": name, "type": "assy", "path": "%s.assy" % name}, **config)
    return Assembly("//src", config)


def test_the_compound_of_an_assembly_is_a_part_named_after_it():
    assembly = _assembly(desc="A wall", export={"step": {"comment": "walls"}})

    view = assembly_compound.view(assembly)

    assert isinstance(view, Part)
    assert (view.kind, view.project_name, view.name) == ("part", "//src", "wall")
    assert view.derived_from is assembly
    assert view.artifact_identity == assembly_compound.IDENTITY
    # What names it and the file types configured for it, and not what makes it an assembly.
    assert view.config["desc"] == "A wall"
    assert view.config["export"] == {"step": {"comment": "walls"}}
    assert "path" not in view.config
    assert view.config["type"] == "compound"
    assert view.config["source"] == "//src:wall"


def test_one_object_has_one_compound():
    assembly = _assembly()

    assert assembly_compound.view(assembly) is assembly_compound.view(assembly)


def test_the_compound_of_one_shape_is_that_shape():
    part = Part("//src", {"name": "brick", "type": "step"})

    assert assembly_compound.view(part) is part
    assert not assembly_compound.applies(part)


def test_a_compound_of_something_not_cached_is_not_cached():
    view = assembly_compound.view(_assembly(cache=False))

    assert view.config.get("cache") is False
    assert not view.get_cacheable()


def test_a_compound_is_keyed_on_the_code_that_flattens_it():
    view = assembly_compound.view(_assembly())

    assert assembly_compound.code_versions() is not None
    assert "transform.py@" in assembly_compound.code_versions()
    # The same key every time it is asked, and not the assembly's.
    assert view.hash.get() != _assembly().hash.get()


def test_a_compound_is_not_closed_into_solids_on_the_way_out():
    """Every part in it was finished as itself; a STEP part's reported shell stays the shell it was."""
    view = assembly_compound.view(_assembly())

    assert view.finish_request()["validate"] == {"solidify": False}


def test_the_identity_the_core_reads_is_the_module_s():
    from partcad import shape

    assert shape._COMPOUND_IDENTITY == assembly_compound.IDENTITY


def test_the_compound_field_of_a_file_type_is_partcad_s_own():
    impl = output.Implementation(output.EXPORT, "step", {"path": "x.py", "compound": True, "tolerance": 0.1})

    assert impl.compound is True
    assert "compound" not in impl.parameters
    assert impl.parameters["tolerance"] == 0.1
    assert output.Implementation(output.EXPORT, "step", {"path": "x.py"}).compound is False


def test_a_compound_field_that_is_not_a_flag_is_refused():
    impl = output.Implementation(output.EXPORT, "step", {"path": "x.py", "compound": "sometimes"})

    with pytest.raises(ValueError, match="compound"):
        impl.compound


def _subject(shape, compound, monkeypatch):
    """What '_output_subject_async' hands an output file of 'shape', with the compound's tree stubbed."""

    async def tree(self, ctx):
        return {"name": "compound of " + self.source.name, "brep": b""}

    monkeypatch.setattr(assembly_compound.CompoundView, "get_wrapped", tree)
    return asyncio.run(shape._output_subject_async(None, {"assembly": []}, None, {}, compound))


def test_an_output_file_asked_for_the_compound_is_of_the_compound(monkeypatch):
    assembly = _assembly()

    subject, obj, ports = _subject(assembly, True, monkeypatch)

    assert subject is assembly_compound.view(assembly)
    assert obj == {"name": "compound of wall", "brep": b""}
    assert ports == {}


def test_an_output_file_not_asked_for_the_compound_is_of_the_tree(monkeypatch):
    assembly = _assembly()

    subject, obj, _ports = _subject(assembly, False, monkeypatch)

    assert subject is assembly
    assert obj == {"assembly": []}


def test_a_part_asked_for_its_compound_is_itself(monkeypatch):
    part = Part("//src", {"name": "brick", "type": "step"})

    subject, obj, _ports = _subject(part, True, monkeypatch)

    assert subject is part
    assert obj == {"assembly": []}


# ---------------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def examples():
    return pc.init("examples")


def test_a_compound_part_is_one_shape(examples):
    import ocp_serialize

    part = examples.get_part("//produce_assembly_assy:primitive_compound")
    envelope = asyncio.run(part.get_wrapped(examples))

    # One shape, not the assembly's tree under the part's name.
    assert ocp_serialize.is_shape_object(envelope)
    assert envelope[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_MEASUREMENTS]["solids"] == 2


def test_an_assembly_exported_as_its_compound_is_one_step_product(examples, tmp_path):
    assembly = examples.get_assembly("//produce_assembly_assy:primitive")

    results = asyncio.run(assembly.render_async(examples, "step", output_dir=str(tmp_path), compound=True))
    assert results["step"]["success"], results
    asyncio.run(assembly.render_async(examples, "step", filepath=str(tmp_path / "tree.step")))

    def products(name):
        return re.findall(r"PRODUCT\('([^']*)'", (tmp_path / name).read_text(encoding="utf-8"))

    # Under the assembly's own name, and one product, where the tree is one per part and one for the assembly.
    assert products("primitive.step") == ["primitive"]
    assert sorted(products("tree.step")) == ["cube", "cylinder", "primitive"]


def test_a_file_of_the_compound_is_not_the_file_of_the_tree(examples, tmp_path):
    """The two are cached apart: asking for one never hands back the other."""
    assembly = examples.get_assembly("//produce_assembly_assy:primitive")

    asyncio.run(assembly.render_async(examples, "step", filepath=str(tmp_path / "tree.step")))
    asyncio.run(assembly.render_async(examples, "step", filepath=str(tmp_path / "flat.step"), compound=True))
    asyncio.run(assembly.render_async(examples, "step", filepath=str(tmp_path / "tree2.step")))

    def count(name):
        return len(re.findall(r"PRODUCT\('", (tmp_path / name).read_text(encoding="utf-8")))

    assert (count("tree.step"), count("flat.step"), count("tree2.step")) == (3, 1, 3)


def test_a_file_type_written_for_one_shape_is_handed_the_compound(examples, tmp_path, monkeypatch):
    """'compound: true' on a file type implies the compound, without the run asking for it."""
    assembly = examples.get_assembly("//produce_assembly_assy:primitive")
    real = output.Implementation.compound
    monkeypatch.setattr(
        output.Implementation, "compound", property(lambda impl: impl.format_name == "step" or real.fget(impl))
    )

    asyncio.run(assembly.render_async(examples, "step", filepath=str(tmp_path / "implied.step")))

    assert re.findall(r"PRODUCT\('([^']*)'", (tmp_path / "implied.step").read_text(encoding="utf-8")) == ["primitive"]


# ---------------------------------------------------------------- ad hoc


def _converted(monkeypatch, *args, **kwargs):
    from partcad.adhoc import convert

    written = []
    monkeypatch.setattr(convert, "write_output_file", lambda *a, **k: written.append((a, k)))
    convert.convert_cad_file(*args, **kwargs)
    return written


def test_an_adhoc_compound_reads_the_input_as_an_assembly(monkeypatch):
    ((args, kwargs),) = _converted(monkeypatch, "robot.urdf", "urdf", "robot.stl", "stl", compound=True)

    assert args[:4] == ("robot.urdf", "urdf", "robot.stl", "stl")
    assert kwargs["kind"] == "assembly"
    assert kwargs["compound"] is True


def test_a_urdf_means_something_ad_hoc_only_as_its_compound(monkeypatch):
    with pytest.raises(ValueError, match="only means anything inside a package"):
        _converted(monkeypatch, "robot.urdf", "urdf", "robot.stl", "stl")


@pytest.mark.parametrize(
    "input_type, output_type",
    [("assy", "stl"), ("step", "urdf")],
)
def test_what_only_a_package_reads_is_refused_ad_hoc_even_as_a_compound(monkeypatch, input_type, output_type):
    with pytest.raises(ValueError, match="only means anything inside a package"):
        _converted(monkeypatch, "in." + input_type, input_type, "out." + output_type, output_type, compound=True)


def test_a_step_assembly_converted_ad_hoc_as_its_compound(tmp_path):
    from partcad.adhoc.convert import convert_cad_file

    source = os.path.join("examples", "feature_import", "AeroAssembly.step")
    target = tmp_path / "AeroAssembly.brep"

    convert_cad_file(source, "step", str(target), "brep", compound=True)

    assert target.exists() and target.stat().st_size > 0


def test_an_adhoc_compound_of_an_assembly_that_failed_says_why(tmp_path, monkeypatch):
    """What the assembly recorded is the reason its compound is empty, and is what is reported."""
    from partcad.adhoc import adhoc
    from partcad.project import Project

    failed = types.SimpleNamespace(errors=["the link 'base' names a mesh that is not there"])
    empty = types.SimpleNamespace(errors=[])

    async def nothing(ctx):
        return None

    empty.get_wrapped = nothing
    monkeypatch.setattr(Project, "get_assembly", lambda self, name, *args, **kwargs: failed)
    monkeypatch.setattr(assembly_compound, "view", lambda source: empty if source is failed else source)
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='robot'/>")

    with pytest.raises(RuntimeError, match="names a mesh that is not there"):
        adhoc.write_output_file(str(source), "urdf", str(tmp_path / "robot.stl"), "stl", kind="assembly", compound=True)
