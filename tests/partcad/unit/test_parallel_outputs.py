#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How PartCAD runs a video, and keeps what it makes.

A video is a file whose extension says it is one (see 'output.VIDEO_EXTENSIONS'),
whatever its file type is called, and no file type says how it is run or kept:
the user's configuration does.

- 'video.parallel' (on by default): the run is given the process slots that are
  free when it starts and says so in 'threads'; off, it is told one thread.
  Either way it is keyed on neither 'threads' nor 'memory';
- 'video.cacheTiers' ('remote' by default): its file is kept only in the remote
  tiers of the cache, never in the files on this machine, not even promoted
  there from a hit - or in 'all' of them, or in 'none';
- always: what it draws from is handed back, kept in every tier under a key of
  its own, and handed in to the next video of the object at that size.

The wrapper is the real one, run as a subprocess by this interpreter; the
runtime around it is a stand-in that takes a process slot the way the Python
sandbox does, and the remote tier is a dictionary.
"""

import asyncio
import json
import os
import subprocess
import sys
import textwrap
import types

import pytest

import partcad as pc
from partcad import cache_backend, output, process_output, runtime, sandbox_lock
from partcad.cache import Cache
from partcad.cache_hash import CacheHash
from partcad_utils import user_config as pc_user_config

pytestmark = pytest.mark.timeout(120)

# Writes down what it was handed, and hands back a scene when asked for one.
WRITE = textwrap.dedent("""
    import json


    def process(path, request):
        scene = request.get("scene")
        with open(path, "w") as f:
            json.dump(
                {
                    "threads": request.get("threads"),
                    "memory": request.get("memory"),
                    "scene": scene.decode() if isinstance(scene, (bytes, bytearray)) else scene,
                    "scene_wanted": request.get("scene_wanted"),
                },
                f,
            )
        result = {"success": True, "files": []}
        if request.get("scene_wanted"):
            result["scene"] = ("the scene %s built at %s" % (request.get("say"), request.get("size"))).encode()
        return result
    """)

# Videos by their extensions, under names that are not; and a file that is not.
EXTENSIONS = {"clip": "mp4", "reel": "webm", "wide": "mkv", "still": "still"}
FILE_TYPES = """
    clip: {path: write.py, size: reels, extension: mp4, say: clip}
    reel: {path: write.py, size: reels, extension: webm, say: reel}
    wide: {path: write.py, size: landscape, extension: mkv, say: wide}
    still: {path: write.py, size: reels, extension: still, say: still}
    """


class FakeRemote(cache_backend.RemoteCacheBackend):
    """A remote tier with nothing remote about it: a dictionary."""

    name = "fake"

    def __init__(self) -> None:
        super().__init__(None, "artifacts")
        self.storage = {}

    @property
    def client_key(self) -> tuple:
        return ("fake", id(self))

    @property
    def location(self) -> tuple:
        return ("fake", id(self))

    async def _open(self):
        return self

    async def _close(self, client) -> None:
        pass

    async def _read_async(self, names):
        async with self.connected():
            return {name: self.storage[name] for name in names if name in self.storage}

    async def _contains_async(self, names):
        async with self.connected():
            return {name: bool(self.storage.get(name)) for name in names}

    async def _write_async(self, items):
        async with self.connected():
            self.storage.update(items)
        return {name: True for name in items}


class _Sandbox:
    """A Python runtime running what it is asked with this interpreter, in a process slot as the real one does."""

    EXCHANGES_FILES = False

    def __init__(self):
        self.calls = 0
        self.held = []

    def get_session(self, name):
        return {"name": name, "path": None, "dirty": False, "deps": [], "missing": []}

    async def prepare_for_package(self, project, session=None):
        pass

    async def ensure_async(self, python_package, session=None, path=None, force=False):
        pass

    async def run_async(self, cmd, stdin="", session=None, **_kwargs):
        async with sandbox_lock.process_slots.slot_async():
            data = runtime.stdin_bytes(stdin)
            self.held.append(sandbox_lock.process_slots._in_use)
        self.calls += 1
        finished = await asyncio.to_thread(subprocess.run, [sys.executable, *cmd], input=data, capture_output=True)
        stderr = process_output.decode(finished.stderr)
        return finished.returncode, process_output.answer(finished.stdout), stderr if finished.returncode else ""


class _Exchanging(_Sandbox):
    """A sandbox on another machine, as far as the process slots here go."""

    EXCHANGES_FILES = True


@pytest.fixture
def video(tmp_path, monkeypatch):
    """A part whose 'video' file types are written by 'write.py', a cache of files and a remote tier, and a sandbox."""
    root = tmp_path / "package"
    root.mkdir()
    (root / "partcad.yaml").write_text(
        "name: //video\nparts:\n  bracket:\n    type: step\n    path: bracket.step\nexport:\n"
        + textwrap.indent(textwrap.dedent(FILE_TYPES), "  ")
    )
    (root / "write.py").write_text(WRITE)
    (root / "bracket.step").write_text("ISO-10303-21; bracket")

    ctx = pc.Context(str(root))
    config = types.SimpleNamespace(
        cache=True,
        internal_state_dir=str(tmp_path / "state"),
        cache_min_entry_size=1,
        cache_max_entry_size=10 * 1024 * 1024,
    )
    cache = Cache("artifacts", config)
    remote = FakeRemote()
    cache.backends.append(remote)
    ctx.cache_artifacts = cache
    sandbox = _Sandbox()
    monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: sandbox)
    monkeypatch.setattr(sandbox_lock, "process_slots", sandbox_lock.ProcessSlots(4))
    # What a user who said nothing gets, whatever this machine's configuration says.
    monkeypatch.setattr(ctx.user_config, "video_parallel", True)
    monkeypatch.setattr(ctx.user_config, "video_cache_tiers", "remote")

    async def get_wrapped(self, _ctx):
        return {"name": self.name, "label": None}

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    return types.SimpleNamespace(ctx=ctx, cache=cache, remote=remote, sandbox=sandbox, out=tmp_path / "out")


def _render(video, format_name, **kwargs):
    async def run():
        part = video.ctx.get_part("//:bracket")
        results = await part.render_async(video.ctx, format_name, output_dir=str(video.out), **kwargs)
        await video.cache.flush_async()
        return results

    return asyncio.run(run())


def _path(video, name):
    return os.path.join(str(video.out), "bracket." + EXTENSIONS[name])


def _written(video, name):
    with open(_path(video, name)) as f:
        return json.load(f)


def _files_tier(video):
    return [b for b in video.cache.backends if not isinstance(b, cache_backend.RemoteCacheBackend)][0]


def _local_entries(video):
    """The names of what the files tier holds."""
    found = []
    for directory, _dirs, files in os.walk(str(video.ctx.cache_artifacts.user_config.internal_state_dir)):
        found += files
    return found


# ---------------------------------------------------------------------------
# Process slots
# ---------------------------------------------------------------------------


def test_more_slots_are_taken_only_from_what_is_free_and_given_back():
    slots = sandbox_lock.ProcessSlots(4)
    assert slots._try_acquire()
    assert slots.take_more(10) == 3
    assert slots.take_more(1) == 0
    assert not slots._try_acquire()
    slots.give_back(3)
    assert slots.take_more(2) == 2
    slots.give_back(2)
    slots.give_back(0)
    slots._release()
    assert slots._in_use == 0


def test_a_video_is_given_every_free_slot_and_gives_them_back(video):
    results = _render(video, "clip")
    assert results["clip"]["success"]
    written = _written(video, "clip")
    # Its own slot and the three the machine had free, held while it ran.
    assert written["threads"] == 4
    assert video.sandbox.held == [4]
    assert sandbox_lock.process_slots._in_use == 0


def test_a_video_gets_what_is_free_however_much_it_asks_for(video):
    busy = sandbox_lock.process_slots.take_more(2)
    try:
        _render(video, "clip", threads=8)
        assert _written(video, "clip")["threads"] == 2
        _render(video, "reel", threads=1)
        assert _written(video, "reel")["threads"] == 1
    finally:
        sandbox_lock.process_slots.give_back(busy)
    assert sandbox_lock.process_slots._in_use == 0


def test_a_file_that_is_not_a_video_is_told_nothing(video):
    _render(video, "still")
    assert _written(video, "still")["threads"] is None


def test_a_sandbox_elsewhere_is_given_no_slots_of_this_machine(video, monkeypatch):
    sandbox = _Exchanging()
    monkeypatch.setattr(video.ctx, "get_python_runtime", lambda version=None, image=None: sandbox)
    _render(video, "clip")
    assert _written(video, "clip")["threads"] is None
    assert sandbox_lock.process_slots._in_use == 0


@pytest.mark.parametrize("runtime_class", [_Sandbox, _Exchanging], ids=["here", "elsewhere"])
def test_a_user_who_turned_parallel_off_has_every_video_drawn_on_one_thread(video, monkeypatch, runtime_class):
    sandbox = runtime_class()
    monkeypatch.setattr(video.ctx, "get_python_runtime", lambda version=None, image=None: sandbox)
    monkeypatch.setattr(video.ctx.user_config, "video_parallel", False)
    _render(video, "clip", threads=8)
    assert _written(video, "clip")["threads"] == 1
    if runtime_class is _Sandbox:
        # Its own slot, and nothing more.
        assert sandbox.held == [1]
    assert sandbox_lock.process_slots._in_use == 0
    # And it is the same video: asked for again with the slots granted, it is
    # the cache that answers.
    monkeypatch.setattr(video.ctx.user_config, "video_parallel", True)
    os.remove(_path(video, "clip"))
    _render(video, "clip")
    assert sandbox.calls == 1


def test_neither_threads_nor_memory_is_part_of_what_a_video_is_cached_under(video):
    _render(video, "clip")
    assert video.sandbox.calls == 1
    os.remove(_path(video, "clip"))
    results = _render(video, "clip", threads=2, memory=512)
    assert video.sandbox.calls == 1 and results["clip"]["success"]
    assert os.path.exists(_path(video, "clip"))
    # Anything else it is told is a file of its own.
    _render(video, "clip", fps=60)
    assert video.sandbox.calls == 2


# ---------------------------------------------------------------------------
# Which tiers keep it
# ---------------------------------------------------------------------------


def test_a_view_of_the_remote_tiers_has_only_them():
    config = types.SimpleNamespace(cache=False)
    cache = Cache("artifacts", config)
    remote = FakeRemote()
    cache.backends = [types.SimpleNamespace(), remote]
    assert cache.tiers(Cache.REMOTE_TIERS).backends == [remote]
    assert cache.tiers(Cache.ALL_TIERS) is cache
    assert not cache.tiers(Cache.NO_TIERS).enabled


def test_a_video_is_kept_in_the_remote_tiers_and_never_on_this_machine(video):
    _render(video, "clip")
    held_remotely = [name for name in video.remote.storage if name.endswith(".artifact")]
    assert held_remotely, sorted(video.remote.storage)
    # The scene is in the files tier; the file is not.
    local = _local_entries(video)
    assert not [name for name in local if name.endswith(".artifact")], local

    # Asked again, it is the remote tier that answers - and the hit is not
    # copied into the files tier, as a hit of anything else would be.
    os.remove(_path(video, "clip"))
    _render(video, "clip")
    assert video.sandbox.calls == 1
    assert _written(video, "clip")["threads"] == 4
    assert not [name for name in _local_entries(video) if name.endswith(".artifact")]


def test_a_file_that_is_not_a_video_is_kept_in_every_tier(video):
    _render(video, "still")
    assert [name for name in _local_entries(video) if name.endswith(".artifact")]
    assert [name for name in video.remote.storage if name.endswith(".artifact")]


def test_a_user_who_keeps_videos_in_every_tier_has_them_on_this_machine_too(video, monkeypatch):
    monkeypatch.setattr(video.ctx.user_config, "video_cache_tiers", "all")
    _render(video, "clip")
    assert [name for name in _local_entries(video) if name.endswith(".artifact")]
    assert [name for name in video.remote.storage if name.endswith(".artifact")]


def test_a_user_who_keeps_videos_nowhere_has_each_made_afresh(video, monkeypatch):
    monkeypatch.setattr(video.ctx.user_config, "video_cache_tiers", "none")
    _render(video, "clip")
    assert not [name for name in _local_entries(video) if name.endswith(".artifact")]
    assert not [name for name in video.remote.storage if name.endswith(".artifact")]
    os.remove(_path(video, "clip"))
    _render(video, "clip")
    assert video.sandbox.calls == 2
    # The scene is still kept, and handed to the second run.
    assert [name for name in video.remote.storage if name.endswith(".artifact-scene")]
    assert _written(video, "clip")["scene"] == "the scene clip built at reels"


# ---------------------------------------------------------------------------
# The scene
# ---------------------------------------------------------------------------


def test_the_scene_one_file_built_is_handed_to_the_next_of_that_size(video):
    results = _render(video, "clip")
    first = _written(video, "clip")
    assert first["scene"] is None and first["scene_wanted"] is True
    # Taken out of what the run answered: it is the cache's.
    assert "scene" not in results["clip"]

    _render(video, "reel")
    second = _written(video, "reel")
    assert second["scene"] == "the scene clip built at reels"
    assert second["scene_wanted"] is None

    # Another size is another scene.
    _render(video, "wide")
    third = _written(video, "wide")
    assert third["scene"] is None and third["scene_wanted"] is True


def test_the_scene_is_kept_in_every_tier(video):
    _render(video, "clip")
    scene_entries = [name for name in video.remote.storage if name.endswith(".artifact-scene")]
    assert scene_entries
    assert [name for name in _local_entries(video) if name.endswith(".artifact-scene")]


def test_a_file_that_is_not_a_video_is_neither_handed_a_scene_nor_asked_for_one(video):
    _render(video, "clip")
    _render(video, "still")
    still = _written(video, "still")
    assert still["scene"] is None and still["scene_wanted"] is None


# ---------------------------------------------------------------------------
# What a video is
# ---------------------------------------------------------------------------


def test_a_video_is_known_by_its_extension_not_by_its_name():
    def impl(section, name, config):
        return output.Implementation(section, name, {"path": "x.py", **config})

    assert impl(output.RENDER, "mp4", {}).is_video
    assert impl(output.EXPORT, "reel", {"extension": "MP4"}).is_video
    assert impl(output.RENDER, "reel", {"extension": ".webm"}).is_video
    assert not impl(output.RENDER, "mp4", {"extension": "png"}).is_video
    assert not impl(output.RENDER, "png", {}).is_video
    # Only a file PartCAD writes for 'pc render' or 'pc export'.
    assert not impl(output.SIMULATE, "mp4", {}).is_video


def test_no_file_type_says_how_a_video_is_run_or_kept():
    import yaml

    for key in ("parallel", "cacheTiers", "sceneCache"):
        assert key not in output.IMPLEMENTATION_KEYS
    path = os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]], "partcad.yaml")
    with open(path) as stream:
        render = yaml.safe_load(stream)["render"]
    videos = [name for name, config in render.items() if (config or {}).get("path") == "render_video.py"]
    assert len(videos) == 10
    for name, config in render.items():
        if not isinstance(config, dict):
            continue
        assert not {"parallel", "cacheTiers", "sceneCache"} & set(config), name
        # Every type 'render_video.py' writes is a video, and nothing else is.
        assert output.Implementation(output.RENDER, name, config).is_video == (name in videos), name
    assert {render[name].get("extension", name) for name in videos} == output.VIDEO_EXTENSIONS


# ---------------------------------------------------------------------------
# The user's configuration
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A '$HOME' of its own, and no 'PC_*' from the environment this runs in."""
    for name in [n for n in os.environ if n.startswith("PC_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".partcad").mkdir()

    def config(text=""):
        (tmp_path / ".partcad" / "config.yaml").write_text(text)
        return pc_user_config.UserConfig()

    return config


def test_a_user_who_says_nothing_has_videos_drawn_in_parallel_and_kept_remotely(home):
    config = home()
    assert config.video_parallel is True
    assert config.video_cache_tiers == "remote"


def test_a_user_says_otherwise_in_the_configuration_or_the_environment(home, monkeypatch):
    config = home("video:\n  parallel: false\n  cacheTiers: ALL\n")
    assert config.video_parallel is False
    assert config.video_cache_tiers == "all"

    monkeypatch.setenv("PC_VIDEO_PARALLEL", "0")
    monkeypatch.setenv("PC_VIDEO_CACHE_TIERS", "none")
    config = home()
    assert config.video_parallel is False
    assert config.video_cache_tiers == "none"


def test_one_of_the_two_in_the_file_and_the_other_in_the_environment(home, monkeypatch):
    # A section the file gives in part, with the rest bound to the environment:
    # how vyper has been known to raise KeyError (see 'SECTION_PATHS').
    monkeypatch.setenv("PC_VIDEO_CACHE_TIERS", "all")
    config = home("video:\n  parallel: false\n")
    assert config.video_parallel is False
    assert config.video_cache_tiers == "all"
    assert config.to_dict()["video.cacheTiers"] == "all"


def test_a_tier_nobody_has_is_the_default(home):
    assert home("video:\n  cacheTiers: nearby\n").video_cache_tiers == "remote"
    assert pc_user_config.video_cache_tiers(None) == "remote"
    assert pc_user_config.video_cache_tiers(" Remote ") == "remote"


def test_the_tiers_a_user_may_name_are_the_ones_the_cache_has():
    assert set(pc_user_config.VIDEO_CACHE_TIERS) == {Cache.ALL_TIERS, Cache.REMOTE_TIERS, Cache.NO_TIERS}


def test_both_settings_travel_to_the_daemon():
    assert "video.parallel" in pc_user_config.OPTION_KEYS
    assert "video.cacheTiers" in pc_user_config.OPTION_KEYS


def test_cache_hash_of_a_scene_is_not_the_files():
    # A scene's key and a file's key never meet: they are hashed under different names.
    assert CacheHash("a#scene", cache=True).name != CacheHash("a#clip", cache=True).name


def test_the_wrapper_names_the_scene_as_partcad_does(monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import wrapper_export

    assert wrapper_export.SCENE_KEY == output.SCENE_KEY
    assert wrapper_export.SCENE_WANTED_KEY == output.SCENE_WANTED_KEY
