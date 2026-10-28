#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The file types of one object, written by one sandbox call.

`pc render` of a package asks for every file type of a shape at once, and those
the cache does not hold are written by one interpreter per sandbox environment
rather than one per file: the CAD stack is imported once and the shape decoded
once (see `Shape._run_together_locked` and `wrapper_export.run_together`). Each
file is still worked out, cached, logged and reported on its own, and one that
fails costs the others nothing.

The wrapper is the real one, run as a subprocess by this interpreter; only the
runtime around it is a stand-in, which counts the calls. The implementations are
scripts of the test's own and the shape carries no geometry, so none of it needs
a CAD sandbox. What the wrapper does with the files of one call - which of them
share a decoding of the object, and in what order they are written - is
`test_output_batch_wrapper.py`'s, which runs it in this process.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import textwrap
import types

import pytest

import partcad as pc
from partcad import output, process_output, runtime, sandbox_versions
from partcad import shape as pc_shape
from partcad import shape_envelope
from partcad.cache import Cache

# Says which file type it is, where it ran, and with what in 'sys.path' and
# 'sys.argv' -- which is what it would have found running on its own. 'crash'
# ends the whole process the first time it is asked, the way a native fault
# would, and 'always_crash' every time; 'fail' is an implementation reporting a
# failure of its own.
WRITE = textwrap.dedent("""
    import os
    import sys


    def process(path, request):
        if request.get("always_crash"):
            os._exit(3)
        marker = request.get("crash")
        if marker and not os.path.exists(marker):
            open(marker, "w").close()
            os._exit(3)
        if request.get("fail"):
            return {"success": False, "exception": "%s cannot be written" % request.get("say")}
        leaked = request.get("leak") in sys.path
        if request.get("leak"):
            sys.path.append(request["leak"])
        with open(path, "w") as f:
            f.write(
                "%s in %s, argv %s, leaked %s"
                % (request.get("say"), os.path.basename(os.getcwd()), sys.argv[1] == path, leaked)
            )
        return {"success": True, "files": []}
    """)


def _cache(tmp_path) -> Cache:
    """A files-only cache of the test's own."""
    config = types.SimpleNamespace(
        cache=True,
        internal_state_dir=str(tmp_path / "state"),
        cache_min_entry_size=1,
        cache_max_entry_size=10 * 1024 * 1024,
    )
    return Cache("artifacts", config)


class _Sandbox:
    """A Python runtime that runs what it is asked with this interpreter, and keeps count.

    Its own environment holds everything but what is named 'layer-...': a file
    type asking for one of those runs in the layer named after them, as
    'PythonRuntime.get_session' has it.
    """

    EXCHANGES_FILES = False

    def __init__(self):
        self.calls = []
        self.sessions = []

    def get_session(self, name):
        return {"name": name, "path": None, "dirty": False, "deps": [], "missing": []}

    def _ask(self, session, python_package):
        if python_package.startswith("unavailable-"):
            raise RuntimeError("No matching distribution found for %s" % python_package)
        if session is None:
            return
        session["deps"].append(python_package)
        if python_package.startswith("layer-") and python_package not in session["missing"]:
            session["missing"].append(python_package)
            session["dirty"] = True
            session["path"] = "layer:" + ",".join(sorted(session["missing"]))

    async def prepare_for_package(self, project, session=None):
        for python_package in project.config_obj.get("pythonRequirements") or []:
            self._ask(session, python_package)

    async def ensure_async(self, python_package, session=None, path=None, force=False):
        self._ask(session, python_package)

    async def run_async(self, cmd, stdin="", session=None, **_kwargs):
        # Bytes, as a request to the Python sandbox is: a frame.
        data = runtime.stdin_bytes(stdin)
        cmd = [part for part in cmd if part != "python"]
        self.calls.append(cmd)
        self.sessions.append(session)
        finished = await asyncio.to_thread(subprocess.run, [sys.executable, *cmd], input=data, capture_output=True)
        # What 'PythonRuntime' does with what a run printed: its answers kept as
        # the bytes of their frames (see 'process_output.answer'), and standard
        # error a warning when it succeeded, the error when it did not.
        stderr = process_output.decode(finished.stderr)
        return finished.returncode, process_output.answer(finished.stdout), stderr if finished.returncode else ""

    def files_per_call(self):
        return [(len(call) - 1) // 3 for call in self.calls]


def _package(root, file_types: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / "partcad.yaml").write_text(
        "name: //batch\nparts:\n  bracket:\n    type: step\n    path: bracket.step\nexport:\n"
        + textwrap.indent(textwrap.dedent(file_types), "  ")
    )
    (root / "write.py").write_text(WRITE)
    (root / "bracket.step").write_text("ISO-10303-21; bracket")


@pytest.fixture
def batch(tmp_path, monkeypatch):
    """A part of a package whose file types are written by 'write.py', and the sandbox that writes them."""
    sandbox = _Sandbox()

    def make(file_types):
        root = tmp_path / "package"
        _package(root, file_types)
        ctx = pc.Context(str(root))
        ctx.cache_artifacts = _cache(tmp_path)
        monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: sandbox)

        async def get_container_runtime(_container):
            return sandbox

        monkeypatch.setattr(ctx, "get_container_runtime", get_container_runtime)
        return ctx

    async def get_wrapped(self, _ctx):
        # A tree with no geometry in it: the wrapper decodes nothing.
        return {"name": self.name, "label": None}

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    return make, sandbox, tmp_path / "out"


