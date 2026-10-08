#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How every container is named, started, reused and given files -- without a daemon.

What is worth pinning here is the deciding: which name a description gets, when
a container that answers to it is trusted and when it is replaced, what it is
created with, where its service is dialled, and what a request carries in each
transfer mode. None of that needs Docker to be running, so a fake client stands
in for it -- one that records what it was asked and answers the way the SDK
does, `NotFound` and 409 included. `test_containers_live.py` does the same
things against a real daemon.
"""

import base64
import io
import json
import os
import tarfile
import types

import docker
import pytest

from partcad_utils import container_service, containers
from partcad_utils.containers import MOUNT, UPLOAD, ContainerSpec

IMAGE = "ghcr.io/partcad/partcad-container-kicad:0.8.160"


def spec(**overrides):
    values = dict(role="kicad", image=IMAGE, allowed_commands={"kicad-cli": "/usr/bin/kicad-cli"})
    values.update(overrides)
    return ContainerSpec(**values)


# --------------------------------------------------------------------------- #
# Names                                                                        #
# --------------------------------------------------------------------------- #


def test_a_name_says_whose_which_version_and_exactly_which():
    name = containers.container_name(spec())
    prefix, role, tag, digest = name.split("-", 1)[0], *name.split("-", 1)[1].rsplit("-", 2)
    assert prefix == "partcad"
    assert role == "kicad"
    assert tag == "0.8.160"
    assert len(digest) == 12 and int(digest, 16) >= 0


def test_a_new_release_is_a_new_container():
    """The bug this module exists for: 0.8.158 importing boards in 0.8.129's container."""
    assert containers.container_name(spec()) != containers.container_name(
        spec(image="ghcr.io/partcad/partcad-container-kicad:0.8.161")
    )


def test_the_same_description_is_the_same_container():
    assert containers.container_name(spec()) == containers.container_name(spec())


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_commands": {"kicad-cli": "/opt/kicad-cli"}},
        {"environment": {"A": "1"}},
        {"sandbox_root": "/pc-sandbox"},
        {"user": "501:20"},
        {"volumes": {"v": {"bind": "/v", "mode": "rw"}}},
        {"service_python": "/usr/bin/python3.11"},
        {"mode": UPLOAD},
    ],
)
def test_anything_fixed_at_creation_changes_the_identity(change):
    assert containers.identity(spec()) != containers.identity(spec(**change))


def test_mounts_are_identity_in_mount_mode_and_nothing_in_upload_mode():
    mounted = {"/home/u": {"bind": "/home/u", "mode": "rw"}}
    assert containers.identity(spec(mode=MOUNT)) != containers.identity(spec(mode=MOUNT, mounts=mounted))
    # Nothing from here is visible in upload mode, so mounts cannot distinguish
    # one such container from another -- and are not passed to Docker at all.
    assert containers.identity(spec(mode=UPLOAD)) == containers.identity(spec(mode=UPLOAD, mounts=mounted))


def test_the_role_is_not_identity():
    """Two roles needing exactly one container may share it."""
    assert containers.identity(spec(role="a")) == containers.identity(spec(role="b"))


def test_a_different_service_is_a_different_container(monkeypatch):
    """The container runs the service it was given; a PartCAD shipping another needs another."""
    before = containers.identity(spec())
    monkeypatch.setattr(containers, "_service_source", lambda: b"# a newer service\n")
    assert containers.identity(spec()) != before


@pytest.mark.parametrize(
    "image,tag",
    [
        ("ghcr.io/partcad/x:0.8.160", "0.8.160"),
        ("linuxserver/freecad:latest", "latest"),
        ("linuxserver/freecad", "latest"),
        ("localhost:5000/x", "latest"),
        ("localhost:5000/x:1.2", "1.2"),
        ("ghcr.io/x/y@sha256:abc", "digest"),
    ],
)
def test_the_tag_in_a_name(image, tag):
    assert containers._tag_of(image) == tag


def test_a_name_holds_only_what_docker_allows():
    name = containers.container_name(spec(role="open freecad/Weird", image="x/y:Tag+With:Odd"))
    assert all(c.isalnum() or c in "_.-" for c in name)
    assert name.startswith("partcad-open-freecad-Weird-")


