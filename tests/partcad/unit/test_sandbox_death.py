#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A sandbox process that dies is noticed, reported, and let go of.

What wedged the daemon for good: a sandbox interpreter killed mid-run -- by the
out-of-memory killer, as a big render's wrapper was -- while something it had
started still held its standard output or standard error. PartCAD waited for
those pipes to reach their end rather than for the process, so it went on
waiting after the process was gone, for as long as whatever held them lived:
forever, for a run with no bound. And it waited holding a process slot, the
environment's lock, the shape's lock and -- in the daemon -- the one lock every
request is served under, so every command after it waited too.

Every sandbox here is a tiny interpreter that does exactly that: starts a
child that inherits its pipes and sleeps, writes half an answer, and kills
itself the way the kernel would. Nothing provisions a CAD environment.
"""

import asyncio
import base64
import os
import signal
import subprocess
import sys
import threading
import time
import types

import psutil
import pytest

from partcad import runtime as pc_runtime
from partcad import runtime_python, sandbox_lock
from partcad_utils import container_service

POSIX = os.name != "nt"

posix = pytest.mark.skipif(not POSIX, reason="a sandbox is killed here by a POSIX signal")

# How long a dead sandbox may take to be noticed and let go of, in seconds. The
# grace is two seconds; this is a ceiling with room for a loaded runner, and far
# below the 300 s of silence a client waits before giving up on the daemon.
WITHIN = 20.0

# The child the sandbox leaves behind: it holds the sandbox's pipes, because it
# inherited them, and it outlives the sandbox by ten minutes.
SLEEPER = "import time; time.sleep(600)"


def _dies(pids, answer="half an answer", end="os.kill(os.getpid(), signal.SIGKILL)"):
    """A sandbox that starts a child holding its pipes, says something, and ends."""
    return (
        "import os, signal, subprocess, sys\n"
        "sys.stdin.buffer.read()\n"
        "child = subprocess.Popen([sys.executable, '-c', %r])\n"
        "open(%r, 'w').write(str(child.pid))\n"
        "sys.stdout.write(%r)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('working on it\\n')\n"
        "sys.stderr.flush()\n"
        "%s\n" % (SLEEPER, str(pids), answer, end)
    )


def _gone(pid, within=5.0):
    """Whether 'pid' is no longer running (a zombie nobody reaped counts as gone)."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def pids(tmp_path):
    """Where the sandbox writes the pid of the child it leaves; that child is killed afterwards whatever happened."""
    path = tmp_path / "pids"
    yield path
    if path.exists():
        try:
            os.kill(int(path.read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def _left(pids):
    return int(pids.read_text())


def _in_thread(fn, within=WITHIN):
    """Call 'fn' on a thread of its own, and give up on it after 'within' seconds.

    So that a run which never returns fails its test instead of hanging the
    suite -- which is what it did before there was anything to notice a death.
    """
    result = {}

    def call():
        try:
            result["value"] = fn()
        except BaseException as e:  # pylint: disable=broad-except
            result["error"] = e

    thread = threading.Thread(target=call, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(within)
    assert not thread.is_alive(), "still waiting for a sandbox %gs after it died" % within
    if "error" in result:
        raise result["error"]
    return result["value"], time.monotonic() - started


def _ctx(tmp_path):
    return types.SimpleNamespace(user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path)))


@pytest.fixture
def python_runtime(tmp_path):
    """A 'PythonRuntime' that runs this interpreter and provisions nothing."""
    made = runtime_python.PythonRuntime(_ctx(tmp_path), "test", "3.11")
    made.exec_path = sys.executable
    made.provisioned = True
    return made


def _all_slots_free():
    """Whether every process slot can be taken right now -- none is held by a run that is over."""
    slots = sandbox_lock.process_slots
    taken = 0
    try:
        while taken < slots.count and slots._try_acquire():
            taken += 1
        return taken == slots.count
    finally:
        for _ in range(taken):
            slots._release()


def _free(lock, within=5.0):
    """Whether the environment lock can be taken for writing: nobody is still reading through it."""
    taken = threading.Event()

    def take():
        with lock.acquire(write=True):
            taken.set()

    threading.Thread(target=take, daemon=True).start()
    return taken.wait(within)


# --------------------------------------------------------------------------- #
# The wait itself                                                              #
# --------------------------------------------------------------------------- #


@posix
@pytest.mark.parametrize("timeout", [None, 600.0], ids=["unbounded", "bounded"])
def test_a_sandbox_killed_while_what_it_started_holds_its_output_is_noticed(pids, timeout):
    """Unbounded, this was forever; bounded, it was the whole bound -- here ten minutes."""

    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _dies(pids),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **pc_runtime.bounded_spawn_options(timeout),
        )
        started = time.monotonic()
        try:
            out, err = await asyncio.wait_for(pc_runtime.communicate(p, b"a request", timeout), WITHIN)
        except asyncio.TimeoutError:
            pytest.fail("still waiting for a sandbox %gs after it died" % WITHIN)
        return p.returncode, out, err, time.monotonic() - started

    returncode, out, err, took = asyncio.run(main())

    assert returncode == -signal.SIGKILL
    # What it said before it died is kept: it is what says how far it got.
    assert out == b"half an answer"
    assert b"working on it" in err
    assert took < WITHIN
    # And what it left behind holding the pipes is stopped with it.
    assert _gone(_left(pids))


