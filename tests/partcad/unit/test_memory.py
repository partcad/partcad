#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What PartCAD's work holds, and what the machine has: the numbers admission is decided on."""

import gc
import sys
from types import SimpleNamespace

import psutil
import pytest

from partcad import memory
from partcad_utils import containers

GB = 1024**3

# What '_PyObject_DebugMallocStats' writes about the arenas, trimmed to the lines read.
_PYMALLOC_STATS = """\
class   size   num pools   blocks in use  avail blocks
-----   ----   ---------   -------------  ------------
    0     16           1             115           906

# arenas allocated total           =                   15
# arenas allocated current         =                   15
# bytes in allocated blocks        =            8,365,904
# bytes in available blocks        =            6,608,512
36 unused pools * 16384 bytes      =              589,824
# bytes lost to pool headers       =               44,064
Total                              =           15,728,640
"""


def test_python_s_free_blocks_and_pools_are_what_it_can_reuse():
    assert memory.parse_pymalloc_free(_PYMALLOC_STATS) == 6_608_512 + 589_824


def test_statistics_with_nothing_free_say_nothing_is():
    assert memory.parse_pymalloc_free("# bytes in allocated blocks = 1,000\n") == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc and open_memstream")
def test_what_python_frees_is_found_free_for_reuse():
    """Not given back to the system, and not counted as used either."""
    before = memory.reusable()
    garbage = [str(i) * 3 for i in range(300_000)]
    del garbage[::2]
    gc.collect()
    assert memory.reusable() > before


def test_the_footprint_counts_this_process_less_what_it_can_reuse():
    footprint = memory.Footprint(own=5 * GB, reusable=2 * GB, children=3 * GB, containers=GB)
    assert footprint.usage == 7 * GB


def test_the_footprint_never_counts_less_than_nothing_for_this_process():
    footprint = memory.Footprint(own=GB, reusable=3 * GB, children=GB, containers=0)
    assert footprint.usage == GB


def test_the_footprint_says_what_it_is_made_of():
    text = memory.Footprint(own=2 * GB, reusable=GB, children=3 * GB, containers=0).describe()
    assert text.startswith("4.0 GB")
    assert "sandboxes 3.0 GB" in text


def test_this_process_s_footprint_is_measured():
    """The real thing, on whatever this machine is: positive, and its sandboxes among it."""
    footprint = memory.footprint()
    assert footprint.own > 0
    assert footprint.usage > 0
    assert footprint.children >= 0


# ---- capacity ------------------------------------------------------------------


def _cgroup_v1(tmp_path, path, limits):
    proc = tmp_path / "proc_cgroup"
    proc.write_text("4:memory:%s\n1:cpu:/\n0::/\n" % path)
    for directory, (memory_limit, both) in limits.items():
        where = tmp_path / "memory" / directory.strip("/")
        where.mkdir(parents=True, exist_ok=True)
        (where / "memory.limit_in_bytes").write_text("%d\n" % memory_limit)
        (where / "memory.memsw.limit_in_bytes").write_text("%d\n" % both)
    return str(tmp_path), str(proc)


def _cgroup_v2(tmp_path, path, limits):
    proc = tmp_path / "proc_cgroup"
    proc.write_text("0::%s\n" % path)
    for directory, (memory_limit, swap) in limits.items():
        where = tmp_path / directory.strip("/")
        where.mkdir(parents=True, exist_ok=True)
        (where / "memory.max").write_text("%s\n" % memory_limit)
        (where / "memory.swap.max").write_text("%s\n" % swap)
    return str(tmp_path), str(proc)


UNLIMITED_V1 = 9223372036854771712


def test_a_v1_cgroup_s_limit_is_the_tightest_on_the_way_up(tmp_path):
    root, proc = _cgroup_v1(
        tmp_path,
        "/session/bash",
        {
            "/": (UNLIMITED_V1, UNLIMITED_V1),
            "/session": (16 * GB, 20 * GB),
            "/session/bash": (13 * GB, UNLIMITED_V1),
        },
    )
    assert memory.cgroup_limits(root, proc) == (13 * GB, 4 * GB)


def test_an_unlimited_v1_cgroup_is_no_limit(tmp_path):
    root, proc = _cgroup_v1(tmp_path, "/", {"/": (UNLIMITED_V1, UNLIMITED_V1)})
    assert memory.cgroup_limits(root, proc) == (None, None)


