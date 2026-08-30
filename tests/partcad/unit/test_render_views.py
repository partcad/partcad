#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the viewing angle of a 2D projection.

'pc render --view' is meant to be a naming of what 'partcad.yaml' already says,
not a second way of saying it: what a name resolves to has to be the very
'viewport_origin'/'viewport_up' pair a 'render:' file type is configured with,
and it has to reach the implementation on top of that configuration rather than
beside it. Both halves are checked here without a sandbox.
"""

import asyncio

import pytest

import partcad as pc
from partcad.render import VIEWS, VIEW_NAMES, resolve_viewport
from partcad.shape import Shape

# The names the thin CLI inlines for '--help' and for rejecting a typo without a
# round trip. Duplicated there on purpose (it must not import the heavy partcad
# package), and shared by every command that writes a projection - 'pc render'
# and 'pc adhoc render' - so there is one copy, not one per command. This is what
# keeps it honest.
from partcad_cli.click.viewport import VIEW_NAMES as CLI_VIEW_NAMES

# --------------------------------------------------------------------------- #
# The named views                                                             #
# --------------------------------------------------------------------------- #


def test_every_view_is_a_pair_of_direction_vectors():
    for name, (origin, up) in VIEWS.items():
        assert len(origin) == 3, name
        assert len(up) == 3, name
        # A viewport origin says which direction to look from and an up vector
        # which way is up; neither means anything as the zero vector.
        assert any(origin), name
        assert any(up), name


def test_up_is_not_parallel_to_the_direction_looked_from():
    """A view whose up vector lies along the line of sight has no picture in it."""
    for name, (origin, up) in VIEWS.items():
        cross = (
            origin[1] * up[2] - origin[2] * up[1],
            origin[2] * up[0] - origin[0] * up[2],
            origin[0] * up[1] - origin[1] * up[0],
        )
        assert any(cross), name


def test_iso_is_the_default_a_part_is_drawn_from():
    """'--view iso' names the corner the SVG wrapper looks from on its own.

    That default lives in the wrapper (it is picked from the kind of shape being
    drawn, which only the wrapper knows). Naming it here is what makes it
    selectable again once a package has configured something else, so the two
    have to agree.
    """
    assert VIEWS["iso"] == ((100, -100, 100), (0, 0, 1))


def test_the_cli_offers_exactly_the_views_that_resolve():
    assert sorted(CLI_VIEW_NAMES) == sorted(VIEW_NAMES)


# --------------------------------------------------------------------------- #
# Resolution                                                                  #
# --------------------------------------------------------------------------- #


def test_no_arguments_override_nothing():
    """What a plain 'pc render' sends: the configuration is left alone."""
    assert resolve_viewport() == {}


def test_a_name_resolves_to_the_configuration_keys():
    assert resolve_viewport("front") == {
        "viewport_origin": [0, -100, 0],
        "viewport_up": [0, 0, 1],
    }


@pytest.mark.parametrize("view", VIEW_NAMES)
def test_every_name_resolves(view):
    overrides = resolve_viewport(view)
    assert set(overrides) == {"viewport_origin", "viewport_up"}


def test_vectors_win_over_the_name_component_by_component():
    """'--view top' can be tilted without spelling the whole pair out again."""
    overrides = resolve_viewport("top", viewport_up=[0, 1, 0.5])
    assert overrides["viewport_origin"] == [0, 0, 100]
    assert overrides["viewport_up"] == [0.0, 1.0, 0.5]


def test_vectors_alone_need_no_name():
    assert resolve_viewport(viewport_origin=("1", "2", "3")) == {"viewport_origin": [1.0, 2.0, 3.0]}


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"view": "isometric"}, "Unknown view"),
        ({"viewport_origin": [1, 2]}, "three numbers"),
        ({"viewport_origin": [1, 2, 3, 4]}, "three numbers"),
        ({"viewport_origin": "nonsense"}, "three numbers"),
        # A three-character string is iterable and three long, so it would
        # otherwise be read as [1.0, 2.0, 3.0] and aim the camera at something
        # nobody asked for. Refused rather than silently obeyed.
        ({"viewport_origin": "123"}, "not a string"),
        ({"viewport_origin": None, "viewport_up": [0, 0, 0]}, "zero vector"),
        # Not a string at all: the dictionary lookup would raise TypeError,
        # which the callers do not turn into a usage error the way they do a
        # ValueError. The CLI constrains this; the daemon's other clients do not.
        ({"view": ["front"]}, "Unknown view"),
        ({"view": 3}, "Unknown view"),
        # Both vectors pass their own checks and contradict each other: looking
        # along -Y with "up" also along Y leaves no rotation that puts anything
        # at the top of the picture.
        ({"view": "front", "viewport_up": [0, -1, 0]}, "parallel"),
        ({"viewport_origin": [0, 0, 100], "viewport_up": [0, 0, -2]}, "parallel"),
    ],
)
def test_a_request_that_cannot_be_aimed_is_refused(kwargs, expected):
    """Rather than rendering something aimed somewhere else."""
    with pytest.raises(ValueError, match=expected):
        resolve_viewport(**kwargs)


def test_one_vector_alone_is_not_checked_against_the_other():
    """The pair is only comparable when this request settles both halves of it.

    Given just an up vector, the origin is whatever the configuration resolves
    to and is not known here, so there is nothing yet to be parallel to.
    """
    assert resolve_viewport(viewport_up=[0, 0, 1]) == {"viewport_up": [0.0, 0.0, 1.0]}


# --------------------------------------------------------------------------- #
# Where the overrides land                                                    #
# --------------------------------------------------------------------------- #


def test_the_overrides_reach_the_request_above_the_configuration():
    """A render parameter passed per run beats the one the package configured.

    'Shape._output_request()' is the join: the merged configuration first, then
    the arguments of this one run. Exercised directly, with no shape and no
    sandbox, because what is under test is the precedence and nothing else.
    """

    class _Impl:
        parameters = {"viewport_origin": [0, 0, 100], "line_weight": 2.0}

    class _Fake:
        name = "part"
        kind = "part"
        config = {"type": "cadquery"}
        project_name = "//pkg"

        _output_request = Shape._output_request

    request = asyncio.run(
        _Fake()._output_request("wrapped", _Impl(), {"viewport_origin": [0, -100, 0], "viewport_up": None})
    )
    assert request["viewport_origin"] == [0, -100, 0]
    # What this run said nothing about is still what the package configured.
    assert request["line_weight"] == 2.0
    # An argument left unset is not an override: 'None' must not erase the
    # configuration, which is what several callers pass for the options they
    # were given nothing for.
    assert "viewport_up" not in request


def test_a_package_render_hands_the_overrides_to_every_shape(monkeypatch):
    """'Project.render_async()' is the caller in between, and has to pass them on.

    Nothing is rendered: 'Shape.render_async' is replaced by a recorder, so this
    covers the plumbing at the cost of reading a package configuration and
    without a Python sandbox.
    """
    calls = []

    async def _record(self, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(Shape, "render_async", _record)

    ctx = pc.Context("examples")
    project = ctx.get_project("//produce_part_cadquery_primitive")
    project.render(parts=["cube"], format="svg", render_opts={"viewport_origin": [0, -100, 0]})

    assert calls, "no shape was asked to render"
    for call in calls:
        assert call["viewport_origin"] == [0, -100, 0]


def test_a_package_render_without_overrides_passes_none_of_them(monkeypatch):
    """What a plain 'pc render' does: the configuration is the whole answer."""
    calls = []

    async def _record(self, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(Shape, "render_async", _record)

    ctx = pc.Context("examples")
    project = ctx.get_project("//produce_part_cadquery_primitive")
    project.render(parts=["cube"], format="svg")

    assert calls, "no shape was asked to render"
    for call in calls:
        assert "viewport_origin" not in call
        assert "viewport_up" not in call
