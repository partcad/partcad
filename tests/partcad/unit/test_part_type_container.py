#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A partType whose script runs in the container it declares (``container:``).

What is real here: the part factory, the request it builds and the paths it
carries, `partcad.wrapper_container`, the `Runtime` and `Endpoint` a container
is driven through, the container's service (`partcad_utils.container_service`,
loaded from its file as a container runs it), and the wrapper and the script it
runs. What is not is Docker: the service runs in this process, reached over the
same frames the client writes (see `test_container_execute.py`, which this
borrows its wiring from), with ``python`` allowed as this interpreter -- which
has OCP, as an image a part type runs in must.

Both ways files reach a container are run, because both have to work for every
caller: ``mount``, where the command names files where they are, and
``upload``, where every directory it names is sent and every argument naming one
is rewritten -- so a script that saw a path of this machine in ``upload`` mode
saw one that was never sent.
"""

import asyncio
import importlib.util
import json
import os
import sys

import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad import runtime as pc_runtime
from partcad import shape_envelope, wrapper_container
from partcad.cache_shape import ShapeCache
from partcad_utils import container_service, containers
from partcad_utils.json_rpc_client import RuntimeJsonRpcClient

IMAGE = "ghcr.io/example/csg:1.2.3"

PARTCAD_YAML = """\
partTypes:
  cube:
    path: cube.py
    extension: size
    container:
      image: %s
      name: csg
parts:
  small:
    type: ":cube"
""" % (IMAGE,)

# A script of the kind the container exists for, minus the native program: it
# reads the part's file, keeps something in its cache, and builds the shape.
# What it saw is written into the cache, where the test reads it back -- which
# in 'upload' mode is also the proof that the cache came back.
SCRIPT = """\
import json
import os

if __name__ == "__partcad_part__":
    from build123d import Box

    with open(request["path"]) as f:  # noqa: F821
        size = float(f.read())
    os.makedirs(request["cache_dir"], exist_ok=True)  # noqa: F821
    with open(os.path.join(request["cache_dir"], "seen.json"), "w") as f:  # noqa: F821
        json.dump({"path": request["path"], "cache_dir": request["cache_dir"], "script": __file__}, f)  # noqa: F821
    output = {"shape": Box(size, size, size).wrapped}
"""


@pytest.fixture
def server(monkeypatch, tmp_path):
    """The container's service, loaded from its file without a container."""
    monkeypatch.setenv("PC_CONTAINER_ALLOWED_COMMANDS", json.dumps({"python": sys.executable}))
    monkeypatch.setenv("PC_CONTAINER_SANDBOX_ROOT", str(tmp_path / "pc-sandbox"))
    monkeypatch.setenv("PC_CONTAINER_STORE", str(tmp_path / "pc-store"))
    spec = importlib.util.spec_from_file_location("pc_container_json_rpc", container_service.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Wire(RuntimeJsonRpcClient):
    """The RPC client with the socket taken out: the frames each way are the real ones."""

    def __init__(self, server):
        super().__init__("127.0.0.1", 0, token="wire-%d" % id(self))
        self.server = server
        self.sent = None

    def _post_frame(self, parts, timeout):
        body = b"".join(bytes(memoryview(part)) for part in parts)
        payload = self.server.decode_frame(body)
        if payload["method"] == "execute":
            self.sent = payload["params"]
        answer = self.server.encode_frame(self.server.dispatch(payload, frames=True))
        return 200, self.server.FRAME_TYPE, b"".join(bytes(memoryview(part)) for part in answer)


class _WiredEndpoint(containers.Endpoint):
    def __init__(self, wire, mode):
        super().__init__(
            name="partcad-plugin-csg-test",
            spec=containers.ContainerSpec(role="plugin-csg", image=IMAGE, mode=mode),
            container=None,
            host="127.0.0.1",
            port=0,
            token=None,
        )
        self.wire = wire

    def client(self):
        return self.wire


@pytest.fixture
def package(tmp_path):
    directory = tmp_path / "pkg"
    directory.mkdir()
    (directory / "partcad.yaml").write_text(PARTCAD_YAML)
    (directory / "cube.py").write_text(SCRIPT)
    (directory / "small.size").write_text("7")
    return directory


def _context(package, tmp_path):
    ctx = pc.Context(str(package))
    ctx.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "state"))
    return ctx


def _contained(ctx, server, mode, monkeypatch):
    """Have 'ctx' start every container as the in-process service; what it was asked for is returned."""
    made = pc_runtime.Runtime(ctx, "partcad-plugin-csg-test")
    made.use_container(_WiredEndpoint(_Wire(server), mode))
    asked = []

    async def get_container_runtime(container):
        asked.append(container)
        return made

    monkeypatch.setattr(ctx, "get_container_runtime", get_container_runtime)
    return made, asked


