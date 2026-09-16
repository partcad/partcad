#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which layers of a drawing a sketch reads is a parameter, not just a field.

A DXF holds the outline of a part and the lines its bends go along, on layers of
its own. Before this, which of them a sketch read was a field of the
declaration, so reading two of them meant declaring a second sketch - and a
third for the next combination somebody wanted.

They are object-type parameters now: 'include' and 'exclude' are contributed by
the 'dxf' type itself rather than invented by the author of the sketch, so they
exist whether or not the declaration mentions them, and whoever *refers* to the
sketch can set them: 'bends;include=BEND_UP,BEND_DOWN'. The top-level fields
stay exactly what they were, as the default the reference overrides.

Nothing here builds a sketch: what is checked is which layers the factory is
left holding, which is settled while the package is loaded.
"""

import os

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad.factory import ObjectTypeParameterException
from partcad.lint.all import get_partcad_schema
from partcad.project import declare_object_type_parameters
from partcad.shape_config import NO_DEFAULT, as_list, object_type_parameter
from partcad.sketch_factory import SketchFactory
from partcad.sketch_factory_dxf import SketchFactoryDxf
from partcad.utils import format_parameterized_name, parse_parameterized_name


def _package(tmp_path, sketches):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test", "sketches": sketches}))
    for name, sketch in sketches.items():
        (tmp_path / (sketch.get("path") or (name + ".dxf"))).write_text("")
    return pc.Context(str(tmp_path))


def _layers(sketch, name):
    """The layers the DXF factory reads for this sketch, by its own rule."""
    return SketchFactoryDxf.layers(sketch.config, name)


#
# What a declaration says
#


def test_the_top_level_fields_are_the_declared_default(tmp_path):
    """'include:'/'exclude:' go on meaning exactly what they always meant."""
    ctx = _package(
        tmp_path,
        {
            "listed": {"type": "dxf", "include": ["BEND_UP", "BEND_DOWN"]},
            "single": {"type": "dxf", "exclude": "OUTLINE"},
        },
    )
    assert _layers(ctx.get_sketch("//test:listed"), "include") == ["BEND_UP", "BEND_DOWN"]
    assert _layers(ctx.get_sketch("//test:single"), "exclude") == ["OUTLINE"]


def test_a_drawing_with_no_filters_reads_every_layer(tmp_path):
    """Which is what an empty list has always meant here."""
    ctx = _package(tmp_path, {"bends": {"type": "dxf"}})
    sketch = ctx.get_sketch("//test:bends")
    assert _layers(sketch, "include") == []
    assert _layers(sketch, "exclude") == []


def test_the_filters_can_be_declared_as_parameters(tmp_path):
    """The long form, for a sketch that wants to describe its own default."""
    ctx = _package(
        tmp_path,
        {"bends": {"type": "dxf", "parameters": {"include": {"type": "array", "default": ["BEND_UP"]}}}},
    )
    assert _layers(ctx.get_sketch("//test:bends"), "include") == ["BEND_UP"]


#
# What a reference says
#


def test_a_reference_reads_the_layers_it_asks_for(tmp_path):
    """The point of the whole thing: one drawing, read as many ways as needed.

    The sketch declares no parameters at all - the type contributes them - so
    nothing had to be written down in advance for this reference to work.
    """
    ctx = _package(tmp_path, {"bends": {"type": "dxf"}})
    sketch = ctx.get_sketch("//test:bends;include=BEND_UP,BEND_DOWN")
    assert sketch is not None
    assert _layers(sketch, "include") == ["BEND_UP", "BEND_DOWN"]

    # ...and the sketch it asked for is a different sketch from the one that
    # reads everything, which is what keeps the two from sharing a cache entry.
    assert sketch.name != "bends"
    assert sketch.hash.get() != ctx.get_sketch("//test:bends").hash.get()


def test_each_set_of_layers_is_a_sketch_of_its_own(tmp_path):
    """Three references, three objects - not one object read three ways.

    This is what makes the layer filters worth being parameters rather than
    fields. Each instance has to be its own object all the way down, or the
    second reference to a drawing would be answered with the first one's
    geometry: the name is what the package registers it under, and the cache key
    is what its shape is stored under.
    """
    ctx = _package(tmp_path, {"panel": {"type": "dxf"}})
    sketches = [
        ctx.get_sketch("//test:panel"),
        ctx.get_sketch("//test:panel;include=BEND_UP"),
        ctx.get_sketch("//test:panel;include=BEND_DOWN"),
        ctx.get_sketch("//test:panel;include=BEND_UP,BEND_DOWN"),
    ]
    assert all(sketches)
    assert len({s.name for s in sketches}) == len(sketches)
    assert len({s.hash.get() for s in sketches}) == len(sketches)
    assert [_layers(s, "include") for s in sketches] == [
        [],
        ["BEND_UP"],
        ["BEND_DOWN"],
        ["BEND_UP", "BEND_DOWN"],
    ]


def test_each_set_of_layers_renders_to_a_file_of_its_own(tmp_path):
    """...and the file each is written to is its own too.

    The parameters are part of the object's name, so they are part of the file
    named after it - 'panel;include=BEND_UP.svg'. Both characters are legal in
    a filename on every platform PartCAD runs on ('/' and ':' are the ones that
    are not, and neither can appear in an object name). Without this, two
    readings of one drawing would overwrite each other's projection, and the
    first one would also overwrite the base sketch's.
    """
    ctx = _package(tmp_path, {"panel": {"type": "dxf"}})
    paths = [
        ctx.get_sketch(ref)._output_filepath({}, str(tmp_path), ".svg")
        for ref in (
            "//test:panel",
            "//test:panel;include=BEND_UP",
            "//test:panel;include=BEND_DOWN",
            "//test:panel;include=BEND_UP,BEND_DOWN",
        )
    ]
    assert len(set(paths)) == len(paths)
    assert [os.path.basename(path) for path in paths] == [
        "panel.svg",
        "panel;include=BEND_UP.svg",
        "panel;include=BEND_DOWN.svg",
        "panel;include=BEND_UP,BEND_DOWN.svg",
    ]


def test_a_reference_outranks_the_declared_default(tmp_path):
    """Whoever refers to a sketch is the outer of the two, as everywhere else."""
    ctx = _package(tmp_path, {"bends": {"type": "dxf", "include": ["OUTLINE"]}})
    assert _layers(ctx.get_sketch("//test:bends;include=BEND_UP"), "include") == ["BEND_UP"]


def test_a_list_in_a_name_reaches_the_factory_as_a_list(tmp_path):
    """A name holding a comma-separated value, read back as one value.

    The parsing itself is asserted directly below, on
    'parse_parameterized_name'. What this adds is the whole path: the list
    survives being written into a name, parsed out of it, and resolved by the
    factory, and arrives as two layer names rather than as one string or as two
    parameters.

    One filter, because the two are mutually exclusive -- see
    'test_a_reference_setting_both_filters_is_refused', which is where the pair
    is asked about.
    """
    ctx = _package(tmp_path, {"bends": {"type": "dxf"}})
    sketch = ctx.get_sketch("//test:bends;exclude=NOTES,DIMS")
    assert _layers(sketch, "exclude") == ["NOTES", "DIMS"]
    assert SketchFactoryDxf.filters(sketch.config) == ([], ["NOTES", "DIMS"])


def test_a_list_value_survives_being_written_as_a_name():
    """A comma separates parameters, and a list is written with commas in it.

    So a fragment with no '=' continues the value before it. Without that,
    'include=BEND_UP,BEND_DOWN' would parse as a parameter called 'BEND_DOWN' -
    which no object declares, and which used to be rejected moments later.
    """
    assert parse_parameterized_name("bends;include=BEND_UP,BEND_DOWN") == (
        "bends",
        {"include": "BEND_UP,BEND_DOWN"},
    )
    name = format_parameterized_name("bends", {"include": "A,B", "exclude": "C"})
    assert parse_parameterized_name(name) == ("bends", {"include": "A,B", "exclude": "C"})


#
# Which types contribute them
#


def test_a_sketch_type_with_no_layers_rejects_the_parameters(tmp_path, caplog):
    """A layer is a thing a DXF has; an SVG and a script have none.

    Accepted silently, such a parameter would be one the package believed was
    filtering something. It is the per-object failure a rejected part parameter
    is, so the rest of the package goes on loading.
    """
    ctx = _package(
        tmp_path,
        {
            "drawing": {"type": "svg", "path": "drawing.svg", "parameters": {"include": {"type": "array"}}},
            "fine": {"type": "dxf"},
        },
    )
    (tmp_path / "drawing.svg").write_text("")
    with caplog.at_level("ERROR"):
        assert ctx.get_sketch("//test:drawing") is None
    assert "does not accept" in caplog.text
    assert "include" in caplog.text

    # The package is otherwise fine.
    assert ctx.get_sketch("//test:fine") is not None


def test_only_the_registered_names_are_policed(tmp_path):
    """Every other parameter name stays the sketch author's own invention."""
    ctx = _package(
        tmp_path,
        {"drawing": {"type": "svg", "path": "drawing.svg", "parameters": {"included": 1.0}}},
    )
    (tmp_path / "drawing.svg").write_text("")
    assert ctx.get_sketch("//test:drawing") is not None


