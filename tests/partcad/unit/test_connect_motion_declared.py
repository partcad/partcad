#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether anything says how an object is brought into place.

A step of an assembly somebody performs has to say whether the object is
pushed, snapped or screwed in. The connection's own 'how' can say it, and so can
the mating of the two interfaces it connects ('snapIn', 'selfScrew') or the
interfaces themselves (a thread). Nothing saying it is what makes a step one
that cannot be followed, which the manufacturability test and the Build vs Buy
table both report.
"""

import asyncio

import partcad as pc
from partcad.assembly_connect import ConnectHow


class _Iface:
    def __init__(self, name, self_screw=False, thread_step=None, ctx=None):
        self.full_name = name
        self._self_screw = self_screw
        self._thread_step = thread_step
        self.project = type("_P", (), {"ctx": ctx})()

    def get_self_screw(self):
        return self._self_screw

    def get_thread_step(self):
        return self._thread_step


class _Mate:
    def __init__(self, self_screw=False, snap_in=False):
        self.self_screw = self_screw
        self.snap_in = snap_in


class _Ctx:
    def __init__(self, mates=None):
        self._mates = {}
        for (a, b), mate in (mates or {}).items():
            self._mates[(a, b)] = mate
            self._mates[(b, a)] = mate

    def get_mate(self, a, b):
        return self._mates.get((a, b))


def _how(config, source=None, target=None):
    return ConnectHow(config, where="connect").resolve(source_interface=source, target_interface=target)


def test_a_connection_that_says_nothing_says_nothing_about_how():
    assert not _how(None).motion_declared()
    # When and by what it is held are not how it goes in.
    assert not _how({"stage": "snug", "holdWith": "grip"}).motion_declared()


def test_the_connection_itself_can_say_it():
    assert _how({"pushForceMax": 10}).motion_sources == ["how"]
    assert _how({"snapIn": False}).motion_declared()


def test_a_mating_can_say_it_for_every_connection_through_it():
    for mate in (_Mate(snap_in=True), _Mate(self_screw=True)):
        ctx = _Ctx({("//p:clip", "//p:barb"): mate})
        source, target = _Iface("//p:clip", ctx=ctx), _Iface("//p:barb", ctx=ctx)
        assert _how(None, source, target).motion_sources == ["mating"]


def test_a_thread_on_the_interfaces_says_it_is_screwed_in():
    ctx = _Ctx()
    screw = _Iface("//p:m3", thread_step=0.5, ctx=ctx)
    hole = _Iface("//p:m3-hole", thread_step=0.5, ctx=ctx)
    assert _how(None, screw, hole).motion_sources == ["interface"]
    assert _how(None, _Iface("//p:tapping", self_screw=True, ctx=ctx), _Iface("//p:plain", ctx=ctx)).motion_declared()
    assert not _how(None, _Iface("//p:peg", ctx=ctx), _Iface("//p:hole", ctx=ctx)).motion_declared()


def test_the_steps_of_the_examples_that_are_meant_to_be_built_can_all_be_followed():
    ctx = pc.init("examples")
    for name in (
        "//produce_assembly_assy:logo",
        "//feature_interface:connect-instructions",
        "//feature_import:AeroAssembly_assy_example/AeroAssembly_connected",
    ):
        assembly = ctx.get_assembly(name)
        assert asyncio.run(assembly.get_step_problems()) == [], name


def test_a_step_placed_by_coordinates_cannot_be_followed():
    ctx = pc.init("examples")
    assembly = ctx.get_assembly("//produce_assembly_assy:logo_embedded")

    problems = asyncio.run(assembly.get_step_problems())

    assert ("bone1", "it is placed by 'location:', which does not say what it is joined to") in problems
    # The connectivity test fails these already; the manufacturability test
    # leaves them to it.
    assert asyncio.run(assembly.get_step_problems(include_located=False)) == []


#
# A mating's own 'how'
#


class _HowMate(_Mate):
    def __init__(self, how, **flags):
        super().__init__(**flags)
        self.how = how


def _through(how_config, mate, source_thread=None, target_thread=None):
    ctx = _Ctx({("//p:screw", "//p:tapped"): mate})
    source = _Iface("//p:screw", thread_step=source_thread, ctx=ctx)
    target = _Iface("//p:tapped", thread_step=target_thread, ctx=ctx)
    return _how(how_config, source, target)


def test_a_mating_how_says_how_every_connection_through_it_goes_together():
    how = _through(None, _HowMate({"turnTorqueMax": 0.6, "turnDirection": "ccw", "threadStep": 0.5}))

    assert (how.turn_torque_max, how.turn_direction, how.thread_step) == (0.6, "ccw", 0.5)
    assert how.motion_sources == ["mating"]


def test_an_assy_how_overrides_the_mating_field_by_field():
    mate = _HowMate({"turnTorqueMax": 0.6, "threadStep": 0.5, "pushForceMax": 20})

    how = _through({"turnTorqueMax": 1.2}, mate)

    # The step's own torque, and the mating's thread and push force.
    assert (how.turn_torque_max, how.thread_step, how.push_force_max) == (1.2, 0.5, 20)
    assert how.motion_sources == ["how", "mating"]


def test_a_mating_thread_outranks_the_interfaces():
    how = _through(None, _HowMate({"threadStep": 0.7}), source_thread=0.5, target_thread=0.5)
    assert how.thread_step == 0.7


def test_a_mating_how_flag_outranks_the_mating_flag_beside_it():
    how = _through(None, _HowMate({"snapIn": False}, snap_in=True))
    assert how.snap_in is False


def test_a_mating_reads_its_how_and_refuses_what_is_not_about_going_together():
    from partcad.mating import Mating

    mating = Mating(None, None, {"how": {"turnTorqueMax": 0.6, "stage": "first", "holdWith": "grip"}})
    assert mating.how == {"turnTorqueMax": 0.6}
    assert Mating(None, None, {}).how == {}
    assert Mating(None, None, {"how": "screwed"}).how == {}