THREE = """
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """
THREE_NAMES = ("alpha", "beta", "gamma")


def _render(ctx, out):
    asyncio.run(ctx.get_project("//").render_async(output_dir=str(out)))


def _read(out, name):
    with open(os.path.join(str(out), name)) as f:
        return f.read()


def test_the_file_types_of_a_shape_are_written_by_one_call(batch):
    make, sandbox, out = batch
    ctx = make(THREE)

    _render(ctx, out)

    assert sandbox.files_per_call() == [3]
    # Each as it would have been written on its own: in its package, with its
    # own path in 'sys.argv', and nothing another file type put in 'sys.path'.
    for name in ("alpha", "beta", "gamma"):
        assert _read(out, "bracket." + name) == "%s in package, argv True, leaked False" % name


def test_a_file_type_the_cache_holds_is_not_drawn_again(batch):
    make, sandbox, out = batch
    ctx = make(THREE)

    asyncio.run(ctx.get_part("//:bracket").render_async(ctx, "alpha", output_dir=str(out)))
    _render(ctx, out)
    assert sandbox.files_per_call() == [1, 2]
    assert "alpha" not in " ".join(sandbox.calls[1])

    for name in ("alpha", "beta", "gamma"):
        os.remove(os.path.join(str(out), "bracket." + name))
    _render(ctx, out)
    # Every one of them from the cache, under its own key.
    assert sandbox.files_per_call() == [1, 2]
    assert _read(out, "bracket.gamma").startswith("gamma in package")


def test_several_file_types_say_what_each_answered_in_the_order_asked(batch):
    """'render_async' answers for every file type it was asked for, written together or not."""
    make, sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")

    results = asyncio.run(part.render_async(ctx, ["gamma", "alpha", "beta"], output_dir=str(out)))

    assert sandbox.files_per_call() == [3]
    assert list(results) == ["gamma", "alpha", "beta"]
    assert all(result["success"] for result in results.values())
    # And one asked for alone, under the name it was asked for by.
    assert list(asyncio.run(part.render_async(ctx, "alpha", output_dir=str(out)))) == ["alpha"]


def test_a_section_cuts_every_file_type_of_a_batch_and_is_part_of_each_key(batch, monkeypatch):
    """Each file type is cut as it is when asked for alone, and a cut is never answered for the whole."""
    make, sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")
    cuts = []

    async def section_async(_ctx, tree, section, cacheable=True):
        cuts.append(section)
        return dict(tree, cut=section)

    monkeypatch.setattr(pc_shape.shape_section, "section_async", section_async)
    formats = ["alpha", "beta", "gamma"]

    asyncio.run(part.render_async(ctx, formats, output_dir=str(out), section={"z": [0, 5], "x": None}))
    assert cuts == [{"z": [0.0, 5.0]}] * 3
    assert sandbox.files_per_call() == [3]

    # The whole shape is another question, and so is another cut ...
    asyncio.run(part.render_async(ctx, formats, output_dir=str(out)))
    asyncio.run(part.render_async(ctx, formats, output_dir=str(out), section={"z": [1, 5]}))
    assert sandbox.files_per_call() == [3, 3, 3]
    # ... and the same one again is the cache's.
    asyncio.run(part.render_async(ctx, formats, output_dir=str(out), section={"z": [0, 5]}))
    assert sandbox.files_per_call() == [3, 3, 3]