def test_the_exception_names_the_type_and_the_parameter():
    """What the message has to carry to be actionable."""
    error = ObjectTypeParameterException("sketch", "svg", "drawing", "include")
    assert "sketch type 'svg'" in str(error)
    assert "'include' parameter" in str(error)
    assert "drawing" in str(error)


def test_a_name_the_type_does_not_contribute_is_still_refused(tmp_path, caplog):
    """A typo must stay a typo rather than becoming a parameter nothing reads.

    Only the names the type contributes are declared on the object's behalf, so
    'includes' finds nothing to be and the reference is refused with the message
    it has always had.
    """
    ctx = _package(tmp_path, {"bends": {"type": "dxf"}})
    with caplog.at_level("ERROR"):
        assert ctx.get_sketch("//test:bends;includes=BEND_UP") is None
    assert "parametrize" in caplog.text

    # ...and the same on a sketch that does declare parameters, where it is the
    # setting of the value that refuses it and the message names it.
    ctx = _package(tmp_path, {"other": {"type": "dxf", "parameters": {"include": {"type": "array"}}}})
    with pytest.raises(ValueError, match="includes"):
        ctx.get_sketch("//test:other;includes=BEND_UP")


@pytest.mark.parametrize(
    "written,expected",
    [
        ("BEND_UP", ["BEND_UP"]),
        ("BEND_UP,BEND_DOWN", ["BEND_UP", "BEND_DOWN"]),
        ("BEND_UP, BEND_DOWN", ["BEND_UP", "BEND_DOWN"]),
        ("BEND_UP,", ["BEND_UP"]),
        ("", []),
    ],
)
def test_a_list_written_as_text_is_split_on_commas(tmp_path, written, expected):
    """A reference has only text to write with, so text is what arrives."""
    ctx = _package(tmp_path, {"bends": {"type": "dxf"}})
    reference = "//test:bends" + (";include=%s" % written if written else "")
    assert _layers(ctx.get_sketch(reference), "include") == expected


