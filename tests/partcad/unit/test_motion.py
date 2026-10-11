#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a 'motion:' declaration says on its own, before any connection reads it.

'partcad.motion' turns one declaration into the degrees of freedom it states and
reports what contradicts itself; matching them to parameters is the joint's
business ('test_joint.py').
"""

import pytest

from partcad import motion as pc_motion
from partcad.motion import MOVE, TURN, Motion


def _implied(config):
    return [(freedom.kind, freedom.axis) for freedom in Motion(config).implied()]


def test_the_short_form_is_the_type():
    assert Motion("revolute").type == "revolute"
    assert Motion({"type": "revolute"}).implied()[0].kind == TURN


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("fixed", []),
        ("revolute", [(TURN, (0.0, 0.0, 1.0))]),
        ("continuous", [(TURN, (0.0, 0.0, 1.0))]),
        ("prismatic", [(MOVE, (0.0, 0.0, 1.0))]),
        ("cylindrical", [(TURN, (0.0, 0.0, 1.0)), (MOVE, (0.0, 0.0, 1.0))]),
        ("screw", [(TURN, (0.0, 0.0, 1.0)), (MOVE, (0.0, 0.0, 1.0))]),
        ("universal", [(TURN, (0.0, 0.0, 1.0)), (TURN, (1.0, 0.0, 0.0))]),
        ("ball", [(TURN, (1.0, 0.0, 0.0)), (TURN, (0.0, 1.0, 0.0)), (TURN, (0.0, 0.0, 1.0))]),
        ("planar", [(MOVE, (1.0, 0.0, 0.0)), (MOVE, (0.0, 1.0, 0.0)), (TURN, (0.0, 0.0, 1.0))]),
        (
            "floating",
            [(MOVE, (1.0, 0.0, 0.0)), (MOVE, (0.0, 1.0, 0.0)), (MOVE, (0.0, 0.0, 1.0))]
            + [(TURN, (1.0, 0.0, 0.0)), (TURN, (0.0, 1.0, 0.0)), (TURN, (0.0, 0.0, 1.0))],
        ),
    ],
)
def test_every_kind_implies_its_degrees_of_freedom_about_the_port_z_axis(kind, expected):
    assert _implied(kind) == expected
    assert not Motion(kind).problems


def test_an_axis_moves_every_freedom_that_has_one():
    assert _implied({"type": "prismatic", "axis": [0, 2, 0]}) == [(MOVE, (0.0, 1.0, 0.0))]
    # A plane across X is moved in along Y and Z, and turned about X.
    assert _implied({"type": "planar", "axis": [1, 0, 0]}) == [
        (MOVE, (0.0, 1.0, 0.0)),
        (MOVE, (0.0, 0.0, 1.0)),
        (TURN, (1.0, 0.0, 0.0)),
    ]
    # Any other axis gets two directions across it that make a right-handed frame.
    u, v, normal = (freedom.axis for freedom in Motion({"type": "planar", "axis": [1, 1, 1]}).implied())
    assert pc_motion.cross(u, v) == pytest.approx(normal)
    assert pc_motion.dot(u, normal) == pytest.approx(0.0, abs=1e-12)


def test_limits_bound_the_kinds_with_one_axis_to_bound():
    freedom = Motion({"type": "revolute", "limits": {"lower": -30, "upper": 60}}).implied()[0]
    assert (freedom.lower, freedom.upper, freedom.limited) == (-30.0, 60.0, True)
    # A screw's are its turn's: the move follows by the thread.
    turn, move = Motion({"type": "screw", "limits": {"lower": 0, "upper": 720}}).implied()
    assert (turn.lower, turn.upper) == (0.0, 720.0)
    assert move.follows == 0 and not move.limited
    # 'continuous' is the one kind that says "no limits" outright.
    assert Motion("continuous").implied()[0].unlimited


@pytest.mark.parametrize(
    "config, words",
    [
        ({"type": "fixed", "dof": ["turnZ"]}, "keeps no degree of freedom"),
        ({"type": "fixed", "limits": {"lower": 0, "upper": 1}}, "has no limits"),
        ({"type": "continuous", "limits": {"lower": -1, "upper": 1}}, "without limits"),
        ({"type": "ball", "limits": {"lower": -1, "upper": 1}}, "do not say which"),
        ({"type": "revolute", "limits": {"lower": 10, "upper": -10}}, "run backwards"),
        ({"type": "revolute", "limits": {"lower": "%size%"}}, "must be a number"),
        ({"type": "hinge"}, "is not a kind of joint"),
        ({"type": "revolute", "axis": [0, 0, 0]}, "not all zero"),
        ({"type": "revolute", "speed": 3}, "has no field 'speed'"),
        ({"limits": {"lower": 0, "upper": 1}}, "without a 'type'"),
        ({"type": "universal", "axis": [1, 0, 0]}, "turns twice about one axis"),
        (42, "must be the name of a kind of joint"),
    ],
)
def test_a_declaration_that_contradicts_itself_is_reported(config, words):
    motion = Motion(config, where="//p:hinge: motion")
    motion.implied()
    assert any(words in problem for problem in motion.problems), motion.problems
    assert all(problem.startswith("//p:hinge: motion: ") for problem in motion.problems)


def test_what_is_reported_is_replaced_by_what_it_most_plausibly_meant():
    # Limits a continuous joint cannot have are dropped, and it stays continuous.
    freedom = Motion({"type": "continuous", "limits": {"lower": -1, "upper": 1}}).implied()[0]
    assert freedom.unlimited and freedom.lower is None
    # An axis that is not one falls back to the port's Z axis.
    assert _implied({"type": "revolute", "axis": [0, 0, 0]}) == [(TURN, (0.0, 0.0, 1.0))]


def test_dof_is_a_list_of_names():
    assert Motion({"dof": "turnZ"}).dof == ["turnZ"]
    assert Motion({"dof": ["turnZ", "moveZ"]}).dof == ["turnZ", "moveZ"]
    assert Motion({"dof": ["turnZ", "turnZ"]}).dof == ["turnZ"]
    assert Motion({"dof": []}).declared
    assert not Motion(None).declared
    # Only what describes the joint as a whole: nothing about its freedoms.
    assert not Motion({"mimic": {"joint": "other"}}).declared


def test_the_joint_record_is_soft_limits_and_mimic():
    motion = Motion({"type": "revolute", "softLimits": {"lower": -1}, "mimic": {"joint": "a-b", "multiplier": 2}})
    assert motion.joint_record() == {"softLimits": {"lower": -1}, "mimic": {"joint": "a-b", "multiplier": 2}}


def test_principal_names_carry_the_sign_of_the_axis():
    assert pc_motion.principal_name(TURN, (0.0, 0.0, -1.0)) == ("turnZ", -1)
    assert pc_motion.principal_name(MOVE, (0.0, 1.0, 0.0)) == ("moveY", 1)
    assert pc_motion.principal_name(TURN, (0.0, 0.6, 0.8)) == (None, 0)