def test_what_one_sandbox_path_leaves_behind_is_not_seen_by_the_next(batch):
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha, leak: /nowhere}
    beta: {path: write.py, extension: beta, say: beta, leak: /nowhere}
    """)

    _render(ctx, out)
    assert sandbox.files_per_call() == [2]
    assert _read(out, "bracket.beta").endswith("leaked False")


def test_a_file_type_that_fails_does_not_stop_the_others(batch, caplog):
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, fail: true}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """)

    _render(ctx, out)

    assert sandbox.files_per_call() == [3]
    assert _read(out, "bracket.gamma").startswith("gamma")
    assert not os.path.exists(os.path.join(str(out), "bracket.beta"))
    # The message a failed file type has always had.
    assert "Render BETA failed for //batch:bracket: beta cannot be written" in caplog.text


def test_a_file_the_call_did_not_finish_is_written_by_a_call_of_its_own(batch, caplog, tmp_path):
    """The process dies writing the second file: the first is answered, and the other two are written alone."""
    make, sandbox, out = batch
    marker = str(tmp_path / "crashed").replace("\\", "/")
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, crash: "%s"}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """ % marker)

    with caplog.at_level(logging.WARNING):
        _render(ctx, out)

    assert sandbox.files_per_call() == [3, 1, 1]
    for name in ("alpha", "beta", "gamma"):
        assert _read(out, "bracket." + name).startswith(name)
    assert "stopped before it wrote beta, gamma" in caplog.text


def test_a_file_that_crashes_on_its_own_too_fails_as_it_always_did(batch):
    """Written alone it crashes again, and that is raised - as it was before any of this."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, always_crash: true}
    """)

    with pytest.raises(Exception, match="Failed to execute command") as raised:
        _render(ctx, out)
    # The call of its own, which names that file and no other.
    assert "bracket.beta" in str(raised.value) and "bracket.alpha" not in str(raised.value)
    assert sandbox.files_per_call() == [2, 1]
    assert _read(out, "bracket.alpha").startswith("alpha")


def test_two_file_types_that_write_one_path_are_not_written_by_one_call(batch):
    """The one left there is the one asked for last, and neither run is remembered as the other's file."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: toy, say: alpha}
    beta: {path: write.py, extension: toy, say: beta}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """)

    _render(ctx, out)
    assert sandbox.files_per_call() == [2, 1]
    assert _read(out, "bracket.toy").startswith("beta")


def test_file_types_of_another_environment_are_written_by_a_call_of_their_own(batch):
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, pythonVersion: "3.12"}
    gamma: {path: write.py, extension: gamma, say: gamma}
    delta: {path: write.py, extension: delta, say: delta, container: {image: example/solver:1}}
    """)

    _render(ctx, out)
    assert sorted(sandbox.files_per_call()) == [1, 1, 2]
    for name in ("alpha", "beta", "gamma", "delta"):
        assert _read(out, "bracket." + name).startswith(name)