#
# The mechanism is not the sketch's alone
#


def test_a_part_type_parameter_needs_no_declaration_either(tmp_path):
    """The same rule, on the parameters a *part* type contributes.

    'Project.declare_object_type_parameters' is shared, so a homogeneous part
    that declares no 'parameters:' can still be asked for at a tolerance - which
    it could not be before, because it had nothing to apply the value to.
    Checked here because this is where that machinery is exercised.
    """
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                "parts": {"bracket": {"type": "stl", "manufacturing": {"method": "additive"}}},
            }
        )
    )
    (tmp_path / "bracket.stl").write_text("")
    ctx = pc.Context(str(tmp_path))

    part = ctx.get_part("//test:bracket;tolerance=0.2")
    assert part is not None
    assert part.get_object_type_parameter("tolerance") == pytest.approx(0.2)

    # ...and the part that was not asked keeps the default, and its cache key.
    plain = ctx.get_part("//test:bracket")
    assert plain.get_object_type_parameter("tolerance") == 0.0
    assert "parameters" not in plain.config


def test_a_part_type_that_rejects_the_parameter_still_rejects_it(tmp_path, caplog):
    """A 'step' file states its own material; declaring one is refused as before."""
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test", "parts": {"bracket": {"type": "step"}}}))
    (tmp_path / "bracket.step").write_text("")
    ctx = pc.Context(str(tmp_path))

    with caplog.at_level("ERROR"):
        assert ctx.get_part("//test:bracket;material=steel") is None
    assert "parametrize" in caplog.text


#
# How a list-valued parameter is read, whatever it was written as
#


def test_a_list_declared_as_a_list_is_taken_as_one():
    """The YAML spelling. A reference has only text, but a declaration has YAML.

    Both reach the same reader, so the one that is already a list must not be
    split on commas again - a layer whose name contains one would come apart.
    """
    declared = object_type_parameter(
        {"parameters": {"include": {"default": ["BEND_UP", "BEND_DOWN"]}}},
        {"include": []},
        "include",
        "sketch",
        "panel",
    )
    assert declared == ["BEND_UP", "BEND_DOWN"]


