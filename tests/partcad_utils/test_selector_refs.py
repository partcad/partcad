#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'partcad_utils.selector_refs': which CadQuery and build123d selections a comment may point at.

A selection is evaluated with 'eval()' in a sandbox, so the grammar is what keeps
evaluating one from being anything but a call of the library's own selectors.
What the selections then select is 'tests/partcad/unit/test_element_refs.py'.
"""

import pathlib

import pytest

import partcad
from partcad_utils import comments, selector_refs


@pytest.mark.parametrize(
    "ref",
    [
        'faces(">Z")',
        "edges('|Z and >X')",
        'faces("%PLANE").faces(">Z[-2]")',
        'edges("<X").edges("<Y")',
        'faces(">(0.9659,0.2588,0)")',
        'edges("|Z").first()',
        'faces(">Z").item(2)',
        'vertices(">X and >Y")',
    ],
)
def test_a_cadquery_selection_is_a_chain_of_string_selectors(ref):
    assert selector_refs.classify(ref) == (selector_refs.CADQUERY, None)


@pytest.mark.parametrize(
    "ref",
    [
        "faces().sort_by(Axis.Z)[-1]",
        "edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[0]",
        "faces().group_by(Axis.X)[-1].sort_by(Axis.Y)[0]",
        "faces().sort_by(SortBy.AREA, reverse=True)[0:2]",
        "faces().sort_by(Axis((0, 0, 0), (0.9659, 0.2588, 0)))[-1]",
        "faces().filter_by(Plane.XY)",
        "edges().first",
        "faces()",
    ],
)
def test_a_build123d_selection_is_a_chain_of_shapelist_methods(ref):
    assert selector_refs.classify(ref) == (selector_refs.BUILD123D, None)


@pytest.mark.parametrize("ref", ["face:12", "edge:3", "base", "arm:link#2", "quote", "", None, 12])
def test_what_is_not_written_as_a_selection_is_some_other_ref(ref):
    assert selector_refs.classify(ref) == (None, None)
    assert selector_refs.style(ref) is None


@pytest.mark.parametrize(
    "ref, why",
    [
        # Nothing reaches past the library's selectors: no builtins, no dunders,
        # no names but the few the arguments use, no code of its own.
        ('faces().sort_by(__import__("os").system("x"))', "only"),
        ("faces().__class__", "chain of ShapeList methods"),
        ("edges().filter_by(GeomType.LINE)._foo()", "_foo"),
        ("faces().group_by(lambda face: 1)", "an argument is"),
        ("faces().sort_by(os.system)", "only"),
        ("faces().sort_by(Axis.Z)[index]", "an index is an integer"),
        # A CadQuery chain is selectors and nothing else.
        ('faces(">Z").sort_by(Axis.Z)', "not a CadQuery selection"),
        ('faces(">Z").edges(1)', "one string selector"),
        ('faces(selector=">Z")', "no keyword"),
        ("faces(1)", "one string selector"),
        # And it is one chain.
        ('faces(">Z") + edges("<Z")', "one chain"),
        ('faces(">Z"', "not an expression"),
        ('faces("%s")' % ("x" * selector_refs.MAX_LENGTH), "longer"),
    ],
)
def test_what_could_be_more_than_a_selection_is_refused_saying_why(ref, why):
    style, problem = selector_refs.classify(ref)
    assert style is None
    assert why in problem
    with pytest.raises(ValueError, match="written as a selection"):
        comments.entry("Ada", "x", ref=ref)


def test_what_a_selection_selects_first():
    assert selector_refs.kind('faces("%PLANE").edges(">Z")') == "faces"
    assert selector_refs.kind("edges().sort_by(Axis.Z)[-1]") == "edges"
    assert selector_refs.kind("face:12") is None


def test_a_comment_keeps_a_selection_as_written():
    entry = comments.entry("Ada", "Too thin.", ref=' faces(">Z") ')
    assert entry["ref"] == 'faces(">Z")'
    assert comments.describe_ref(entry["ref"]) == 'faces(">Z")'


def test_the_sandbox_has_a_copy_and_it_is_the_same_file():
    """The wrappers cannot import 'partcad_utils' in a sandbox, so they carry this module: edit it here and copy it."""
    copy = pathlib.Path(partcad.__file__).parent / "wrappers" / "selector_refs.py"
    assert (
        copy.read_bytes() == pathlib.Path(selector_refs.__file__).read_bytes()
    ), "src/partcad/wrappers/selector_refs.py differs from src/partcad_utils/selector_refs.py: copy it over"
