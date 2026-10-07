#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every container PartCAD starts, started for real.

`test_containers.py` pins the deciding against a fake daemon; this pins that the
decisions hold against a real one -- that a created container really accepts
the service before it starts, that a file really comes back in upload mode and
really appears in mount mode, that two processes racing for one container end
up in one container.

Skipped where no daemon answers, which is what a machine without Docker is.
Everything a test starts carries a role unique to this session and is removed
at the end, whatever the outcome.
"""

import base64
import os
import pickle
import subprocess
import sys
import threading
import uuid

import pytest
import requests

docker = pytest.importorskip("docker")

from partcad_utils import containers  # noqa: E402
from partcad_utils.containers import MOUNT, UPLOAD, ContainerSpec  # noqa: E402

# Small, public, and with a python3 on PATH -- which is all the service needs.
# PC_TEST_CONTAINER_IMAGE points this at another, e.g. PartCAD's own sandbox
# image, to check that one meets the same contract.
IMAGE = os.environ.get("PC_TEST_CONTAINER_IMAGE", "python:3.12-slim")
SESSION = uuid.uuid4().hex[:8]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux containers on a Windows runner")


@pytest.fixture(scope="module")
def client():
    try:
        client = docker.from_env()
        client.ping()
        if str(client.info().get("OSType", "")).lower() not in ("", "linux"):
            pytest.skip("this daemon does not run Linux containers")
    except Exception as e:
        pytest.skip("no Docker daemon answers here: %s" % e)
    try:
        containers.resolve_image(client, IMAGE)
    except Exception as e:
        pytest.skip("cannot get %s: %s" % (IMAGE, e))
    yield client
    for container in client.containers.list(all=True, filters={"label": containers.LABEL_CONTAINER}):
        if container.labels.get(containers.LABEL_ROLE, "").startswith("live-" + SESSION):
            container.remove(force=True)


def live(role, **values):
    values.setdefault("image", IMAGE)
    values.setdefault("allowed_commands", {"python": None})
    if values.get("mode", MOUNT) == MOUNT and hasattr(os, "getuid"):
        values.setdefault("user", "%d:%d" % (os.getuid(), os.getgid()))
    return ContainerSpec(role="live-%s-%s" % (SESSION, role), **values)


def test_a_command_runs_in_a_fresh_container(client):
    endpoint = containers.acquire(live("hello"), client=client)
    code, stdout, stderr = endpoint.run(["python", "-c", "import platform; print(platform.system())"])
    assert (code, stdout.strip()) == (0, "Linux"), stderr


def _binds(client, *paths):
    """The binds for ``paths``, the way every caller makes them.

    Not ``{path: {"bind": path}}``: in a dev container holding the host's Docker
    socket, the daemon resolves a source against the *host's* filesystem, where
    this container's temporary directory is not -- it would bind an empty
    directory of the same name, owned by root. `container_mounts.bind_mounts` is
    what maps a path to where the daemon really keeps it.
    """
    from partcad import container_mounts, runtime

    try:
        return container_mounts.bind_mounts(client, IMAGE, [str(p) for p in paths], "This test")
    except runtime.SandboxUnavailable as e:
        pytest.skip(str(e))


def test_mount_mode_shares_this_machines_files(client, tmp_path):
    endpoint = containers.acquire(live("mount", mounts=_binds(client, tmp_path)), client=client)
    (tmp_path / "in.txt").write_text("from here")
    target = tmp_path / "out.txt"
    code, _, stderr = endpoint.run(
        [
            "python",
            "-c",
            "import sys; open(sys.argv[2], 'w').write(open(sys.argv[1]).read().upper())",
            str(tmp_path / "in.txt"),
            str(target),
        ]
    )
    assert code == 0, stderr
    assert target.read_text() == "FROM HERE"
    # Written as this user, so it stays this user's to edit and delete.
    assert target.stat().st_uid == os.getuid()


def test_upload_mode_mounts_nothing_from_here(client, tmp_path):
    endpoint = containers.acquire(
        live("upload-nomount", mode=UPLOAD, mounts={str(tmp_path): {"bind": str(tmp_path), "mode": "rw"}}),
        client=client,
    )
    endpoint.container.reload()
    assert [m for m in endpoint.container.attrs.get("Mounts") or [] if m.get("Type") == "bind"] == []


def test_upload_mode_sends_a_file_and_brings_one_back(client, tmp_path):
    endpoint = containers.acquire(live("upload", mode=UPLOAD), client=client)
    source = tmp_path / "model.step"
    source.write_text("solid")
    target = tmp_path / "model.stl"
    code, _, stderr = endpoint.run(
        [
            "python",
            "-c",
            "import sys; open(sys.argv[2], 'w').write(open(sys.argv[1]).read() + ' as mesh')",
            str(source),
            str(target),
        ],
        input_files=[str(source)],
        output_files=[str(target)],
    )
    assert code == 0, stderr
    assert target.read_text() == "solid as mesh"


def test_upload_mode_brings_an_in_place_edit_back(client, tmp_path):
    endpoint = containers.acquire(live("upload-edit", mode=UPLOAD), client=client)
    document = tmp_path / "part.FCStd"
    document.write_text("v1")
    code, _, stderr = endpoint.run(
        ["python", "-c", "import sys; open(sys.argv[1], 'w').write('v2')", str(document)],
        input_files=[str(document)],
        output_files=[str(document)],
    )
    assert code == 0, stderr
    assert document.read_text() == "v2"


def test_upload_mode_brings_a_directory_back(client, tmp_path):
    endpoint = containers.acquire(live("upload-dir", mode=UPLOAD), client=client)
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").write_text("{}")
    (project / "board.kicad_pcb").write_text("v1")
    code, _, stderr = endpoint.run(
        [
            "python",
            "-c",
            "import os, sys; open(os.path.join(os.path.dirname(sys.argv[1]), 'board.kicad_pcb'), 'w').write('v2')",
            str(project / "board.kicad_pro"),
        ],
        input_dirs=[str(project)],
        output_dirs=[str(project)],
    )
    assert code == 0, stderr
    assert (project / "board.kicad_pcb").read_text() == "v2"


def test_a_fresh_volume_is_writable_by_the_service(client):
    """What every new machine running the remote sandbox hit: a volume root owned and 0755."""
    volume = "partcad-live-%s-volume" % SESSION
    try:
        endpoint = containers.acquire(
            live("volume", mode=UPLOAD, user="1000:1000", volumes={volume: {"bind": "/pc-sandbox", "mode": "rw"}}),
            client=client,
        )
        code, _, stderr = endpoint.run(["python", "-c", "open('/pc-sandbox/probe', 'w').write('ok')"])
        assert code == 0, stderr
    finally:
        for container in client.containers.list(
            all=True, filters={"label": containers.LABEL_ROLE + "=live-%s-volume" % SESSION}
        ):
            container.remove(force=True)
        try:
            client.volumes.get(volume).remove(force=True)
        except Exception:
            pass


def test_a_running_container_is_reused(client):
    first = containers.acquire(live("reuse"), client=client)
    second = containers.acquire(live("reuse"), client=client)
    assert first.container.id == second.container.id


def test_a_stopped_container_is_started_again(client):
    first = containers.acquire(live("restart"), client=client)
    first.container.stop(timeout=1)
    second = containers.acquire(live("restart"), client=client)
    assert second.container.id == first.container.id
    assert second.run(["python", "-c", "print('back')"])[1].strip() == "back"


def test_an_impostor_under_the_name_is_replaced(client):
    """A container somebody made by hand under PartCAD's name is not run commands in."""
    spec = live("impostor")
    name = containers.container_name(spec)
    impostor = client.containers.run(IMAGE, ["sleep", "infinity"], name=name, detach=True)
    endpoint = containers.acquire(spec, client=client)
    assert endpoint.container.id != impostor.id
    assert endpoint.run(["python", "-c", "print('ok')"])[0] == 0