def _volume(ctx, name):
    part = ctx.get_part(name)
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    return envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]["volume"]


# --------------------------------------------------------------------------- #
# What a declaration says                                                     #
# --------------------------------------------------------------------------- #


def test_the_short_form_is_the_image():
    assert wrapper_container.declaration(IMAGE, "A partType") == {"image": IMAGE}


def test_the_long_form_is_kept():
    declared = {"image": IMAGE, "name": "csg", "command": "python3"}
    assert wrapper_container.declaration(declared, "A partType") == declared
    assert wrapper_container.command_of(declared) == "python3"
    assert wrapper_container.command_of({"image": IMAGE}) == "python"


def test_nothing_declared_is_no_container():
    assert wrapper_container.declaration(None, "A partType") is None
    assert wrapper_container.declaration("", "A partType") is None


@pytest.mark.parametrize("declared", [{"name": "csg"}, {"image": ""}, ["an", "image"], {"image": IMAGE, "name": 3}])
def test_a_declaration_that_is_not_one_is_refused(declared):
    with pytest.raises(ValueError, match="partType 'cube'"):
        wrapper_container.declaration(declared, "partType 'cube'")


def test_the_schema_takes_both_forms():
    import jsonschema

    from partcad.lint.all import get_partcad_schema

    for container in (IMAGE, {"image": IMAGE, "name": "csg", "command": "python"}):
        config = {"partTypes": {"cube": {"path": "cube.py", "container": container}}}
        jsonschema.validate(instance=config, schema=get_partcad_schema())
    # There is no 'port': PartCAD chooses where to reach its own service.
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(
            instance={"partTypes": {"cube": {"container": {"image": IMAGE, "port": 5000}}}},
            schema=get_partcad_schema(),
        )


# --------------------------------------------------------------------------- #
# What the part is keyed on                                                   #
# --------------------------------------------------------------------------- #


def test_a_part_built_in_a_container_is_keyed_on_its_image(package, tmp_path):
    """The image as declared, and what runs in it -- not the sandbox's interpreter and requirements."""
    ctx = _context(package, tmp_path)
    key = ctx.get_part(":small").environment_cache_key
    assert key == wrapper_container.cache_key({"image": IMAGE, "name": "csg"})
    assert key.startswith("container==python;")
    assert IMAGE in key


def test_another_image_is_another_key():
    assert wrapper_container.cache_key({"image": IMAGE}) != wrapper_container.cache_key(
        {"image": IMAGE.replace("1.2.3", "1.2.4")}
    )
    assert wrapper_container.cache_key({"image": IMAGE}) != wrapper_container.cache_key(
        {"image": IMAGE, "command": "python3"}
    )


# --------------------------------------------------------------------------- #
# Built there, in both modes                                                  #
# --------------------------------------------------------------------------- #


def test_in_mount_mode_the_script_reads_the_files_where_they_are(package, tmp_path, server, monkeypatch):
    ctx = _context(package, tmp_path)
    made, asked = _contained(ctx, server, containers.MOUNT, monkeypatch)

    assert _volume(ctx, ":small") == pytest.approx(7**3)

    assert asked == [{"image": IMAGE, "name": "csg"}]
    command = made.endpoint.wire.sent["command"]
    assert command[0] == "python"
    assert os.path.basename(command[1]) == "wrapper_part_type.py"
    seen = json.loads((package / ".cache" / "seen.json").read_text())
    assert seen["path"] == str(package / "small.size")
    assert seen["cache_dir"] == str(package / ".cache")
    # Nothing sent: the container has the files at these paths.
    assert not made.endpoint.wire.sent.get("input_trees")


def test_in_upload_mode_the_files_travel_and_the_cache_comes_back(package, tmp_path, server, monkeypatch):
    ctx = _context(package, tmp_path)
    made, _asked = _contained(ctx, server, containers.UPLOAD, monkeypatch)

    assert _volume(ctx, ":small") == pytest.approx(7**3)

    sent = made.endpoint.wire.sent
    # The package (with the part's file in it), the wrappers, and the cache as
    # a directory of its own -- the one that comes back.
    assert str(package) in sent["input_trees"]
    assert str(package / ".cache") in sent["input_trees"]
    assert sent["output_dirs"] == [str(package / ".cache")]
    # What the script wrote into its cache is here, and what it saw were the
    # paths the container unpacked to: none of this machine's.
    seen = json.loads((package / ".cache" / "seen.json").read_text())
    for key in ("path", "cache_dir", "script"):
        assert not seen[key].startswith(str(package)), (key, seen[key])
    assert os.path.basename(seen["path"]) == "small.size"