# --------------------------------------------------------------------------- #
# Transfer mode                                                                #
# --------------------------------------------------------------------------- #


def test_mount_is_the_default_and_use_docker_remote_asks_for_upload():
    assert containers.transfer_mode(types.SimpleNamespace(use_docker_remote=False)) == MOUNT
    assert containers.transfer_mode(types.SimpleNamespace(use_docker_remote=True)) == UPLOAD
    assert containers.transfer_mode(types.SimpleNamespace()) == MOUNT


def test_use_docker_remote_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv("PC_USE_DOCKER_REMOTE", raising=False)
    from partcad_utils.user_config import UserConfig

    assert UserConfig().use_docker_remote is False


def test_use_docker_remote_can_be_turned_on_from_the_environment(monkeypatch):
    monkeypatch.setenv("PC_USE_DOCKER_REMOTE", "true")
    from partcad_utils.user_config import UserConfig

    assert UserConfig().use_docker_remote is True


# --------------------------------------------------------------------------- #
# Where the daemon is                                                          #
# --------------------------------------------------------------------------- #


def _client_at(base_url, ssh_host=None):
    api = types.SimpleNamespace(base_url=base_url)
    if ssh_host is not None:
        api._custom_adapter = types.SimpleNamespace(ssh_host=ssh_host)
    return types.SimpleNamespace(api=api)


@pytest.mark.parametrize(
    "base_url,ssh_host,expected",
    [
        ("http+docker://localhost", None, None),
        ("http+docker://localnpipe", None, None),
        ("http://127.0.0.1:2375", None, None),
        ("http://localhost:2375", None, None),
        ("http://10.0.0.7:2375", None, "10.0.0.7"),
        ("https://builder.example.com:2376", None, "builder.example.com"),
        ("http://[2001:db8::1]:2375", None, "2001:db8::1"),
        ("http+docker://ssh", "ssh://ci@builder.example.com:22", "builder.example.com"),
        ("http+docker://ssh", "ci@builder.example.com", "builder.example.com"),
    ],
)
def test_where_the_daemon_runs(base_url, ssh_host, expected):
    assert containers.daemon_host(_client_at(base_url, ssh_host)) == expected


def _networked(ports=None, networks=None):
    return types.SimpleNamespace(attrs={"NetworkSettings": {"Ports": ports or {}, "Networks": networks or {}}})


def test_a_local_container_is_dialled_on_its_published_port_then_its_own_address():
    container = _networked(
        ports={"5000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49200"}]},
        networks={"bridge": {"IPAddress": "172.17.0.5"}},
    )
    assert containers._candidates(container, None) == [("127.0.0.1", 49200), ("172.17.0.5", 5000)]


def test_a_wildcard_bind_is_dialled_on_loopback():
    """'0.0.0.0' is where a port listens, not somewhere to connect to."""
    container = _networked(ports={"5000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49200"}]})
    assert containers._candidates(container, None) == [("127.0.0.1", 49200)]


def test_a_remote_container_is_dialled_at_the_daemons_host_and_nowhere_else():
    """Its network address is on another machine's bridge, which routes nowhere from here."""
    container = _networked(
        ports={"5000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49200"}]},
        networks={"bridge": {"IPAddress": "172.17.0.5"}},
    )
    assert containers._candidates(container, "builder.example.com") == [("builder.example.com", 49200)]


# --------------------------------------------------------------------------- #
# A daemon, faked                                                              #
# --------------------------------------------------------------------------- #


def _api_error(status):
    return docker.errors.APIError("status %d" % status, response=types.SimpleNamespace(status_code=status, reason="x"))