def test_an_empty_entry_is_not_a_layer_called_nothing():
    """A trailing comma is a typo; '' is not a layer anybody drew on."""
    assert as_list(["A", "", None, "B"]) == ["A", "B"]
    assert as_list(("A", "B")) == ["A", "B"]
    assert as_list("A, ,B,") == ["A", "B"]
    assert as_list(None) == []
    # Anything else is the one value it is, rather than being iterated: a number
    # is not a list of digits.
    assert as_list(7) == [7]


def test_a_name_the_type_does_not_contribute_is_not_read():
    """A parameter of the object's own is nobody else's to interpret."""
    assert (
        object_type_parameter({"parameters": {"width": {"default": 5}}}, {"include": []}, "width", "sketch", "s")
        is None
    )


def test_a_type_parameter_that_is_not_declared_falls_back_to_its_default():
    assert object_type_parameter({}, {"include": []}, "include", "sketch", "panel") == []
    assert object_type_parameter({}, {"include": NO_DEFAULT}, "include", "sketch", "panel") is None


def test_a_parameter_that_is_neither_a_number_nor_a_list_is_taken_as_written():
    """Not every object-type parameter is a list; the reader is shared.

    A default that is a plain value says the parameter is a plain value, so
    what the declaration wrote is what it means - no coercion, no splitting.
    """
    assert (
        object_type_parameter(
            {"parameters": {"material": {"default": "steel"}}},
            {"material": "aluminium"},
            "material",
            "part",
            "bracket",
        )
        == "steel"
    )


def test_a_numeric_parameter_refuses_what_is_not_a_number(caplog):
    """And says so, rather than carrying a surprise into the geometry.

    A boolean is caught before 'float()' sees it, because by then 'True' is an
    ordinary 1.0 and nothing can tell it from a number somebody wrote. Either
    way the declared default stands, which is what a type parameter is for.
    """
    accepted = {"tolerance": 0.1}
    for value in (True, "thin", None, [0.2]):
        with caplog.at_level("ERROR"):
            assert (
                object_type_parameter(
                    {"parameters": {"tolerance": {"default": value}}},
                    accepted,
                    "tolerance",
                    "part",
                    "bracket",
                )
                == 0.1
            )
    assert "non-numeric 'tolerance'" in caplog.text
    # ...and a number, however it was written, is the number it is.
    assert (
        object_type_parameter({"parameters": {"tolerance": {"default": "0.5"}}}, accepted, "tolerance", "part", "b")
        == 0.5
    )


#
# What a reference is allowed to declare on the object's behalf
#


def test_a_declaration_the_object_already_made_is_left_alone():
    """The object's own declaration is the one that carries its author's intent.

    A reference setting a value is not a reason to replace the 'desc', the
    'enum' and the default somebody wrote down; it is a reason to supply one
    where there is none. So a name the object already declares is skipped, and
    what was declared stays exactly as it was.
    """
    mine = {"type": "float", "default": 1.0, "desc": "written by the package"}
    config = {"type": "dxf", "parameters": {"include": dict(mine)}}
    declare_object_type_parameters("sketch", config, {"include": "BEND_UP"})
    assert config["parameters"]["include"] == mine


def test_a_reference_declares_what_the_object_left_unsaid():
    """Which is the whole point: 'panel;include=BEND_UP' on a bare sketch."""
    config = {"type": "dxf"}
    declare_object_type_parameters("sketch", config, {"include": "BEND_UP"})
    assert "include" in config["parameters"]


def test_a_parameters_section_that_is_not_a_section_is_not_read_as_one():
    """'parameters: BEND_UP' is malformed, and the schema is what says so.

    It reaches the validator anyway - loading a package does not stop at the
    first thing the schema would have rejected - and a reader that assumed a
    mapping here would raise an AttributeError naming neither the sketch nor
    the mistake. The class stands in for an instance because the guard runs
    before anything instance-specific is touched.
    """
    assert SketchFactory._validate_object_type_parameters(SketchFactory, {"parameters": "BEND_UP"}) is None