def test_the_requirements_of_several_file_types_are_asked_for_in_an_order_that_keeps_them(batch):
    """glTF's list after STEP's, each package once where it first appears, would end in build123d.

    Which a sandbox keeping one environment, installing in the order asked,
    would leave with OCP's build without VTK.
    """
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha, pythonRequirements: ["%s"]}
    beta: {path: write.py, extension: beta, say: beta, pythonRequirements: ["%s", "%s"]}
    """ % (sandbox_versions.CADQUERY_OCP, sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP))

    _render(ctx, out)
    assert sandbox.files_per_call() == [2]
    assert sandbox.sessions[0]["deps"] == [sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP]


def test_file_types_are_written_together_with_those_of_their_own_layer(batch):
    """Each runs where it would have run alone: the base, or the layer its requirements make."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, pythonRequirements: [layer-raster]}
    gamma: {path: write.py, extension: gamma, say: gamma}
    delta: {path: write.py, extension: delta, say: delta, pythonRequirements: [layer-raster]}
    epsilon: {path: write.py, extension: epsilon, say: epsilon, pythonRequirements: [layer-cad]}
    """)

    _render(ctx, out)

    written = {}
    for call, session in zip(sandbox.calls, sandbox.sessions):
        layer = session["path"] if session["dirty"] else "base"
        written[layer] = sorted(os.path.basename(call[index]) for index in range(1, len(call), 3))
    assert written == {
        "base": ["bracket.alpha", "bracket.gamma"],
        "layer:layer-raster": ["bracket.beta", "bracket.delta"],
        "layer:layer-cad": ["bracket.epsilon"],
    }


def test_every_file_type_is_still_an_action_of_its_own(batch, caplog):
    make, _sandbox, out = batch
    ctx = make(THREE)

    with caplog.at_level(logging.DEBUG):
        _render(ctx, out)
    for name in ("ALPHA", "BETA", "GAMMA"):
        assert "DONE: Render%s: //batch: bracket:" % name in caplog.text


def test_a_caller_holding_the_shape_writes_each_file_type_on_its_own(batch):
    """A batch's file types are worked out in tasks of their own, which could never take a lock it held."""
    make, sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")

    async def held():
        async with part.locked():
            await part.render_async(ctx, ["alpha", "beta"], output_dir=str(out))

    asyncio.run(held())
    assert sandbox.files_per_call() == [1, 1]


def test_asked_for_no_file_type_in_particular_every_one_is_written_by_one_call(batch, monkeypatch):
    """'render_async' with no file type writes every one there is, and writes them together as well.

    Every one there is means every built-in one, which would need a CAD sandbox
    here; the package's own three stand in for them.
    """
    make, sandbox, out = batch
    ctx = make(THREE)
    monkeypatch.setattr(output, "all_formats", lambda _ctx: ["gamma", "alpha", "beta"])

    results = asyncio.run(ctx.get_part("//:bracket").render_async(ctx, None, output_dir=str(out)))

    assert sandbox.files_per_call() == [3]
    assert list(results) == ["gamma", "alpha", "beta"]
    assert all(result["success"] for result in results.values())


def test_an_empty_shape_writes_none_of_the_file_types_asked_for(batch, monkeypatch, caplog):
    """Each file type says so under its own action, and the batch they were in starts no sandbox."""
    make, sandbox, out = batch
    ctx = make(THREE)

    async def get_wrapped(self, _ctx):
        return None

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)

    results = asyncio.run(ctx.get_part("//:bracket").render_async(ctx, ["alpha", "beta"], output_dir=str(out)))

    assert results == {}
    assert sandbox.calls == []
    assert caplog.text.count("Cannot render 'bracket': shape is empty") == 2


def test_the_file_types_of_one_render_are_handed_one_tree(batch, monkeypatch):
    """A shape the memory tier does not keep answers each 'get_wrapped' with a tree of its own.

    Asked for once per file type, a batch would carry one copy per file - the
    subjects are told apart by identity - and no two files could share a
    decoding: exactly the large objects batching is for.
    """
    make, sandbox, out = batch
    ctx = make(THREE)
    fetched = []

    async def get_wrapped(self, _ctx):
        fetched.append(self.name)
        return {"name": self.name, "label": None}

    documents = []
    together_request = pc_shape._together_request

    def spy(outputs):
        documents.append(together_request(outputs))
        return documents[-1]

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    monkeypatch.setattr(pc_shape, "_together_request", spy)

    results = asyncio.run(ctx.get_part("//:bracket").render_async(ctx, list(THREE_NAMES), output_dir=str(out)))

    assert all(result["success"] for result in results.values())
    assert fetched == ["bracket"]
    assert sandbox.files_per_call() == [3]
    assert [len(document[output.BATCH_SUBJECTS_KEY]) for document in documents] == [1]


def test_a_sandbox_that_sends_files_back_is_told_every_file_a_call_writes(batch, monkeypatch):
    """What a command writes is not in its request, so a sandbox exchanging files has to be told all of them."""
    make, _sandbox, out = batch
    ctx = make(THREE)

    class Exchanging(_Sandbox):
        EXCHANGES_FILES = True

        def __init__(self):
            super().__init__()
            self.sent_back = []

        async def run_async(self, cmd, stdin="", session=None, output_files=None, **kwargs):
            self.sent_back.append(output_files)
            return await super().run_async(cmd, stdin, session=session, **kwargs)

    exchanging = Exchanging()
    monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: exchanging)

    _render(ctx, out)

    assert exchanging.files_per_call() == [3]
    (sent_back,) = exchanging.sent_back
    assert sorted(sent_back) == [os.path.join(os.path.abspath(str(out)), "bracket." + name) for name in THREE_NAMES]