class FakeContainer:
    def __init__(self, daemon, name, kwargs, status="created", image_id="sha256:current"):
        self.daemon = daemon
        self.name = name
        self.kwargs = kwargs
        self.status = status
        self.archives = []
        self.started = 0
        self.removed = False
        env = ["%s=%s" % (k, v) for k, v in (kwargs.get("environment") or {}).items()]
        self.attrs = {
            "Image": image_id,
            "Config": {"Labels": dict(kwargs.get("labels") or {}), "Env": env},
            "NetworkSettings": {
                "Ports": {"5000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49200"}]},
                "Networks": {"bridge": {"IPAddress": "172.17.0.9"}},
            },
        }

    @property
    def labels(self):
        return self.attrs["Config"]["Labels"]

    def reload(self):
        if self.daemon.exit_on_start and self.started:
            self.status = "exited"

    def start(self):
        self.started += 1
        self.status = "running"
        self.daemon.order.append(("start", self.name))

    def put_archive(self, path, data):
        self.archives.append((path, data))
        self.daemon.order.append(("put_archive", self.name))
        return True

    def remove(self, force=False):
        self.removed = True
        self.daemon.store.pop(self.name, None)

    def logs(self, tail=None):
        return b"python3: not found"

    def exec_run(self, cmd, user=None):
        self.daemon.execs.append((self.name, list(cmd), user))
        return 0, b""


class FakeDaemon:
    """Containers and images, as the SDK presents them, and a record of what was asked."""

    def __init__(self, base_url="http+docker://localhost", image_env=None):
        self.api = types.SimpleNamespace(base_url=base_url)
        self.store = {}
        self.created = []
        self.order = []
        self.exit_on_start = False
        self.conflict_once = False
        # How many look-ups, after a conflict, still find nothing: the daemon
        # reserves a name before the container behind it can be inspected.
        self.invisible_lookups = 0
        self.pulled = []
        self.execs = []
        self.image = types.SimpleNamespace(
            id="sha256:current",
            attrs={"Config": {"Env": image_env or []}},
        )
        self.containers = types.SimpleNamespace(get=self._get, create=self._create)
        self.images = types.SimpleNamespace(get=self._image_get, pull=self._image_pull)
        self.local_images = {IMAGE}

    def _image_get(self, name):
        if name in self.local_images:
            return self.image
        raise docker.errors.ImageNotFound(name)

    def _image_pull(self, name):
        self.pulled.append(name)
        return self.image

    def _get(self, name):
        if self.invisible_lookups > 0:
            self.invisible_lookups -= 1
            raise docker.errors.NotFound(name)
        if name in self.store:
            return self.store[name]
        raise docker.errors.NotFound(name)

    def _create(self, image, **kwargs):
        name = kwargs["name"]
        if self.conflict_once:
            # Another process won the race: its container now exists.
            self.conflict_once = False
            self.store[name] = FakeContainer(self, name, kwargs, status="running")
            raise _api_error(409)
        container = FakeContainer(self, name, kwargs)
        self.store[name] = container
        self.created.append((image, kwargs))
        self.order.append(("create", name))
        return container


def ready(host, port):
    return 2


@pytest.fixture
def daemon():
    return FakeDaemon()


def test_a_container_is_created_with_the_service_as_its_command(daemon):
    endpoint = containers.acquire(spec(), client=daemon, ping=ready)
    image, kwargs = daemon.created[0]
    assert image == IMAGE
    assert kwargs["name"] == containers.container_name(spec())
    assert kwargs["command"] == ["python3", containers.SERVICE_PATH]
    assert kwargs["entrypoint"] == []
    assert endpoint.name == kwargs["name"]


def test_the_service_is_in_the_container_before_it_starts(daemon):
    containers.acquire(spec(), client=daemon, ping=ready)
    name = containers.container_name(spec())
    assert daemon.order == [("create", name), ("put_archive", name), ("start", name)]


def test_what_is_put_into_the_container_is_this_service(daemon):
    containers.acquire(spec(), client=daemon, ping=ready)
    path, data = daemon.store[containers.container_name(spec())].archives[0]
    assert path == "/"
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        member = tar.extractfile(containers.SERVICE_PATH.lstrip("/"))
        with open(container_service.__file__, "rb") as f:
            assert member.read() == f.read()


def test_every_container_is_labelled_for_prune_and_for_its_identity(daemon):
    containers.acquire(spec(), client=daemon, ping=ready)
    labels = daemon.created[0][1]["labels"]
    assert labels[containers.LABEL_CONTAINER] == "1"
    assert labels[containers.LABEL_ROLE] == "kicad"
    assert labels[containers.LABEL_IDENTITY] == containers.identity(spec())
    assert labels[containers.LABEL_MODE] == MOUNT
    from partcad_utils import __version__

    assert labels[containers.LABEL_VERSION] == __version__


