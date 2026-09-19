#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where a joint learns that it cuts its own thread.

Three levels know, and the more specific one wins. An interface knows when it
is true wherever that interface is used - a self-tapping screw is one whatever
it goes into. A mating knows when it is true of the pairing: an M8 screw in an
M8 tapped hole cuts nothing, and the same screw in a plain M8 opening cuts its
own thread, so neither end can answer and only the pairing can. A connection's
'how' knows when it is true of that joint alone.

It matters because 'partcad.test.interference' expects the two solids to share
space exactly where a thread is being formed, and reports it everywhere else.
"""

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
    """Stands in for the real context, which registers a mating under both
    orderings: 'Context.add_mate' stores (a, b) and (b, a), so a lookup never
    has to try the pair the other way round."""

    def __init__(self, mates=None):
        self._mates = {}
        for (a, b), mate in (mates or {}).items():
            self._mates[(a, b)] = mate
            self._mates[(b, a)] = mate

    def get_mate(self, a, b):
        return self._mates.get((a, b))


def _resolved(how_config, source, target):
    how = ConnectHow(how_config, where="connect")
    how._resolve_thread_step(source, target)
    return how.self_screw


def test_a_joint_between_plain_interfaces_cuts_nothing():
    ctx = _Ctx()
    assert not _resolved({}, _Iface("a", ctx=ctx), _Iface("b", ctx=ctx))


def test_an_interface_that_taps_its_own_thread_says_so_wherever_it_is_used():
    ctx = _Ctx()
    assert _resolved({}, _Iface("screw", self_screw=True, ctx=ctx), _Iface("hole", ctx=ctx))


def test_a_pairing_can_say_what_neither_end_knows():
    """The same M8 screw cuts a thread in a plain opening and cuts nothing in a
    tapped hole. Only the mating can tell those apart."""
    ctx = _Ctx({("m8-screw", "m8-opening"): _Mate(self_screw=True)})
    assert _resolved({}, _Iface("m8-screw", ctx=ctx), _Iface("m8-opening", ctx=ctx))

    tapped = _Ctx({("m8-screw", "m8-hole-10"): _Mate(self_screw=False)})
    assert not _resolved({}, _Iface("m8-screw", ctx=tapped), _Iface("m8-hole-10", ctx=tapped))


def test_the_pairing_is_read_whichever_end_the_connection_names_first():
    """A package states the mating once, on one of the two interfaces. Which of
    them the ASSY file happens to be adding is not its business."""
    ctx = _Ctx({("m8-opening", "m8-screw"): _Mate(self_screw=True)})
    assert _resolved({}, _Iface("m8-screw", ctx=ctx), _Iface("m8-opening", ctx=ctx))
    assert _resolved({}, _Iface("m8-opening", ctx=ctx), _Iface("m8-screw", ctx=ctx))


def test_one_joint_may_say_it_for_itself():
    """An ordinary screw driven into something soft - a fact about this joint,
    not about the screw and not about the pairing in general."""
    ctx = _Ctx()
    assert _resolved({"selfScrew": True, "turnTorqueMax": 0.5}, _Iface("a", ctx=ctx), _Iface("b", ctx=ctx))


def test_a_joint_may_also_deny_it():
    """'how' is the most specific level, so it overrides both others."""
    ctx = _Ctx({("screw", "hole"): _Mate(self_screw=True)})
    assert not _resolved(
        {"selfScrew": False, "turnTorqueMax": 0.5},
        _Iface("screw", self_screw=True, ctx=ctx),
        _Iface("hole", ctx=ctx),
    )


def test_a_thread_that_gets_cut_need_not_match_the_one_it_cuts_into():
    """The disagreement is only a problem for a joint that has to match a thread.

    Checked against the resolved answer, not the interfaces' own: the mating and
    the 'how' are the more specific statements, so either of them saying the
    joint cuts its own thread settles it.
    """
    ctx = _Ctx({("m8-screw", "plastic-seat"): _Mate(self_screw=True)})
    how = ConnectHow({}, where="connect")
    how._resolve_thread_step(
        _Iface("m8-screw", thread_step=1.25, ctx=ctx),
        _Iface("plastic-seat", thread_step=2.0, ctx=ctx),
    )
    assert how.self_screw
    assert not how.problems

    how = ConnectHow({"selfScrew": True, "turnTorqueMax": 0.5}, where="connect")
    how._resolve_thread_step(_Iface("a", thread_step=1.25), _Iface("b", thread_step=2.0))
    assert not how.problems


def test_a_joint_that_has_to_match_a_thread_still_reports_a_disagreement():
    ctx = _Ctx()
    how = ConnectHow({}, where="connect")
    how._resolve_thread_step(_Iface("a", thread_step=1.25, ctx=ctx), _Iface("b", thread_step=2.0, ctx=ctx))
    assert not how.self_screw
    assert how.problems


# A joint that is pushed together rather than screwed in.


def _snapped(how_config, source, target):
    how = ConnectHow(how_config, where="connect")
    how._resolve_snap_in(source, target)
    return how.snap_in


def test_a_pairing_may_say_that_it_is_pushed_together():
    """A bore pushed onto a thread it is not cut to match. Neither end knows -
    the bolt is the same bolt, and the bore cannot tell what arrives at it - so
    the pairing says it, exactly as it says 'selfScrew'."""
    ctx = _Ctx({("m8-bolt", "m8-press-opening"): _Mate(snap_in=True)})
    assert _snapped({}, _Iface("m8-bolt", ctx=ctx), _Iface("m8-press-opening", ctx=ctx))


def test_an_ordinary_pairing_is_not_pushed_together():
    ctx = _Ctx({("m8-bolt", "m8-opening"): _Mate()})
    assert not _snapped({}, _Iface("m8-bolt", ctx=ctx), _Iface("m8-opening", ctx=ctx))


def test_a_pairing_with_no_mating_at_all_is_not():
    ctx = _Ctx()
    assert not _snapped({}, _Iface("a", ctx=ctx), _Iface("b", ctx=ctx))


def test_one_joint_may_say_it_is_pushed_together_for_itself():
    ctx = _Ctx()
    assert _snapped({"snapIn": True}, _Iface("a", ctx=ctx), _Iface("b", ctx=ctx))


def test_a_joint_may_deny_what_the_pairing_says():
    """'how' is the more specific level, so an explicit 'false' wins."""
    ctx = _Ctx({("a", "b"): _Mate(snap_in=True)})
    assert not _snapped({"snapIn": False}, _Iface("a", ctx=ctx), _Iface("b", ctx=ctx))
