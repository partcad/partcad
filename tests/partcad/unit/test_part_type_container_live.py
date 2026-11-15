#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A partType's ``container:``, run in a real container.

`test_part_type_container.py` runs the same part through the container's
service in this process; this starts the container through
`Context.get_container_runtime`, the way a user's PartCAD does, in both of the
ways files reach it.

Skipped where no Docker daemon answers. Two images:

* one with no OCP in it -- ``python:3.12-slim``, or ``PC_TEST_CONTAINER_IMAGE``
  as `tests/partcad_utils/test_containers_live.py` reads it -- where a part
  fails saying what the image lacks;
* one with OCP, named by ``PC_TEST_PART_TYPE_IMAGE`` (an image built ``FROM``
  ``partcad-container-python`` with build123d installed, as
  ``docs/source/plugins/part_types.rst`` says to), where a part is built. That
  test is skipped when the variable is not set: building such an image is a
  download of the OCP stack, which is not a cost every run should pay.

Every container a test starts carries a role unique to this session and is
removed at the end.
"""

import asyncio
import json
import os
import sys
import uuid

import pytest
from cache_config import CacheUserConfig

docker = pytest.importorskip("docker")

import partcad as pc  # noqa: E402
from partcad import shape_envelope  # noqa: E402
from partcad.cache_shape import ShapeCache  # noqa: E402
from partcad_utils import containers  # noqa: E402

WITHOUT_OCP = os.environ.get("PC_TEST_CONTAINER_IMAGE", "python:3.12-slim")
WITH_OCP = os.environ.get("PC_TEST_PART_TYPE_IMAGE")
SESSION = uuid.uuid4().hex[:8]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux containers on a Windows runner")

SCRIPT = """\
import json
import os

if __name__ == "__partcad_part__":
    from build123d import Box

    with open(request["path"]) as f:  # noqa: F821
        size = float(f.read())
    os.makedirs(request["cache_dir"], exist_ok=True)  # noqa: F821
    with open(os.path.join(request["cache_dir"], "seen.json"), "w") as f:  # noqa: F821
        json.dump({"path": request["path"], "cache_dir": request["cache_dir"]}, f)  # noqa: F821
    output = {"shape": Box(size, size, size).wrapped}
"""


@pytest.fixture(scope="module")
def client():
    try:
        client = docker.from_env()
        client.ping()
        if str(client.info().get("OSType", "")).lower() not in ("", "linux"):
            pytest.skip("this daemon does not run Linux containers")
    except Exception as e:
        pytest.skip("no Docker daemon answers here: %s" % e)
    yield client
    for container in client.containers.list(all=True, filters={"label": containers.LABEL_CONTAINER}):
        if container.labels.get(containers.LABEL_ROLE, "") == "plugin-live-" + SESSION:
            container.remove(force=True)


def _image(client, image):
    try:
        containers.resolve_image(client, image)
    except Exception as e:
        pytest.skip("cannot get %s: %s" % (image, e))
    return image


def _context(tmp_path, image, upload, monkeypatch):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "partcad.yaml").write_text(
        "partTypes:\n"
        "  cube:\n"
        "    path: cube.py\n"
        "    extension: size\n"
        "    container:\n"
        "      image: %s\n"
        "      name: live-%s\n"
        "parts:\n"
        "  small:\n"
        '    type: ":cube"\n' % (image, SESSION)
    )
    (package / "cube.py").write_text(SCRIPT)
    (package / "small.size").write_text("6")
    ctx = pc.Context(str(package))
    ctx.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "state"))
    monkeypatch.setattr(ctx.user_config, "use_docker_remote", upload)
    return ctx, package


@pytest.mark.parametrize("upload", [False, True], ids=["mount", "upload"])
def test_an_image_without_ocp_fails_the_part_saying_so(client, tmp_path, monkeypatch, upload):
    ctx, _package = _context(tmp_path, _image(client, WITHOUT_OCP), upload, monkeypatch)
    part = ctx.get_part(":small")

    assert asyncio.run(part.get_wrapped(ctx)) is None
    said = "\n".join(str(error) for error in part.errors)
    assert "cannot import OCP" in said, said


@pytest.mark.skipif(not WITH_OCP, reason="PC_TEST_PART_TYPE_IMAGE names no image with OCP in it")
@pytest.mark.parametrize("upload", [False, True], ids=["mount", "upload"])
def test_a_part_is_built_in_its_image(client, tmp_path, monkeypatch, upload):
    ctx, package = _context(tmp_path, _image(client, WITH_OCP), upload, monkeypatch)
    part = ctx.get_part(":small")

    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    measured = envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["volume"] == pytest.approx(6**3)
    # What the script kept in its cache is here, in both modes; in 'upload'
    # mode it saw the paths the container unpacked to.
    seen = json.loads((package / ".cache" / "seen.json").read_text())
    assert seen["path"].startswith(str(package)) is not upload
    assert seen["cache_dir"].startswith(str(package)) is not upload