def test_the_allowlist_is_the_images_own_plus_what_the_spec_adds():
    daemon = FakeDaemon(image_env=['PC_CONTAINER_ALLOWED_COMMANDS={"python": "/usr/local/bin/python3"}'])
    containers.acquire(spec(), client=daemon, ping=ready)
    allowed = json.loads(daemon.created[0][1]["environment"]["PC_CONTAINER_ALLOWED_COMMANDS"])
    assert allowed == {"python": "/usr/local/bin/python3", "kicad-cli": "/usr/bin/kicad-cli"}


def test_a_name_allowed_anywhere_on_path_does_not_unpin_the_images_own_path():
    daemon = FakeDaemon(image_env=['PC_CONTAINER_ALLOWED_COMMANDS={"python": "/usr/local/bin/python3"}'])
    containers.acquire(spec(allowed_commands={"python": None, "solver": None}), client=daemon, ping=ready)
    allowed = json.loads(daemon.created[0][1]["environment"]["PC_CONTAINER_ALLOWED_COMMANDS"])
    assert allowed == {"python": "/usr/local/bin/python3", "solver": None}


def test_an_explicit_path_in_the_spec_wins_over_the_images():
    daemon = FakeDaemon(image_env=['PC_CONTAINER_ALLOWED_COMMANDS={"python": "/usr/local/bin/python3"}'])
    containers.acquire(spec(allowed_commands={"python": "/opt/py/bin/python"}), client=daemon, ping=ready)
    allowed = json.loads(daemon.created[0][1]["environment"]["PC_CONTAINER_ALLOWED_COMMANDS"])
    assert allowed["python"] == "/opt/py/bin/python"


def test_every_container_gets_a_token_of_its_own(daemon):
    first = containers.acquire(spec(), client=daemon, ping=ready)
    other = containers.acquire(spec(role="x", environment={"Z": "1"}), client=daemon, ping=ready)
    assert first.token and other.token and first.token != other.token
    assert first.client().token == first.token


def test_a_local_daemon_publishes_on_loopback_only(daemon):
    containers.acquire(spec(), client=daemon, ping=ready)
    assert daemon.created[0][1]["ports"] == {"5000/tcp": ("127.0.0.1", None)}


def test_a_remote_daemon_publishes_on_every_interface():
    daemon = FakeDaemon(base_url="https://builder.example.com:2376")
    containers.acquire(spec(), client=daemon, ping=ready)
    assert daemon.created[0][1]["ports"] == {"5000/tcp": ("0.0.0.0", None)}


def test_mounts_are_passed_in_mount_mode_and_not_in_upload_mode(daemon):
    mounted = {"/home/u": {"bind": "/home/u", "mode": "rw"}}
    volume = {"partcad-sandbox": {"bind": "/pc-sandbox", "mode": "rw"}}
    containers.acquire(spec(mounts=mounted, volumes=volume), client=daemon, ping=ready)
    containers.acquire(spec(mode=UPLOAD, mounts=mounted, volumes=volume), client=daemon, ping=ready)
    assert daemon.created[0][1]["volumes"] == {**mounted, **volume}
    # A named volume is the daemon's own storage, and stays.
    assert daemon.created[1][1]["volumes"] == volume


def test_a_new_containers_volumes_are_made_writable_for_the_service(daemon):
    """A fresh volume is root's and 0755; the service runs as anyone but root."""
    volume = {"partcad-sandbox": {"bind": "/pc-sandbox", "mode": "rw"}}
    containers.acquire(spec(mode=UPLOAD, volumes=volume), client=daemon, ping=ready)
    assert daemon.execs == [
        (containers.container_name(spec(mode=UPLOAD, volumes=volume)), ["chmod", "1777", "/pc-sandbox"], "0")
    ]


