#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The MemoryPacing healthcheck: little memory for the processes PartCAD runs at once.

Where there is, 'memoryPacing' is what keeps a burst of starts from running the
machine out of memory, and this suggests it. A warning: everything works, and
pacing is the user's to turn on.
"""

from types import SimpleNamespace

import pytest

from partcad import memory, sandbox_lock
from partcad.healthcheck import memory_pacing
from partcad.healthcheck.tests import SEVERITY_WARNING, discover_healthchecks
from partcad_utils.user_config import user_config

GB = 1024**3


@pytest.fixture
def machine(monkeypatch):
    """A machine of 'capacity' bytes, 'available' of them free now, running 'processes' at once."""
    state = SimpleNamespace(capacity=32 * GB, available=24 * GB, processes=4)
    monkeypatch.setattr(memory, "capacity", lambda count_swap=True: state.capacity)
    monkeypatch.setattr(
        memory_pacing.psutil, "virtual_memory", lambda: SimpleNamespace(available=state.available, total=state.capacity)
    )
    monkeypatch.setattr(memory_pacing.psutil, "swap_memory", lambda: SimpleNamespace(free=0, total=0))
    monkeypatch.setattr(sandbox_lock, "process_slot_count", lambda config=None: state.processes)
    monkeypatch.setattr(user_config, "memory_pacing", 0.0)
    monkeypatch.setattr(user_config, "memory_budget", 0.8)
    monkeypatch.setattr(user_config, "memory_budget_swap", True)
    return state


def _findings():
    return memory_pacing.MemoryPacingCheck().test().findings


def test_a_machine_with_room_for_every_process_passes(machine):
    assert _findings() == []


def test_a_small_budget_for_the_processes_suggests_pacing(machine):
    machine.capacity = 6 * GB
    (finding,) = _findings()
    assert "4.8 GB (80% of the 6.0 GB this machine has, swap included) for 4 sandbox processes" in finding
    assert "1.2 GB each" in finding
    assert "memoryPacing: true" in finding and "PC_MEMORY_PACING=true" in finding


def test_more_processes_make_the_same_machine_small(machine):
    machine.capacity = 16 * GB
    assert _findings() == []
    machine.processes = 8
    assert len(_findings()) == 1


def test_little_memory_available_now_suggests_pacing_too(machine):
    machine.available = 4 * GB
    (finding,) = _findings()
    assert "Only 4.0 GB of this machine's memory is available now" in finding
    assert "memoryPacing: true" in finding


def test_with_pacing_on_there_is_nothing_to_suggest(machine, monkeypatch):
    machine.capacity = 6 * GB
    monkeypatch.setattr(user_config, "memory_pacing", 0.5)
    assert _findings() == []


def test_with_the_budget_off_it_says_pacing_needs_it(machine, monkeypatch):
    machine.capacity = 6 * GB
    monkeypatch.setattr(user_config, "memory_budget", 0.0)
    (finding,) = _findings()
    assert "Pacing needs 'memoryBudget', which is turned off" in finding


def test_it_warns_rather_than_fails():
    assert memory_pacing.MemoryPacingCheck().severity == SEVERITY_WARNING


def test_it_is_run_by_pc_healthcheck():
    assert "MemoryPacing" in [check.name for check in discover_healthchecks()]