@posix
def test_a_sandbox_that_ends_well_is_not_held_open_by_what_it_left_behind(pids):
    """A wrapper that answered and exited has answered, whatever is still running."""

    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _dies(pids, answer="the whole answer", end="sys.exit(0)"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            out, _ = await asyncio.wait_for(pc_runtime.communicate(p, b"a request"), WITHIN)
        except asyncio.TimeoutError:
            pytest.fail("still waiting for a sandbox %gs after it exited" % WITHIN)
        return p.returncode, out

    returncode, out = asyncio.run(main())

    assert returncode == 0
    assert out == b"the whole answer"
    assert _gone(_left(pids))


@posix
def test_a_sandbox_that_dies_alone_is_reported_at_once(tmp_path):
    """Nothing holding its pipes: noticed the moment they close, as it always was."""

    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import os, signal, sys; sys.stdin.read(); os.kill(os.getpid(), signal.SIGKILL)",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        started = time.monotonic()
        await asyncio.wait_for(pc_runtime.communicate(p, b""), WITHIN)
        return p.returncode, time.monotonic() - started

    returncode, took = asyncio.run(main())

    assert returncode == -signal.SIGKILL
    assert took < 2.0


# --------------------------------------------------------------------------- #
# The run that depended on it                                                  #
# --------------------------------------------------------------------------- #


@posix
def test_the_run_fails_naming_the_signal_and_what_it_usually_means(python_runtime, pids):
    def run():
        return asyncio.run(python_runtime.run_async_onced(["-c", _dies(pids)], "a request"))

    (exitcode, stdout, stderr), took = _in_thread(run)

    assert exitcode == -signal.SIGKILL
    assert stdout == "half an answer"
    assert "killed by signal 9 (SIGKILL)" in stderr
    assert "out-of-memory killer" in stderr
    assert took < WITHIN


@posix
def test_everything_held_for_the_run_is_let_go_and_the_next_run_works(python_runtime, pids):
    """The slot, the environment's lock: a run after the death must not queue behind it."""

    def run():
        return asyncio.run(python_runtime.run_async_onced(["-c", _dies(pids)], "a request"))

    _in_thread(run)

    assert _all_slots_free()
    assert _free(python_runtime.environment_lock())

    def again():
        return asyncio.run(python_runtime.run_async_onced(["-c", "print('again')"], ""))

    (exitcode, stdout, stderr), _ = _in_thread(again)
    assert exitcode == 0, stderr
    assert stdout.strip() == "again"


@posix
def test_the_synchronous_run_is_held_to_the_same(python_runtime, pids):
    """'run_onced', which provisioning goes through, waits the same way and must stop the same way."""
    (exitcode, stdout, stderr), took = _in_thread(lambda: python_runtime.run_onced(["-c", _dies(pids)], "a request"))

    assert exitcode == -signal.SIGKILL
    assert stdout == "half an answer"
    assert "SIGKILL" in stderr
    assert took < WITHIN
    assert _gone(_left(pids))
    assert _all_slots_free()


@posix
def test_the_base_runtime_s_synchronous_run_too(tmp_path, pids):
    made = pc_runtime.Runtime(_ctx(tmp_path), "plain")

    (exitcode, stdout, stderr), took = _in_thread(
        lambda: made.run([sys.executable, "-c", _dies(pids)], stdin="a request")
    )

    assert exitcode == -signal.SIGKILL
    assert stdout == "half an answer"
    assert "SIGKILL" in stderr
    assert took < WITHIN
    assert _gone(_left(pids))


@posix
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_an_install_whose_pip_was_killed_is_not_recorded_and_fails_saying_so(
    python_runtime, tmp_path, monkeypatch, asynchronous
):
    """Recorded, a half-written install was a package every later run believed was there."""
    killed = ["-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"]
    monkeypatch.setattr(python_runtime, "pip_install_command", lambda package, force: killed)
    # The runtime's own environment, whose interpreter is this one.
    path = python_runtime.path
    os.makedirs(path, exist_ok=True)

    with pytest.raises(RuntimeError, match=r"Installing 'cq_warehouse' into .* did not finish: .*SIGKILL"):
        if asynchronous:
            asyncio.run(python_runtime.install_async_onced_locked("cq_warehouse", path))
        else:
            python_runtime.install_onced_locked("cq_warehouse", path)

    assert not python_runtime.installed_onced("cq_warehouse", path)


def test_an_install_that_ran_to_the_end_is_recorded_as_it_always_was(python_runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(python_runtime, "pip_install_command", lambda package, force: ["-c", "import sys; sys.exit(1)"])
    # The runtime's own environment, whose interpreter is this one.
    path = python_runtime.path
    os.makedirs(path, exist_ok=True)

    asyncio.run(python_runtime.install_async_onced_locked("cq_warehouse", path))

    assert python_runtime.installed_onced("cq_warehouse", path)


# --------------------------------------------------------------------------- #
# Inside a container                                                           #
# --------------------------------------------------------------------------- #


@posix
def test_the_container_service_answers_for_a_command_that_died(pids):
    """The same wait, one level down: the service in every container ran its command the same way.

    Every command of the 'remote' sandbox and of the 'docker' one in 'upload'
    mode goes through it, and its caller waits on the HTTP answer with no
    bound -- so a command that died there left the request open for good, and
    the environment's lock on the volume with it.
    """

    def execute():
        return container_service.handle_execute_command(
            [sys.executable, "-c", _dies(pids)],
            stdin=base64.b64encode(b"a request").decode("ascii"),
            allowed={sys.executable: sys.executable},
        )

    answer, took = _in_thread(execute)

    assert answer["exit_code"] == -signal.SIGKILL
    assert base64.b64decode(answer["stdout"]) == b"half an answer"
    assert took < WITHIN
    assert _gone(_left(pids))


@posix
def test_the_container_service_still_waits_for_what_a_launcher_handed_its_window_to(tmp_path):
    """An application opened for editing may be a launcher that starts the real one and exits 0.

    The service has always read such a command's output to the end, which is
    the real application closing -- what `pc ide open` waits for. Only a
    command that failed or was killed is cut off.
    """
    launcher = (
        "import subprocess, sys\n"
        "print('launched', flush=True)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3); print(\"closed\", flush=True)'])\n"
    )

    def execute():
        return container_service.handle_execute_command(
            [sys.executable, "-c", launcher], allowed={sys.executable: sys.executable}
        )

    answer, took = _in_thread(execute)

    assert answer["exit_code"] == 0
    assert base64.b64decode(answer["stdout"]).split() == [b"launched", b"closed"]
    assert took >= 2.5


@posix
def test_only_what_can_still_write_into_the_pipe_is_a_holder():
    """The reading end is this process's own, and a copy of it is no reason to wait."""
    reader, writer = os.pipe()
    sleep = [sys.executable, "-c", "import time; time.sleep(30)"]
    writes = subprocess.Popen(sleep, stdout=writer)
    reads = subprocess.Popen(sleep, stdin=reader)
    try:
        assert container_service.pipe_holders([reader]) == [writes.pid]
    finally:
        for child in (writes, reads):
            child.kill()
            child.wait()
        os.close(reader)
        os.close(writer)


# --------------------------------------------------------------------------- #
# A container is a sandbox process too                                         #
# --------------------------------------------------------------------------- #


def test_a_death_by_signal_in_a_container_is_read_as_the_signal():
    """'docker exec' reports it the way a shell does: 128 plus the signal."""
    from partcad import runtime_python_docker

    # The container's numbering, which is Linux's whatever this host is.
    assert runtime_python_docker.exec_status(137) == -9
    assert runtime_python_docker.exec_status(139) == -11
    # Docker's own failures, and what a command really exited with, stay.
    for code in (0, 1, 2, 125, 126, 127, 255, 3221225477):
        assert runtime_python_docker.exec_status(code) == code


class _Container:
    """A container whose state is whatever the test says, as the SDK reports it on 'reload'."""

    def __init__(self, status="running", oom=False, exit_code=0, gone=False):
        self.status = status
        self.attrs = {"State": {"OOMKilled": oom, "ExitCode": exit_code}}
        self.gone = gone
        self.reloads = 0

    def reload(self):
        self.reloads += 1
        if self.gone:
            import docker

            raise docker.errors.NotFound("gone")


def _docker_runtime(tmp_path, monkeypatch, exits_with):
    from partcad import runtime_python_docker

    ctx = types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state")),
        root_path=str(tmp_path / "pkg"),
        sandbox_paths=[],
    )
    made = runtime_python_docker.DockerPythonRuntime(ctx, "3.11", image="ghcr.io/x/solver:abc")
    made.provisioned = True
    # What 'docker exec' would have exited with, from a process that is here.
    launched = [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(%d)" % exits_with]
    monkeypatch.setattr(made, "_spawn", lambda cmd, cwd=None, env=None: (launched, None, None))
    return made


@posix
def test_an_interpreter_killed_in_its_container_is_reported_as_killed(tmp_path, monkeypatch):
    made = _docker_runtime(tmp_path, monkeypatch, exits_with=137)
    container = made._container = _Container()

    exitcode, _, stderr = asyncio.run(made.run_async_onced(["-c", "pass"], ""))

    assert exitcode == -signal.SIGKILL
    assert "killed by signal 9 (SIGKILL)" in stderr and "out-of-memory killer" in stderr
    # The container itself is still running, so it is kept.
    assert made._container is container


@pytest.mark.parametrize(
    "container, said",
    [
        (_Container(status="exited", oom=True, exit_code=137), "stopped by the out-of-memory killer"),
        (_Container(status="exited", exit_code=137), "killed by SIGKILL (exit code 137)"),
        (_Container(gone=True), "has been removed"),
    ],
    ids=["oom", "killed", "removed"],
)
def test_a_sandbox_container_that_stopped_is_let_go_and_said_why(tmp_path, monkeypatch, container, said):
    """Every command sent to a stopped container fails without running; the next one has to start it again.

    '_start' acquires a container whenever it holds none, which finds a stopped
    one and starts it, or makes a new one where it is gone.
    """
    made = _docker_runtime(tmp_path, monkeypatch, exits_with=1)
    made._container = container

    exitcode, _, stderr = asyncio.run(made.run_async_onced(["-c", "pass"], ""))

    assert exitcode == 1
    assert said in stderr
    assert "started again for the next command" in stderr
    assert made._container is None


def test_a_command_that_failed_in_a_running_container_leaves_the_container_alone(tmp_path, monkeypatch):
    made = _docker_runtime(tmp_path, monkeypatch, exits_with=1)
    container = made._container = _Container()

    exitcode, _, stderr = asyncio.run(made.run_async_onced(["-c", "pass"], ""))

    assert exitcode == 1
    assert "started again" not in (stderr or "")
    assert made._container is container


class _Endpoint:
    """A container endpoint whose commands answer as the test says."""

    def __init__(self, name, container, answer):
        self.name = name
        self.container = container
        self.answer = answer
        self.spec = types.SimpleNamespace(name=name)
        self.ran = 0

    def run(self, *args, **kwargs):
        self.ran += 1
        return self.answer

    async def run_async(self, *args, **kwargs):
        self.ran += 1
        return self.answer


@pytest.mark.parametrize("asynchronous", [False, True], ids=["run", "run_async"])
def test_a_container_runtime_whose_container_stopped_starts_it_again_for_the_next_command(
    tmp_path, monkeypatch, asynchronous
):
    """KiCad's and a plugin's container: the endpoint is kept for good, so a dead one was asked forever."""
    dead = _Endpoint("partcad-kicad-x", _Container(status="exited", oom=True), (1, "", "returned no response"))
    alive = _Endpoint("partcad-kicad-x", _Container(), (0, "fine", ""))
    acquired = []

    def acquire(spec, client=None, ping=None):
        acquired.append(spec)
        return alive

    monkeypatch.setattr(pc_runtime.containers, "acquire", acquire)
    made = pc_runtime.Runtime(_ctx(tmp_path), "kicad")
    made.use_container(dead)

    def run():
        if asynchronous:
            return asyncio.run(made.run_async(["kicad-cli"], ""))
        return made.run(["kicad-cli"], "")

    exitcode, _, stderr = run()
    assert exitcode == 1
    assert "stopped by the out-of-memory killer" in stderr
    assert acquired == []

    exitcode, stdout, _ = run()
    assert exitcode == 0 and stdout == "fine"
    assert acquired == [dead.spec]
    assert made.endpoint is alive


# --------------------------------------------------------------------------- #
# The remote sandbox's pool                                                    #
# --------------------------------------------------------------------------- #


def _remote_pool():
    from partcad import remote_docker

    started = []

    def start(image):
        container = _Container()
        started.append(container)
        return remote_docker.Lease(image, container, "127.0.0.1:%d" % (5000 + len(started)))

    pool = remote_docker.ContainerPool(start)
    pool.started = started
    return pool


class _Environments:
    def __init__(self):
        self.forgotten = []

    def ensure(self, image, version, requirements=None):
        return "/pc-sandbox/v-env-%s/bin/python" % version

    def forget(self, image):
        self.forgotten.append(image)


class _Silent:
    """A JSON-RPC client to a container that does not answer -- what a dead one looks like."""

    def __init__(self, *args, **kwargs):
        pass

    def execute(self, command, params=None, timeout=None):
        return None


def test_a_remote_container_that_stopped_is_let_go_and_the_next_request_starts_another(monkeypatch):
    from partcad import remote_sandbox

    monkeypatch.setattr(remote_sandbox, "RuntimeJsonRpcClient", _Silent)
    pool, environments = _remote_pool(), _Environments()
    image = "ghcr.io/x/solver:abc"
    lease = pool.acquire(image)
    pool.release(lease)
    lease.container.status = "exited"
    lease.container.attrs["State"]["OOMKilled"] = True

    with pytest.raises(RuntimeError, match="stopped by the out-of-memory killer"):
        remote_sandbox.execute(pool, environments, {"image": image, "command": ["x.py"], "python_version": "3.11"})

    assert environments.forgotten == [image]
    assert pool.acquire(image) is not lease
    assert len(pool.started) == 2


def test_a_remote_container_that_merely_did_not_answer_is_kept(monkeypatch):
    from partcad import remote_sandbox

    monkeypatch.setattr(remote_sandbox, "RuntimeJsonRpcClient", _Silent)
    pool = _remote_pool()
    image = "ghcr.io/x/solver:abc"
    lease = pool.acquire(image)
    pool.release(lease)

    code, _, stderr = remote_sandbox.forward(pool, image, ["python", "-c", "pass"])

    assert code == 1 and "returned no response" in stderr
    assert pool.acquire(image) is lease


# --------------------------------------------------------------------------- #
# The daemon                                                                   #
# --------------------------------------------------------------------------- #


@posix
@pytest.mark.skipif(not hasattr(__import__("socket"), "AF_UNIX"), reason="the daemon's socket is AF_UNIX")
def test_the_daemon_answers_with_the_death_and_goes_on_answering(python_runtime, pids):
    """What the user sees: the error, not "the PartCAD service stopped responding".

    Served the way the daemon serves a request -- one at a time, under the lock
    every request is dispatched under -- so a run that never ended took every
    request after it with it. The client's silence bound is set far below its
    300 s default and still never reached.
    """
    import shutil
    import socket
    import tempfile

    from partcad_client.client import DaemonClient, DaemonError
    from partcad_service_json_rpc.core.session import Session
    from partcad_service_json_rpc.transport.socket_server import SocketServer

    def render(session, params):
        exitcode, _, stderr = asyncio.run(python_runtime.run_async_onced(["-c", _dies(pids)], "a request"))
        if exitcode != 0:
            raise RuntimeError(stderr)
        return "rendered"

    directory = tempfile.mkdtemp(prefix="pcw", dir="/tmp")
    path = os.path.join(directory, "socket")
    server = SocketServer(Session(), {"render": render, "status": lambda session, params: "serving"})
    threading.Thread(target=server.serve_unix, args=(path,), daemon=True).start()
    try:
        deadline = time.monotonic() + 5
        while True:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(path)
                break
            except OSError:
                sock.close()
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.01)
        sock.settimeout(WITHIN)
        stream = sock.makefile("rwb")
        client = DaemonClient(stream, stream, closer=sock.close, timeout=WITHIN, endpoint=path)

        started = time.monotonic()
        with pytest.raises(DaemonError) as failed:
            client.call("render")
        assert "killed by signal 9 (SIGKILL)" in str(failed.value)
        assert "out-of-memory killer" in str(failed.value)
        assert time.monotonic() - started < WITHIN

        assert client.call("status") == "serving"
        client.close()
    finally:
        server.stop()
        shutil.rmtree(directory, ignore_errors=True)