def test_a_reused_containers_volumes_are_opened_too(daemon):
    """A container made before this fix kept its root-owned volume and kept failing."""
    volume = {"partcad-sandbox": {"bind": "/pc-sandbox", "mode": "rw"}}
    containers.acquire(spec(mode=UPLOAD, volumes=volume), client=daemon, ping=ready)
    containers.acquire(spec(mode=UPLOAD, volumes=volume), client=daemon, ping=ready)
    assert len(daemon.execs) == 2
    assert len(daemon.created) == 1


def test_a_container_that_fits_is_reused(daemon):
    containers.acquire(spec(), client=daemon, ping=ready)
    containers.acquire(spec(), client=daemon, ping=ready)
    assert len(daemon.created) == 1


def test_a_stopped_container_that_fits_is_started_again(daemon):
    containers.acquire(spec(), client=daemon, ping=ready)
    container = daemon.store[containers.container_name(spec())]
    container.status = "exited"
    containers.acquire(spec(), client=daemon, ping=ready)
    assert container.started == 2
    assert len(daemon.created) == 1


def test_a_container_with_the_name_and_another_identity_is_replaced(daemon):
    """A hand-made container, or one an older PartCAD derived differently, is not trusted."""
    name = containers.container_name(spec())
    impostor = FakeContainer(daemon, name, {"labels": {containers.LABEL_IDENTITY: "something-else"}}, status="running")
    daemon.store[name] = impostor
    containers.acquire(spec(), client=daemon, ping=ready)
    assert impostor.removed
    assert len(daemon.created) == 1


def test_a_container_running_an_image_its_tag_no_longer_names_is_replaced(daemon):
    """`:latest` re-pulled: same name, same identity, a different image underneath."""
    containers.acquire(spec(), client=daemon, ping=ready)
    old = daemon.store[containers.container_name(spec())]
    daemon.image.id = "sha256:newer"
    containers.acquire(spec(), client=daemon, ping=ready)
    assert old.removed
    assert len(daemon.created) == 2


def test_losing_a_creation_race_finds_the_winners_container(daemon):
    daemon.conflict_once = True
    endpoint = containers.acquire(spec(), client=daemon, ping=ready)
    assert daemon.created == []  # the winner's, not ours
    assert endpoint.container is daemon.store[containers.container_name(spec())]


def test_a_name_reserved_but_not_yet_inspectable_is_waited_for(daemon):
    """What four real processes racing found: three immediate retries all land in that gap."""
    daemon.conflict_once = True
    daemon.invisible_lookups = 1 + containers.START_ATTEMPTS * 2
    endpoint = containers.acquire(spec(), client=daemon, ping=ready)
    assert daemon.created == []
    assert endpoint.container is daemon.store[containers.container_name(spec())]


def test_somebody_elses_container_caught_between_create_and_start_is_finished(daemon):
    name = containers.container_name(spec())
    theirs = FakeContainer(
        daemon, name, {"labels": {containers.LABEL_IDENTITY: containers.identity(spec())}}, status="created"
    )
    daemon.store[name] = theirs
    containers.acquire(spec(), client=daemon, ping=ready)
    assert theirs.archives, "the service has to be put there before the start"
    assert theirs.started == 1


def test_the_first_address_that_answers_is_the_one_used(daemon):
    answering = {("172.17.0.9", 5000)}
    endpoint = containers.acquire(spec(), client=daemon, ping=lambda h, p: 2 if (h, p) in answering else None)
    assert (endpoint.host, endpoint.port) == ("172.17.0.9", 5000)


def test_a_container_that_dies_before_answering_is_removed_and_reported(daemon):
    daemon.exit_on_start = True
    with pytest.raises(containers.ContainerUnavailable) as failed:
        containers.acquire(spec(), client=daemon, ping=lambda h, p: None)
    message = str(failed.value)
    assert "python3: not found" in message  # its logs
    assert "PATH" in message  # and what that means
    assert containers.container_name(spec()) not in daemon.store


def test_an_image_nobody_can_get_names_every_name_it_tried(daemon):
    """Naming every candidate is the only clue to which tag needs publishing."""
    daemon.local_images = set()

    def refuse(name):
        raise docker.errors.NotFound("no such image: %s" % name)

    daemon.images.pull = refuse
    with pytest.raises(containers.ContainerUnavailable) as failed:
        containers.acquire(spec(), client=daemon, ping=ready)
    from partcad_utils import docker_image

    for candidate in docker_image.candidates(IMAGE):
        assert candidate in str(failed.value)