def test_a_parametrized_instance_is_not_one_of_the_declarations(tmp_path):
    """'self.sketches' holds instances too, and a README describes a package.

    Asking for 'panel;include=BEND_UP' creates an object and registers it
    beside the declared 'panel', so a package that declares one sketch can be
    holding several by the time a README is written. Each extra one used to get
    a section of its own, find no image - nothing renders one for an instance -
    and warn about a file nobody was going to write.

    'orig_name' is what tells them apart: it is the name of the declaration an
    object came from, so it is an object's own name exactly when the object is
    a declaration. Both halves are checked here - the property the filter reads,
    and the README that reads the filter. (The sections come out empty for a
    package this bare; what matters is which names reach them.)
    """
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                "render": {"readme": {}},
                "sketches": {"panel": {"type": "dxf"}},
                "interfaces": {"m3": {"desc": "Abstract 3mm circular interface", "abstract": True}},
            }
        )
    )
    (tmp_path / "panel.dxf").write_text("")

    ctx = pc.Context(str(tmp_path))
    project = ctx.get_project("//test")
    assert ctx.get_sketch("//test:panel;include=BEND_UP") is not None

    assert set(project.sketches) == {"panel", "panel;include=BEND_UP"}
    # The declaration each of them came from. The instance names the base.
    assert project.sketches["panel"].config.get("orig_name") == "panel"
    assert project.sketches["panel;include=BEND_UP"].config.get("orig_name") == "panel"

    out = tmp_path / "out"
    out.mkdir()
    project.render_readme_async({}, str(out))
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "## Sketches" in readme
    assert "## Interfaces" in readme
    assert "include=BEND_UP" not in readme


#
# What the schema will take
#


def _validate(config):
    jsonschema.validate(instance=config, schema=get_partcad_schema())


def test_the_schema_takes_either_filter_on_its_own():
    _validate({"sketches": {"a": {"type": "dxf", "include": ["BEND_UP"]}}})
    _validate({"sketches": {"b": {"type": "dxf", "exclude": "OUTLINE"}}})
    _validate({"sketches": {"c": {"type": "dxf"}}})


def test_the_schema_refuses_both_filters_on_one_sketch():
    """The DXF importer's own rule, said once in the schema rather than twice.

    The two descriptions in the schema have always stated it, and the
    documentation says it too, but nothing enforced it -- so a drawing
    declaring both was taken by the loader and refused much later, by the
    importer, in its own words. Held here, where the declaration is read.
    """
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate({"sketches": {"a": {"type": "dxf", "include": ["BEND_UP"], "exclude": ["OUTLINE"]}}})


def test_a_reference_setting_both_filters_is_refused(tmp_path):
    """The rule the schema states, on the path the schema never sees.

    The schema holds it for the two *fields*. It cannot hold it for the two
    *parameters*: a reference setting them -- 'panel;include=BEND_UP,exclude=OUTLINE'
    -- is a name, resolved long after the declaration it points at was read,
    and it is `pc lint` that applies the schema rather than the loader.

    It has to be caught somewhere, because nothing downstream does: CadQuery's
    importer raises on both, the wire fallback is reached *by* the face import
    raising, and 'dxf_metadata.is_included' applies both filters rather than
    objecting to them. Uncaught, a reference asking for both would fall back,
    be filtered twice, and come back as a perfectly ordinary sketch under a
    warning about geometry.
    """
    with pytest.raises(Exception, match="only one of them says which layers"):
        SketchFactoryDxf.filters(
            {
                "name": "panel",
                "type": "dxf",
                "parameters": {
                    "include": {"default": "BEND_UP"},
                    "exclude": {"default": "OUTLINE"},
                },
            }
        )

    # And end to end, where the reference is what puts both there.
    ctx = _package(tmp_path, {"panel": {"type": "dxf", "include": ["BEND_UP"]}})
    assert ctx.get_project("//test").get_sketch("panel;include=BEND_UP,exclude=OUTLINE") is None


def test_a_reference_may_choose_the_other_filter(tmp_path):
    """Choosing to select by exclusion is choosing, not conflicting.

    A package declares 'include:' and a reference asks for 'exclude=' instead.
    The reference is deciding how the drawing is read, which is the whole
    reason the parameter exists -- so the declared 'include' goes rather than
    being handed to the importer alongside it, which would refuse a reference
    that said one reasonable thing.
    """
    ctx = _package(tmp_path, {"panel": {"type": "dxf", "include": ["BEND_UP"]}})
    project = ctx.get_project("//test")

    # The declaration on its own is unchanged.
    assert SketchFactoryDxf.filters(project.get_sketch("panel").config) == (["BEND_UP"], [])

    # A reference choosing the other filter replaces it rather than adding to it.
    chosen = project.get_sketch("panel;exclude=OUTLINE")
    assert chosen is not None
    assert SketchFactoryDxf.filters(chosen.config) == ([], ["OUTLINE"])


def test_a_declaration_writing_both_filters_is_refused(tmp_path):
    """The schema says so, but `pc lint` is what runs the schema.

    A package loaded without ever being linted would otherwise carry the
    combination all the way to the importer.
    """
    ctx = _package(tmp_path, {"panel": {"type": "dxf", "include": ["BEND_UP"], "exclude": ["OUTLINE"]}})
    assert ctx.get_project("//test").get_sketch("panel") is None