def test_the_python_sandbox_is_not_prepared(package, tmp_path, server, monkeypatch):
    """Nothing is installed for a part that runs in a container: the image is what it has."""
    from partcad.part_factory_wrapper import PartFactoryWrapper

    async def refuse(*_args, **_kwargs):
        raise AssertionError("the Python sandbox was asked to prepare")

    monkeypatch.setattr(PartFactoryWrapper, "_prepare_sandbox_async", refuse)
    ctx = _context(package, tmp_path)
    _contained(ctx, server, containers.MOUNT, monkeypatch)
    assert _volume(ctx, ":small") == pytest.approx(7**3)


# --------------------------------------------------------------------------- #
# Where it cannot run                                                         #
# --------------------------------------------------------------------------- #


def test_with_no_container_runtime_the_part_fails_saying_so(package, tmp_path, monkeypatch):
    monkeypatch.setattr(pc_runtime, "docker_available", lambda: False)
    ctx = _context(package, tmp_path)
    part = ctx.get_part(":small")

    assert asyncio.run(part.get_wrapped(ctx)) is None
    said = "\n".join(str(error) for error in part.errors)
    assert "no container runtime" in said
    assert IMAGE in said


def test_an_image_without_ocp_is_told_so(package, tmp_path, server, monkeypatch):
    """The image's interpreter cannot import OCP: the part says what the image lacks, not where it tripped."""
    shadow = tmp_path / "no-ocp"
    shadow.mkdir()
    (shadow / "OCP.py").write_text("raise ImportError('no OCP in this image')\n")
    # The service's children inherit this process's environment, as a
    # container's commands inherit the image's.
    monkeypatch.setenv("PYTHONPATH", str(shadow))
    ctx = _context(package, tmp_path)
    _contained(ctx, server, containers.MOUNT, monkeypatch)
    part = ctx.get_part(":small")

    assert asyncio.run(part.get_wrapped(ctx)) is None
    said = "\n".join(str(error) for error in part.errors)
    assert "cannot import OCP" in said
    assert "partcad-container-python" in said


# --------------------------------------------------------------------------- #
# What it does not need                                                       #
# --------------------------------------------------------------------------- #


def test_no_python_sandbox_is_made_for_a_part_that_runs_in_a_container(package, tmp_path, monkeypatch):
    """A sandbox this machine cannot make must not fail a part that never uses one."""
    ctx = _context(package, tmp_path)

    def refuse(*_args, **_kwargs):
        raise AssertionError("a Python sandbox was made")

    monkeypatch.setattr(ctx, "get_python_runtime", refuse)
    part = ctx.get_part(":small")
    assert part is not None, "the part was not created"


def _late_key(package, tmp_path, image, monkeypatch):
    """The key 'small' is read from the cache under, its partType declaring 'image' and unknown as it was created."""
    (package / "partcad.yaml").write_text(PARTCAD_YAML.replace(IMAGE, image))
    declaration = wrapper_container.declaration
    creating = [True]

    def not_yet(declared, who):
        # As if the partType's package had not been reachable when the part was made.
        return None if creating[0] else declaration(declared, who)

    monkeypatch.setattr(wrapper_container, "declaration", not_yet)
    ctx = _context(package, tmp_path / image.replace("/", "_").replace(":", "_"))
    part = ctx.get_part(":small")
    creating[0] = False
    assert part.environment_cache_key.startswith("python==")
    asyncio.run(part.prepare_async())
    return part.hash.get()


def test_a_part_type_resolved_late_is_still_keyed_on_its_image(package, tmp_path, monkeypatch):
    """Keyed on the image before the cache is read, so another image is never served the first one's shape."""
    first = _late_key(package, tmp_path, IMAGE, monkeypatch)
    second = _late_key(package, tmp_path, IMAGE.replace("1.2.3", "1.2.4"), monkeypatch)
    assert first is not None and second is not None
    assert first != second


def test_a_part_type_resolved_late_needs_no_python_sandbox(package, tmp_path, server, monkeypatch):
    """Unknown as the part was created, and no sandbox can be made here: the part is still built in its container."""
    declaration = wrapper_container.declaration
    creating = [True]

    def not_yet(declared, who):
        return None if creating[0] else declaration(declared, who)

    monkeypatch.setattr(wrapper_container, "declaration", not_yet)
    ctx = _context(package, tmp_path)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("this machine cannot make that sandbox")

    monkeypatch.setattr(ctx, "get_python_runtime", unavailable)
    _contained(ctx, server, containers.MOUNT, monkeypatch)
    part = ctx.get_part(":small")
    assert part is not None
    creating[0] = False
    assert _volume(ctx, ":small") == pytest.approx(7**3)