def test_a_container_whose_log_cannot_be_read_still_reports_why_it_failed(daemon):
    """A best-effort extra must not replace the error it was decorating."""
    daemon.exit_on_start = True
    original = FakeContainer.logs

    def mute(self, tail=None):
        raise RuntimeError("no log driver")

    FakeContainer.logs = mute
    try:
        with pytest.raises(containers.ContainerUnavailable, match="stopped before its service answered"):
            containers.acquire(spec(), client=daemon, ping=lambda h, p: None)
    finally:
        FakeContainer.logs = original


def test_an_image_this_machine_lacks_is_pulled_arch_suffix_first(daemon):
    daemon.local_images = set()
    containers.acquire(spec(), client=daemon, ping=ready)
    from partcad_utils import docker_image

    assert daemon.pulled == [docker_image.candidates(IMAGE)[0]]


# --------------------------------------------------------------------------- #
# What a request carries                                                       #
# --------------------------------------------------------------------------- #


def _endpoint(mode):
    return containers.Endpoint(
        name="partcad-test", spec=spec(mode=mode), container=None, host="127.0.0.1", port=1, token="t"
    )


def test_mount_mode_sends_names_and_nothing_else(tmp_path):
    source = tmp_path / "in.txt"
    source.write_text("x")
    params = _endpoint(MOUNT).params(
        stdin="request", cwd=str(tmp_path), input_files=[str(source)], output_files=["/o"], input_dirs=[str(tmp_path)]
    )
    assert set(params) == {"stdin", "cwd"}
    assert base64.b64decode(params["stdin"]) == b"request"


def test_upload_mode_sends_every_file_and_names_every_output(tmp_path):
    source = tmp_path / "in.txt"
    source.write_text("payload")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "a.py").write_text("A")
    params = _endpoint(UPLOAD).params(
        input_files=[str(source)], output_files=["/o.stl"], input_dirs=[str(package)], output_dirs=["/d"]
    )
    assert base64.b64decode(params["input_files"][str(source)]) == b"payload"
    assert params["input_dirs"][str(package)] == container_service.pack_directory(str(package))
    assert params["output_files"] == ["/o.stl"]
    assert params["output_dirs"] == ["/d"]


def _answer(**result):
    base = {"exit_code": 0, "stdout": "", "stderr": "", "output_files": {}, "output_dirs": {}}
    base.update(result)
    return {"jsonrpc": "2.0", "id": 1, "result": base}


def test_an_output_file_comes_back_to_where_it_was_asked_for(tmp_path):
    target = tmp_path / "out.stl"
    answer = _answer(output_files={str(target): base64.b64encode(b"mesh").decode()})
    code, _, _ = _endpoint(UPLOAD).result(answer, output_files=[str(target)])
    assert code == 0
    assert target.read_bytes() == b"mesh"


def test_a_file_nobody_asked_for_is_not_written(tmp_path):
    stray = tmp_path / "stray"
    answer = _answer(output_files={str(stray): base64.b64encode(b"x").decode()})
    _endpoint(UPLOAD).result(answer, output_files=[])
    assert not stray.exists()


def test_a_directory_comes_back_over_the_one_here_without_deleting_anything(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "board.kicad_pcb").write_text("v1")
    (project / "keep.txt").write_text("mine")
    edited = tmp_path / "edited"
    edited.mkdir()
    (edited / "board.kicad_pcb").write_text("v2")
    answer = _answer(output_dirs={str(project): container_service.pack_directory(str(edited))})
    _endpoint(UPLOAD).result(answer, output_dirs=[str(project)])
    assert (project / "board.kicad_pcb").read_text() == "v2"
    assert (project / "keep.txt").read_text() == "mine"


def test_mount_mode_writes_nothing_back_because_nothing_was_away(tmp_path):
    target = tmp_path / "out.stl"
    answer = _answer(output_files={str(target): base64.b64encode(b"mesh").decode()})
    _endpoint(MOUNT).result(answer, output_files=[str(target)])
    assert not target.exists()