@pytest.mark.parametrize(
    "said, reported",
    [
        ("", "Empty response from the 'alpha' implementation"),
        ("not an answer", "Failed to deserialize response"),
    ],
)
def test_a_file_type_whose_call_says_nothing_readable_is_reported_and_answered_with_none(
    batch, monkeypatch, caplog, said, reported
):
    """Asked for alone, as a file type always was: the call that writes it is the one there always was."""
    make, _sandbox, out = batch
    ctx = make(THREE)

    class Mute(_Sandbox):
        async def run_async(self, cmd, stdin="", session=None, **_kwargs):
            self.calls.append(cmd)
            return 0, said, ""

    mute = Mute()
    monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: mute)

    results = asyncio.run(ctx.get_part("//:bracket").render_async(ctx, "alpha", output_dir=str(out)))

    assert results == {"alpha": None}
    assert mute.files_per_call() == [1]
    assert reported in caplog.text


def test_a_file_type_asked_for_alone_that_cannot_be_written_raises_as_it_always_did(batch):
    make, sandbox, out = batch
    ctx = make("""
    beta: {path: write.py, extension: beta, say: beta, always_crash: true}
    """)

    with pytest.raises(Exception, match="Failed to execute command"):
        asyncio.run(ctx.get_part("//:bracket").render_async(ctx, "beta", output_dir=str(out)))
    assert sandbox.files_per_call() == [1]


def test_a_file_type_whose_requirements_cannot_be_installed_fails_on_its_own(batch):
    """Which environment it would run in cannot be told, so it is written alone - and fails there, and only there."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, pythonRequirements: [unavailable-raster]}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """)

    with pytest.raises(RuntimeError, match="No matching distribution found for unavailable-raster"):
        _render(ctx, out)

    # Never started: the install it needed is what failed.
    assert sandbox.files_per_call() == [2]
    assert _read(out, "bracket.alpha").startswith("alpha") and _read(out, "bracket.gamma").startswith("gamma")
    assert not os.path.exists(os.path.join(str(out), "bracket.beta"))


def test_a_file_type_whose_container_is_declared_wrongly_fails_on_its_own(batch):
    """A 'container:' that names no image is the declaration's mistake, said for that file type alone."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, container: {port: 5000}}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """)

    with pytest.raises(ValueError, match="names no 'image:'"):
        _render(ctx, out)

    assert sandbox.files_per_call() == [2]
    assert _read(out, "bracket.alpha").startswith("alpha") and _read(out, "bracket.gamma").startswith("gamma")


def test_a_sandbox_that_cannot_start_fails_every_file_of_the_call_and_is_not_asked_again(batch, monkeypatch):
    """Nothing ran, so the reason is the same for every file of it: none is written again on its own."""
    make, _sandbox, out = batch
    ctx = make(THREE)

    class Absent(_Sandbox):
        async def run_async(self, cmd, stdin="", session=None, **_kwargs):
            self.calls.append(cmd)
            raise RuntimeError("the sandbox is not there")

    absent = Absent()
    monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: absent)

    with pytest.raises(RuntimeError, match="the sandbox is not there"):
        asyncio.run(ctx.get_part("//:bracket").render_async(ctx, ["alpha", "beta", "gamma"], output_dir=str(out)))
    assert absent.files_per_call() == [3]


def test_a_file_the_call_says_nothing_of_is_written_again_though_the_call_ended_well(batch, monkeypatch, caplog):
    """The wrapper leaves a file unanswered when it fails before reaching its implementation, and exits 0.

    The stand-in here loses that file's answer instead. Either way the call
    said nothing of it, which is all the core goes by: it writes it again on
    its own, and says so only to whoever is debugging, since nothing failed.
    """
    make, _sandbox, out = batch
    ctx = make(THREE)

    class Forgetful(_Sandbox):
        async def run_async(self, cmd, stdin="", session=None, **kwargs):
            code, said, errors = await super().run_async(cmd, stdin, session=session, **kwargs)
            if len(cmd) > 4:
                # A frame each (see 'shape_envelope.serialize'): all of them
                # written again, but the one for the second file.
                answers = shape_envelope.deserialize_all(said)
                said = b"".join(shape_envelope.serialize(answer) for answer in answers if answer["output"] != 1)
            return code, said, errors

    forgetful = Forgetful()
    monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: forgetful)

    with caplog.at_level(logging.DEBUG):
        _render(ctx, out)

    assert forgetful.files_per_call() == [3, 1]
    for name in THREE_NAMES:
        assert _read(out, "bracket." + name).startswith(name)
    assert "not answered by the call writing 3 files at once, written again on its own: beta" in caplog.text
    assert "stopped before it wrote" not in caplog.text


