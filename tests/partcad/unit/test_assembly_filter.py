#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for 'partcad.assembly_filter': a view of an assembly, as an assembly.

What is pinned here is that a view *is* an assembly -- the same objects, in the
same places, under the same name and configuration -- and that the mask selects
the same links it selects in an ASSY file (``partcad_utils.assy_filter``, tested
beside it). The two halves have to agree: a filtered render and the filtered
copy ``pc filter`` writes should hold the same parts.
"""

import asyncio

import pytest

import partcad as pc
from partcad import assembly_filter
from partcad.assembly import Assembly, AssemblyChild
from partcad.geom import Location
from partcad.scene import Scene
from partcad_utils import assy_filter

# A package with a named container and an unnamed one in the same file, which is
# the distinction the mask turns on.
PACKAGE = "tests/partcad/unit/data/assembly_ports/partcad.yaml"


def filtered(assembly, spec):
    return asyncio.run(assembly_filter.filtered_async(assembly, assy_filter.of(spec)))


def links(assembly):
    return assembly.link_names()


def inner(assembly, index=0):
    return links(assembly.children[index].item)


# ---- derive ----------------------------------------------------------------


def test_derive_holds_the_children_it_is_handed():
    source = Assembly("//pkg", {"name": "widget", "type": "assy"})
    children = [AssemblyChild(object(), "a", Location()), AssemblyChild(object(), "b", Location())]
    view = assembly_filter.derive(source, children)

    assert links(view) == ["a", "b"]
    # Nothing re-reads a declaration for it: 'do_instantiate()' finds the
    # children already there and leaves them alone.
    asyncio.run(view.do_instantiate())
    assert links(view) == ["a", "b"]


def test_derive_keeps_the_name_and_the_declaration_of_what_it_is_a_view_of():
    # Which is what makes a filtered render land in the file the unfiltered one
    # would have, and keeps the file types the package configured applying.
    source = Assembly("//pkg", {"name": "widget", "type": "assy", "render": {"svg": {}}})
    view = assembly_filter.derive(source, [])
    assert view.name == "widget"
    assert view.project_name == "//pkg"
    assert view.config.get("render") == {"svg": {}}


def test_derive_is_never_cacheable():
    # Its identity is "that assembly, minus these links", which no declaration
    # states and no cache key covers.
    source = Assembly("//pkg", {"name": "widget", "type": "assy", "cache": True})
    view = assembly_filter.derive(source, [])
    assert view.cacheable is False


def test_derive_takes_a_declaration_of_its_own():
    source = Assembly("//pkg", {"name": "widget", "type": "assy", "render": {"svg": {}}})
    view = assembly_filter.derive(source, [], config={"name": "widget-step-2", "child": True})
    assert view.name == "widget-step-2"
    assert view.config.get("child") is True
    assert "render" not in view.config


def test_a_view_of_a_scene_is_a_scene():
    # Everything branches on the kind: the shape cache keys on it, the renderer
    # maps it to the 'scenes:' section, and the viewer labels the object with it.
    source = Scene("//pkg", {"name": "bench", "type": "assy"})
    view = assembly_filter.derive(source, [])
    assert isinstance(view, Scene)
    assert view.kind == "scene"


# ---- filtering a built assembly --------------------------------------------


def test_no_filter_is_the_assembly_itself():
    ctx = pc.init(PACKAGE)
    grouped = ctx._get_assembly(":grouped")
    assert asyncio.run(assembly_filter.filtered_async(grouped, None)) is grouped
    assert asyncio.run(assembly_filter.filtered_async(grouped, assy_filter.KEEP_ALL)) is grouped


def test_a_named_container_is_selected_by_its_name():
    ctx = pc.init(PACKAGE)
    grouped = ctx._get_assembly(":grouped")
    asyncio.run(grouped.do_instantiate())
    # 'frame' names itself; the second 'links:' names itself nothing and is
    # therefore addressed by where it is written.
    assert links(grouped) == ["frame", "link#2"]

    view = filtered(grouped, {"frame": None})
    assert links(view) == ["frame"]
    assert inner(view) == ["plate"]


def test_selecting_inside_a_named_container():
    ctx = pc.init(PACKAGE)
    view = filtered(ctx._get_assembly(":grouped"), {"frame": {"plate": None}})
    assert links(view) == ["frame"]
    assert inner(view) == ["plate"]


def test_a_container_that_names_itself_nothing_is_selected_by_its_position():
    ctx = pc.init(PACKAGE)
    view = filtered(ctx._get_assembly(":grouped"), {"link#2": {"loose": None}})
    # Kept under the name it was selected by, not renumbered to 'link#1' by
    # having become the only child: the panel composed the mask out of the
    # labels it was showing, and those are what the view has to keep.
    assert links(view) == ["link#2"]
    assert inner(view) == ["loose"]


def test_every_level_names_its_own_links():
    ctx = pc.init(PACKAGE)
    view = filtered(ctx._get_assembly(":grouped"), ["frame", "link#2"])
    assert links(view) == ["frame", "link#2"]
    assert inner(view, 0) == ["plate"]
    assert inner(view, 1) == ["loose"]


def test_a_view_keeps_each_child_where_the_assembly_put_it():
    ctx = pc.init(PACKAGE)
    grouped = ctx._get_assembly(":grouped")
    asyncio.run(grouped.do_instantiate())
    before = {child.name: tuple(child.location.translation) for child in grouped.children[0].item.children}

    view = filtered(grouped, {"frame": None})
    after = {child.name: tuple(child.location.translation) for child in view.children[0].item.children}
    assert after == before


def test_a_name_that_is_no_link_is_reported(caplog):
    ctx = pc.init(PACKAGE)
    with caplog.at_level("ERROR"):
        view = filtered(ctx._get_assembly(":grouped"), ["nosuch"])
    assert "nosuch" in caplog.text
    assert links(view) == []


def test_a_child_nothing_named_is_addressed_by_its_position():
    """A view of an assembly PartCAD did not read from an ASSY file.

    'add()' names nothing, and neither does a STEP or URDF reader that found no
    label, so 'Assembly.link_name' positions those children - which is what
    makes a filtered render of such an assembly possible at all.
    """
    source = Assembly("//pkg", {"name": "built", "type": "assy"})
    source.children.append(AssemblyChild(object(), None, Location()))
    source.children.append(AssemblyChild(object(), None, Location()))
    source.instantiate = lambda _: True

    view = asyncio.run(assembly_filter.filtered_async(source, assy_filter.of({"link#2": None})))
    assert links(view) == ["link#2"]
    assert view.children[0].item is source.children[1].item


def test_a_part_has_nothing_inside_it_to_select(caplog):
    ctx = pc.init(PACKAGE)
    with caplog.at_level("ERROR"):
        view = filtered(ctx._get_assembly(":grouped"), {"frame": {"plate": {"anything": None}}})
    assert "'plate' is a part" in caplog.text
    # Reported, and the part is kept whole rather than dropped.
    assert inner(view) == ["plate"]


def test_a_filtered_scene_is_still_a_scene():
    ctx = pc.init("examples")
    bench = ctx._get_scene("//produce_scene_assy:bench")
    view = filtered(bench, ["block"])
    assert isinstance(view, Scene)
    assert view.kind == "scene"
    assert links(view) == ["block"]


@pytest.mark.slow
def test_a_view_builds_as_an_assembly_does():
    # The point of making a view an 'Assembly' rather than a list of shapes: it
    # goes through the very same machinery, so every operation on an assembly
    # works on it.
    ctx = pc.init(PACKAGE)
    view = filtered(ctx._get_assembly(":grouped"), {"frame": None})
    wrapped = asyncio.run(view.get_wrapped(ctx))
    assert wrapped is not None

    whole = asyncio.run(ctx._get_assembly(":grouped").get_wrapped(ctx))
    # One plate rather than two, and under the name the object has.
    from partcad import shape_envelope

    assert len(wrapped[shape_envelope.KEY_ASSEMBLY]) == 1
    assert len(whole[shape_envelope.KEY_ASSEMBLY]) == 2
    assert wrapped["label"] == whole["label"]


# ---- a filter a file type declares ----------------------------------------
#
# The other way to ask for a subset: 'filter:' on a 'render:'/'export:' file
# type, in either place a file type is configured. Per file type, which is the
# whole point -- one object can have a picture of one sub-assembly checked in
# beside the drawing of the whole of it.


def _impl(config):
    from partcad import output

    return output.Implementation(output.RENDER, "svg", config)


def test_a_file_type_declares_which_links_it_is_of():
    assert _impl({}).link_filter is None
    assert _impl({"filter": ["base"]}).link_filter.names() == ["base"]
    assert _impl({"filter": {"tower": {"upper": None}}}).link_filter.select("tower").names() == ["upper"]


def test_the_field_is_partcads_own_and_not_the_implementations():
    # The implementation is handed the shape the filter leaves rather than the
    # whole one and a note about it, so it never sees the field.
    assert "filter" not in _impl({"filter": ["base"], "precision": 4}).parameters
    assert _impl({"filter": ["base"], "precision": 4}).parameters == {"precision": 4}


def test_a_declaration_that_is_not_a_mask_is_refused():
    # Rather than taken for "keep everything", which would render the whole
    # object and say nothing.
    with pytest.raises(ValueError):
        _impl({"filter": 7}).link_filter


def test_a_filter_means_nothing_for_a_part_and_says_so(caplog):
    ctx = pc.init(PACKAGE)
    plate = ctx.get_part("//:plate")
    with caplog.at_level("ERROR"):
        same = asyncio.run(plate.filtered_view_async(assy_filter.of(["anything"])))
    assert same is plate
    assert "a part has none" in caplog.text or "and a part has none" in caplog.text


def test_one_subset_is_built_once_however_many_file_types_ask_for_it():
    """What the per-call view cache is for.

    Two file types declaring the same 'filter:' are one subset; the key is the
    mask's ('Filter.key'), so the second asks for what the first built.
    """
    ctx = pc.init(PACKAGE)
    grouped = ctx._get_assembly(":grouped")
    views = {}
    mask = assy_filter.of(["frame"])

    first = asyncio.run(grouped._output_subject_async(ctx, {"name": "tree"}, mask, views))
    second = asyncio.run(grouped._output_subject_async(ctx, {"name": "tree"}, assy_filter.of({"frame": {}}), views))
    assert first[0] is second[0]
    assert len(views) == 1

    # No filter at all is the object itself and the tree the caller already had.
    subject, tree, _ = asyncio.run(grouped._output_subject_async(ctx, {"name": "tree"}, None, views))
    assert subject is grouped and tree == {"name": "tree"}