def test_a_refusal_is_an_exit_code_and_a_sentence_not_a_key_error():
    """`KeyError: 'result'` is what a refusal used to surface as, three frames from its cause."""
    code, _, stderr = _endpoint(MOUNT).result({"error": {"code": -32602, "message": "Command 'x' is not allowed"}})
    assert code == 1
    assert "not allowed" in stderr


def test_no_answer_at_all_is_a_failure_that_says_so():
    code, _, stderr = _endpoint(MOUNT).result(None)
    assert code == 1
    assert "no response" in stderr


def test_output_is_decoded_and_the_exit_code_kept():
    answer = _answer(
        exit_code=3,
        stdout=base64.b64encode(b"out").decode(),
        stderr=base64.b64encode(b"err").decode(),
    )
    assert _endpoint(MOUNT).result(answer) == (3, "out", "err")


def test_the_endpoint_talks_to_its_service_with_its_token():
    client = _endpoint(MOUNT).client()
    assert (client.host, client.port, client.token) == ("127.0.0.1", 1, "t")
    assert os.path.isfile(container_service.__file__)


def test_a_frozen_modules_pyc_name_still_finds_the_source(monkeypatch, tmp_path):
    """In a bundle `__file__` names a `.pyc` that is not on disk; the `.py` is shipped as data beside it."""
    source = tmp_path / "container_service.py"
    source.write_bytes(b"# the service\n")
    monkeypatch.setattr(container_service, "__file__", str(tmp_path / "container_service.pyc"))
    assert containers._service_path() == str(source)


def test_an_installation_without_the_service_says_so():
    containers._service_source.cache_clear()
    original = containers._service_path
    try:
        containers._service_path = lambda: "/nowhere/container_service.py"
        with pytest.raises(containers.ContainerUnavailable, match="not where this installation"):
            containers._service_source()
    finally:
        containers._service_path = original
        containers._service_source.cache_clear()


def test_a_daemon_elsewhere_is_warned_about_once(monkeypatch):
    """Its containers are reached in plain HTTP; whoever turned that on is told, once per daemon."""
    said = []
    monkeypatch.setattr(containers, "_CLEARTEXT_WARNED", set())
    monkeypatch.setattr(containers.pc_logging, "warning", said.append)

    for _ in range(3):
        containers._warn_cleartext("build-box")
    containers._warn_cleartext("other-box")

    assert len(said) == 2
    assert "plain HTTP" in said[0] and "build-box" in said[0]
    # The advice that would be wrong is not given as a way out.
    assert "carries Docker's own API and not these" in said[0]


def test_env_is_sent_in_either_mode(tmp_path):
    for mode in (MOUNT, UPLOAD):
        assert _endpoint(mode).params(env={"DISPLAY": ":1"})["env"] == {"DISPLAY": ":1"}
    assert "env" not in _endpoint(MOUNT).params()


def test_display_plumbing_is_bound_on_a_local_daemon_in_either_mode(daemon):
    """The X socket is not how files arrive, so upload mode keeps it -- on this machine."""
    x11 = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}
    containers.acquire(spec(mode=UPLOAD, local_binds=x11), client=daemon, ping=ready)
    assert daemon.created[0][1]["volumes"] == x11


def test_display_plumbing_is_not_bound_on_another_machines_daemon():
    """There it would bind that machine's sockets, which are nobody's display."""
    remote = FakeDaemon(base_url="https://builder.example.com:2376")
    x11 = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}
    containers.acquire(spec(mode=UPLOAD, local_binds=x11), client=remote, ping=ready)
    assert not remote.created[0][1]["volumes"]


def test_extra_hosts_reach_the_container(daemon):
    containers.acquire(spec(extra_hosts={"host.docker.internal": "host-gateway"}), client=daemon, ping=ready)
    assert daemon.created[0][1]["extra_hosts"] == {"host.docker.internal": "host-gateway"}


def test_display_plumbing_and_hosts_are_identity():
    assert containers.identity(spec()) != containers.identity(spec(extra_hosts={"h": "a"}))
    assert containers.identity(spec()) != containers.identity(spec(local_binds={"/x": {"bind": "/x", "mode": "rw"}}))