def _left_running():
    """The tasks of this loop other than the one asking: what a render left behind when it returned."""
    return [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]


def test_a_file_type_that_does_not_resolve_fails_once_the_others_are_written(batch):
    """It fails before it is handed in, and the batch is still the others' to finish before the render says so.

    Raised as it happened, the failure reached the caller while the other file
    types were still being worked out, and they went on doing it in tasks
    nobody waited for: written after the render had failed, or - when the loop
    ended first - not at all.
    """
    make, sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")

    async def scenario():
        with pytest.raises(Exception, match="No implementation of 'nope' is declared"):
            await part.render_async(ctx, ["alpha", "nope", "gamma"], output_dir=str(out))
        return _left_running()

    assert asyncio.run(scenario()) == []
    assert sandbox.files_per_call() == [2]
    assert _read(out, "bracket.alpha").startswith("alpha") and _read(out, "bracket.gamma").startswith("gamma")


def test_a_render_cancelled_before_every_file_type_is_handed_in_starts_no_sandbox(batch, monkeypatch):
    """Nobody is waiting for the files handed in by then, so nothing writes them, and the cancellation is not held up.

    The second file type is still being worked out - cut, here - when the
    render is cancelled. Giving up on it is what completes the batch, and the
    first one's file is no longer anybody's to wait for: the batch used to
    start a sandbox call for it all the same, in a task the cancelled render
    had already stopped waiting for.
    """
    make, sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")
    cuts = []

    async def scenario():
        cutting = asyncio.Event()

        async def section_async(_ctx, tree, section, cacheable=True):
            cuts.append(section)
            if len(cuts) > 1:
                cutting.set()
                await asyncio.Event().wait()
            return tree

        monkeypatch.setattr(pc_shape.shape_section, "section_async", section_async)
        task = asyncio.ensure_future(
            part.render_async(ctx, ["alpha", "beta"], output_dir=str(out), section={"z": [0, 5]})
        )
        await asyncio.wait_for(cutting.wait(), 60)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 60)
        return _left_running()

    assert asyncio.run(scenario()) == []
    assert len(cuts) == 2
    assert sandbox.calls == []


def test_a_render_cancelled_while_its_files_are_written_leaves_nothing_running(batch, monkeypatch):
    make, _sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")

    async def scenario():
        started = asyncio.Event()

        class Slow(_Sandbox):
            async def run_async(self, cmd, stdin="", session=None, **_kwargs):
                self.calls.append(cmd)
                started.set()
                await asyncio.Event().wait()

        slow = Slow()
        monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: slow)
        task = asyncio.ensure_future(part.render_async(ctx, ["alpha", "beta"], output_dir=str(out)))
        await asyncio.wait_for(started.wait(), 60)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 60)
        return slow, _left_running()

    slow, left = asyncio.run(scenario())
    assert slow.files_per_call() == [2]
    assert left == []


