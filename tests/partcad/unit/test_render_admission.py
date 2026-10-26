#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""How a package's render takes part in admission: objects ranked as units, and failures one at a time."""

import asyncio

import pytest
import yaml

import partcad as pc
from partcad import admission, runtime, sandbox_lock
from partcad.shape import Shape
from partcad_utils import user_config as user_config_module

CUBE = "import cadquery as cq\nshape = cq.Workplane('front').box(1, 1, 1)\nshow_object(shape)\n"


def _package(tmp_path, names):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = {
        "name": "//test",
        "parts": {name: {"type": "cadquery", "path": "cube.py"} for name in names},
        "render": {"svg": None, "png": None},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (tmp_path / "cube.py").write_text(CUBE)
    return pc.Context(str(tmp_path)).get_project("//")


@pytest.fixture
def renders(monkeypatch):
    """Every output a render asks for, with the rank it asked under, and no sandbox."""
    seen = []
    failing = set()

    async def render_async(self, ctx, format_name, project=None, **kwargs):
        seen.append((self.name, format_name, admission.current()))
        await asyncio.sleep(0.01)
        if self.name in failing:
            raise RuntimeError("the sandbox drawing %s was killed" % self.name)

    monkeypatch.setattr(Shape, "render_async", render_async)
    return seen, failing


def test_one_failed_object_does_not_end_the_others(tmp_path, renders):
    """The first failure is raised once the rest are done, not instead of them."""
    seen, failing = renders
    project = _package(tmp_path, ["first", "second", "third"])
    failing.add("first")

    with pytest.raises(RuntimeError, match="drawing first was killed"):
        asyncio.run(project.render_async(output_dir=str(tmp_path)))

    assert sorted({name for name, _, _ in seen}) == ["first", "second", "third"]
    assert len(seen) == 6


def test_an_object_s_outputs_share_one_rank_and_objects_rank_in_declaration_order(tmp_path, renders):
    seen, _ = renders
    project = _package(tmp_path, ["b_declared_first", "a_declared_second"])
    asyncio.run(project.render_async(output_dir=str(tmp_path)))

    ranks = {}
    for name, _, rank in seen:
        ranks.setdefault(name, set()).add(id(rank))
        assert rank is not None
    assert all(len(ids) == 1 for ids in ranks.values())

    by_name = {name: rank for name, _, rank in seen}
    assert by_name["b_declared_first"].key() < by_name["a_declared_second"].key()


# ---- a call into a container is a task like any other ---------------------------


class _Endpoint:
    def __init__(self, slots, seen):
        self.slots, self.seen = slots, seen

    def run(self, cmd, stdin=None, **kwargs):
        self.seen.append(self.slots._in_use)
        return 0, "done", ""

    async def run_async(self, cmd, stdin=None, **kwargs):
        self.seen.append(self.slots._in_use)
        return 0, "done", ""


def test_a_call_into_a_container_takes_a_process_slot(tmp_path, monkeypatch):
    slots = sandbox_lock.ProcessSlots(1)
    monkeypatch.setattr(sandbox_lock, "process_slots", slots)
    seen = []
    container = runtime.Runtime.__new__(runtime.Runtime)
    container.endpoint = _Endpoint(slots, seen)
    monkeypatch.setattr(container, "_current_endpoint", lambda: container.endpoint, raising=False)
    monkeypatch.setattr(container, "_endpoint_stopped", False, raising=False)
    monkeypatch.setattr(container, "_endpoint_ended", lambda endpoint, code, err: (code, err), raising=False)
    monkeypatch.setattr(container, "_finished", lambda cmd, out, err, code: (code, out, err), raising=False)

    assert container.run(["python", "x.py"], stdin="request") == (0, "done", "")
    assert asyncio.run(container.run_async(["python", "x.py"], stdin="request")) == (0, "done", "")
    # Held while the call ran, and given back after it.
    assert seen == [1, 1]
    assert slots._in_use == 0


# ---- the settings ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(None, 0.8), ("0.5", 0.5), (0.25, 0.25), (1, 1.0), (0, 0.0), ("false", 0.0), (False, 0.0)],
)
def test_memory_budget_is_a_share(value, expected):
    assert user_config_module.memory_budget_share(value) == expected


@pytest.mark.parametrize("value", [2, -0.1, "most of it", float("nan")])
def test_anything_else_is_ignored_for_the_default(value):
    assert user_config_module.memory_budget_share(value) == user_config_module.MEMORY_BUDGET_DEFAULT


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, 0.0),
        (False, 0.0),
        ("false", 0.0),
        (0, 0.0),
        (True, user_config_module.MEMORY_PACING_ON),
        ("true", user_config_module.MEMORY_PACING_ON),
        ("on", user_config_module.MEMORY_PACING_ON),
        ("0.3", 0.3),
        (0.7, 0.7),
    ],
)
def test_memory_pacing_is_off_on_or_a_share(value, expected):
    assert user_config_module.memory_pacing_share(value) == expected


@pytest.mark.parametrize("value", [2, -0.1, "sometimes", float("nan")])
def test_anything_else_leaves_starts_unpaced(value):
    assert user_config_module.memory_pacing_share(value) == 0.0


def test_the_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("PC_MEMORY_BUDGET", raising=False)
    monkeypatch.delenv("PC_MEMORY_BUDGET_SWAP", raising=False)
    monkeypatch.delenv("PC_MEMORY_PACING", raising=False)
    monkeypatch.delenv("PC_CACHE_MEMORY_MAX_ENTRY_SIZE", raising=False)
    config = user_config_module.UserConfig(settings={"internalStateDir": str(tmp_path)})
    assert config.memory_budget == 0.8
    assert config.memory_budget_swap is True
    assert config.memory_pacing == 0.0
    assert config.cache_memory_max_entry_size == 250 * 1024 * 1024


def test_the_environment_sets_them(tmp_path, monkeypatch):
    monkeypatch.setenv("PC_MEMORY_BUDGET", "0.6")
    monkeypatch.setenv("PC_MEMORY_BUDGET_SWAP", "false")
    monkeypatch.setenv("PC_MEMORY_PACING", "true")
    config = user_config_module.UserConfig(settings={"internalStateDir": str(tmp_path)})
    assert config.memory_budget == 0.6
    assert config.memory_budget_swap is False
    assert config.memory_pacing == user_config_module.MEMORY_PACING_ON


def test_they_travel_with_a_configuration():
    """A daemon budgets with the configuration a request carries, not its own."""
    assert "memoryBudget" in user_config_module.OPTION_KEYS
    assert "memoryBudgetSwap" in user_config_module.OPTION_KEYS
    assert "memoryPacing" in user_config_module.OPTION_KEYS