def test_a_v2_cgroup_s_limits(tmp_path):
    root, proc = _cgroup_v2(
        tmp_path,
        "/user.slice/session",
        {"/": ("max", "max"), "/user.slice": ("max", 2 * GB), "/user.slice/session": (8 * GB, "max")},
    )
    assert memory.cgroup_limits(root, proc) == (8 * GB, 2 * GB)


def test_inside_a_container_its_own_cgroup_is_the_root(tmp_path):
    root, proc = _cgroup_v2(tmp_path, "/", {"/": (6 * GB, 0)})
    assert memory.cgroup_limits(root, proc) == (6 * GB, 0)


def test_no_cgroup_is_no_limit(tmp_path):
    assert memory.cgroup_limits(str(tmp_path), str(tmp_path / "missing")) == (None, None)


def _machine(monkeypatch, ram, swap, limits=(None, None)):
    monkeypatch.setattr(memory.psutil, "virtual_memory", lambda: SimpleNamespace(total=ram))
    monkeypatch.setattr(memory.psutil, "swap_memory", lambda: SimpleNamespace(total=swap))
    monkeypatch.setattr(memory, "cgroup_limits", lambda *args: limits)


def test_the_capacity_is_ram_and_swap(monkeypatch):
    _machine(monkeypatch, 16 * GB, 8 * GB)
    assert memory.capacity() == 24 * GB


def test_the_swap_can_be_left_out(monkeypatch):
    _machine(monkeypatch, 16 * GB, 8 * GB)
    assert memory.capacity(count_swap=False) == 16 * GB


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="cgroups are Linux's")
def test_a_cgroup_holds_the_capacity_to_its_limits(monkeypatch):
    _machine(monkeypatch, 16 * GB, 8 * GB, limits=(13 * GB, 0))
    assert memory.capacity() == 13 * GB


# ---- containers ------------------------------------------------------------------


class _Api:
    def __init__(self, stats):
        self._stats = stats

    def stats(self, container_id, stream=True, one_shot=None):
        assert stream is False and one_shot is True
        return self._stats


def _container(stats):
    return SimpleNamespace(id="abc", client=SimpleNamespace(api=_Api(stats)))


def test_a_container_s_memory_is_what_docker_stats_reports():
    """Its usage less the file cache, as cgroup v2 calls it and as v1 does."""
    v2 = {"memory_stats": {"usage": 3 * GB, "stats": {"inactive_file": GB}}}
    v1 = {"memory_stats": {"usage": 3 * GB, "stats": {"total_inactive_file": GB // 2}}}
    assert memory.container_size(_container(v2)) == 2 * GB
    assert memory.container_size(_container(v1)) == 2 * GB + GB // 2


def test_a_container_that_cannot_be_asked_holds_nothing_known():
    class _Broken:
        id = "abc"

        @property
        def client(self):
            raise RuntimeError("gone")

    assert memory.container_size(_Broken()) == 0
    assert memory.container_size(_container({})) == 0


def test_only_containers_on_this_machine_are_counted_as_this_process_s(monkeypatch):
    monkeypatch.setattr(containers, "_in_use", {})
    here, there = object(), object()
    containers._note_in_use("partcad-sandbox-here", here, None)
    containers._note_in_use("partcad-sandbox-there", there, "builder.example.com")
    assert containers.in_use() == [here]


# ---- the budget ------------------------------------------------------------------


def test_a_budget_is_its_share_of_the_capacity():
    budget = memory.Budget(0.8, capacity_of=lambda count_swap: 10 * GB if count_swap else 8 * GB)
    assert budget.limit == 8 * GB
    assert memory.Budget(0.5, count_swap=False, capacity_of=lambda count_swap: 8 * GB).limit == 4 * GB


def test_a_capacity_that_cannot_be_read_is_none():
    def broken(count_swap):
        raise OSError("no /proc here")

    assert memory.Budget(0.8, capacity_of=broken).limit == 0


def test_the_process_is_measured_with_its_children():
    """What each holds of its own, which is where geometry lives."""
    me = psutil.Process()
    assert memory.process_size(me) > 0
    assert memory.children_size(me) >= 0