def test_a_batch_answers_whoever_still_waits_and_its_failure_is_every_members():
    """A member that gave up waiting while the call ran is not answered, and the others are answered all the same."""
    calls = []

    async def scenario():
        running = asyncio.Event()
        finish = asyncio.Event()

        async def outputs_run_async(_ctx, outputs, _cache):
            calls.append(list(outputs))
            running.set()
            await finish.wait()
            if outputs[0] == "fails":
                raise RuntimeError("the cache could not be read")
            return ["first", "second"]

        async def member(batch, output_):
            async with batch.member():
                return await batch.submit(None, output_)

        # One member stops waiting while the call runs.
        batch = pc_shape._OutputBatch(types.SimpleNamespace(_outputs_run_async=outputs_run_async), None, 2)
        first = asyncio.ensure_future(member(batch, "a"))
        second = asyncio.ensure_future(member(batch, "b"))
        await asyncio.wait_for(running.wait(), 60)
        first.cancel()
        finish.set()
        assert await asyncio.wait_for(second, 60) == "second"
        assert first.cancelled()

        # And what the call raises, every member raises.
        running.clear()
        batch = pc_shape._OutputBatch(types.SimpleNamespace(_outputs_run_async=outputs_run_async), None, 2)
        members = [asyncio.ensure_future(member(batch, name)) for name in ("fails", "too")]
        results = await asyncio.wait_for(asyncio.gather(*members, return_exceptions=True), 60)
        assert [str(result) for result in results] == ["the cache could not be read"] * 2

    asyncio.run(scenario())
    assert calls == [["a", "b"], ["fails", "too"]]


def test_only_the_lines_that_answer_for_a_file_of_the_call_are_answers():
    """Whatever else reaches the call's output - a library's chatter, an answer for no file of it - is passed over."""
    said = "\n".join(
        [
            "",
            "Warning: something a library printed",
            json.dumps([0, {"success": True}]),
            json.dumps({"output": 0, "result": {"success": True}}),
            json.dumps({"output": 3, "result": {"success": True}}),
            json.dumps({"output": True, "result": {"success": True}}),
            json.dumps({"output": 1, "result": "written"}),
            "   ",
            json.dumps({"output": 2, "result": {"success": False}}),
        ]
    )
    assert pc_shape._together_answers(said, 3) == {0: {"success": True}, 2: {"success": False}}


def _frames(*answers):
    """Answers as the Python sandbox writes them: a frame each (see 'shape_envelope.serialize')."""
    return b"".join(shape_envelope.serialize(answer) for answer in answers)


def test_only_the_frames_that_answer_for_a_file_of_the_call_are_answers():
    """As the lines are, in the form a call asked in a frame answers in - with its payloads the bytes they are."""
    said = b"".join(
        [
            b"Warning: something a library printed\n",
            _frames([0, {"success": True}], {"output": 0, "result": {"success": True, "blob": b"\x00\xff"}}),
            b"\n",
            _frames(
                {"output": 3, "result": {"success": True}},
                {"output": True, "result": {"success": True}},
                {"output": 1, "result": "written"},
                {"output": 2, "result": {"success": False}},
            ),
        ]
    )
    assert pc_shape._together_answers(process_output.answer(said), 3) == {
        0: {"success": True, "blob": b"\x00\xff"},
        2: {"success": False},
    }


def test_a_frame_cut_off_is_no_answer_for_its_file():
    """The process died while writing it: the file is written again on its own, and those before it are answered."""
    whole = _frames({"output": 0, "result": {"success": True}})
    cut = _frames({"output": 1, "result": {"success": True, "blob": b"\x00" * 1000}})[:-10]
    assert pc_shape._together_answers(process_output.answer(whole + cut), 2) == {0: {"success": True}}
    # And a first frame cut off leaves no frame at all, which is text, and no answer.
    assert pc_shape._together_answers(process_output.answer(cut), 2) == {}


# --------------------------------------------------------------------------- #
# Which sandbox a file type runs in                                           #
# --------------------------------------------------------------------------- #


def _impl(name, container=None, version="3.11", image=None):
    return types.SimpleNamespace(
        container=container,
        project=types.SimpleNamespace(name=name),
        python_version=lambda: version,
        docker_image=image,
    )


def test_built_in_implementations_share_a_sandbox_and_packages_do_not():
    sandbox_of = pc_shape._sandbox_of
    assert sandbox_of(_impl("//builtin/render")) == sandbox_of(_impl("//builtin/export"))
    assert sandbox_of(_impl("//pub/plugin")) == sandbox_of(_impl("//pub/plugin"))
    assert sandbox_of(_impl("//pub/plugin")) != sandbox_of(_impl("//pub/other"))
    assert sandbox_of(_impl("//pub/plugin")) != sandbox_of(_impl("//pub/plugin", version="3.12"))
    assert sandbox_of(_impl("//pub/plugin")) != sandbox_of(_impl("//pub/plugin", image="example/sandbox:1"))
    # A container is a process of its own.
    assert sandbox_of(_impl("//pub/plugin", container={"image": "example/solver:1"})) is None