def test_prune_can_find_every_container_started_here(client):
    from partcad import docker_prune

    endpoint = containers.acquire(live("prune"), client=client)
    assert endpoint.container.id in {c.id for c in docker_prune.managed_containers(client)}


def test_the_service_refuses_a_request_without_the_containers_token(client):
    endpoint = containers.acquire(live("token"), client=client)
    url = "http://%s:%d/jsonrpc" % (endpoint.host, endpoint.port)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {"command": ["python", "-c", "1"]}}
    assert requests.post(url, json=payload, timeout=10).status_code == 401
    assert endpoint.run(["python", "-c", "1"])[0] == 0


def test_threads_asking_at_once_share_one_container(client):
    spec = live("threads")
    found = []
    workers = [
        threading.Thread(target=lambda: found.append(containers.acquire(spec, client=client).container.id))
        for _ in range(6)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(found) == 6 and len(set(found)) == 1


ACQUIRE_ELSEWHERE = """
import base64, pickle, sys
from partcad_utils import containers
spec = pickle.loads(base64.b64decode(sys.argv[1]))
print(containers.acquire(spec).container.id)
"""


def test_processes_asking_at_once_share_one_container(client):
    """Many users on one daemon is the case `useDockerRemote` exists for; the name is the lock.

    Separate interpreters, started together, each handed the same spec: nothing
    in-process -- no lock, no cache -- can make them agree, only the daemon.
    """
    encoded = base64.b64encode(pickle.dumps(live("processes"))).decode()
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", ACQUIRE_ELSEWHERE, encoded], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        for _ in range(4)
    ]
    found = []
    for worker in workers:
        out, err = worker.communicate(timeout=180)
        assert worker.returncode == 0, err.decode()
        found.append(out.decode().strip().splitlines()[-1])
    assert len(set(found)) == 1