def test_rounds_keep_two_files_at_one_path_apart():
    paths = ["/out/a.json", "/out/b.stl", "/out/a.json", "/out/c.svg", "/out/a.json"]
    outputs = [pc_shape._Output(None, None, {}, path) for path in paths]
    assert pc_shape._rounds(outputs) == [[0, 1, 3], [2], [4]]


def test_the_object_travels_once_however_many_files_are_of_it():
    tree = {"name": "bracket", "brep": b"geometry"}
    view = {"name": "bracket", "assembly": []}
    outputs = [
        pc_shape._Output(None, None, {"wrapped": tree, "say": "a"}, "a"),
        pc_shape._Output(None, None, {"wrapped": view, "say": "b"}, "b"),
        pc_shape._Output(None, None, {"wrapped": tree, "say": "c"}, "c"),
        pc_shape._Output(None, None, {"say": "d"}, "d"),
    ]
    document = pc_shape._together_request(outputs)
    assert document[output.BATCH_SUBJECTS_KEY] == [tree, view]
    entries = document[output.BATCH_OUTPUTS_KEY]
    assert [entry.get(output.BATCH_SUBJECT_KEY) for entry in entries] == [0, 1, 0, None]
    assert all("wrapped" not in entry[output.BATCH_REQUEST_KEY] for entry in entries)
    # The requests themselves are left as they were.
    assert outputs[0].request["wrapped"] is tree


# --------------------------------------------------------------------------- #
# The built-in file types, in a real sandbox                                  #
# --------------------------------------------------------------------------- #

SCREW = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "..",
    "examples",
    "feature_interface",
    "socket-head-m3-screw-6mm.step",
)


def _contents(path):
    """A file's bytes, less what the format stamps with the clock: a 3MF's creation date."""
    import re
    import zipfile

    if path.endswith(".3mf"):
        with zipfile.ZipFile(path) as archive:
            return [(name, re.sub(rb'"CreationDate">[^<]*<', b"", archive.read(name))) for name in archive.namelist()]
    with open(path, "rb") as f:
        return f.read()


@pytest.mark.slow
def test_built_in_files_written_together_are_the_files_written_alone(tmp_path, monkeypatch):
    """Byte for byte, the file types that share a decoding and a mesh included.

    The SVG, the STL, the OBJ and the three.js file run in the sandbox's own
    environment and are written by one call, the PNG and the JPEG in the layer
    that rasterizes and by another, and the 3MF in CadQuery's, alone. PNG and
    JPEG share a decoding and a mesh ('render_svg.TESSELLATION'), and so do OBJ
    and three.js: a file written after its group's first one finds that one's
    mesh on the shape, and has to come out as though it had made it.
    """
    from partcad import runtime_python

    root = tmp_path / "package"
    root.mkdir()
    with open(SCREW, "rb") as source, open(root / "screw.step", "wb") as target:
        target.write(source.read())
    (root / "partcad.yaml").write_text(textwrap.dedent("""
        name: //together
        parts:
          screw:
            type: step
        render:
          svg:
          png:
          jpeg:
        export:
          stl:
          3mf:
          obj:
          threejs:
            extension: three.json
        """))

    calls = []
    original = runtime_python.PythonRuntime.run_async_onced

    async def counted(self, cmd, *args, **kwargs):
        if os.path.basename(str(cmd[0])) == "wrapper_export.py":
            calls.append((len(cmd) - 1) // 3)
        return await original(self, cmd, *args, **kwargs)

    monkeypatch.setattr(runtime_python.PythonRuntime, "run_async_onced", counted)

    formats = ("svg", "png", "jpeg", "stl", "3mf", "obj", "threejs")
    ctx = pc.Context(str(root))
    ctx.cache_artifacts = None
    together, alone = tmp_path / "together", tmp_path / "alone"
    asyncio.run(ctx.get_project("//").render_async(output_dir=str(together)))
    assert sorted(calls) == [1, 2, 4]

    part = ctx.get_part("//:screw")
    for format_name in formats:
        asyncio.run(part.render_async(ctx, format_name, output_dir=str(alone)))

    names = sorted(os.listdir(alone))
    assert names == sorted(os.listdir(together)) and len(names) == len(formats)
    for name in names:
        assert _contents(str(together / name)) == _contents(str(alone / name)), name
