#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this runs in the PartCAD image, and the `docker run` that starts it.

The Dockerfile is the other half of each of these -- it sets the variables read
here and creates the directory the volume is mounted at -- and
`tests/dev_tools/test_partcad_image.py` holds the two together.
"""

import pytest

from partcad_utils import app_image


@pytest.fixture
def outside(monkeypatch):
    monkeypatch.delenv(app_image.MANAGED_BY_ENV, raising=False)
    monkeypatch.delenv(app_image.IMAGE_ENV, raising=False)


def test_only_the_images_own_value_counts(outside, monkeypatch):
    assert not app_image.running_in_image()
    monkeypatch.setenv(app_image.MANAGED_BY_ENV, "vscode-extension")
    assert not app_image.running_in_image()
    monkeypatch.setenv(app_image.MANAGED_BY_ENV, app_image.MANAGED_BY_IMAGE)
    assert app_image.running_in_image()


def test_the_image_is_the_published_one_unless_this_runs_in_another(outside, monkeypatch):
    assert app_image.image() == "ghcr.io/partcad/partcad"
    monkeypatch.setenv(app_image.IMAGE_ENV, "  ")
    assert app_image.image() == "ghcr.io/partcad/partcad"
    monkeypatch.setenv(app_image.IMAGE_ENV, "ghcr.io/someone/partcad")
    assert app_image.image() == "ghcr.io/someone/partcad"


def test_the_workspace_is_mounted_where_it_is_and_worked_in(outside):
    args = app_image.docker_run_args("/home/me/widget", "render", "cube")
    assert args == [
        "run",
        "-i",
        "--rm",
        "-v",
        "partcad-home:/home/pc/.partcad",
        "-v",
        "/home/me/widget:/home/me/widget",
        "-w",
        "/home/me/widget",
        "ghcr.io/partcad/partcad",
        "render",
        "cube",
    ]


def test_the_socket_is_only_passed_when_asked_for(outside):
    assert not any("docker.sock" in arg for arg in app_image.docker_run_args("/w"))
    args = app_image.docker_run_args("/w", "mcp", socket=True)
    assert "/var/run/docker.sock:/var/run/docker.sock" in args
    assert args.index("/var/run/docker.sock:/var/run/docker.sock") < args.index("ghcr.io/partcad/partcad")


def test_an_explicit_reference_wins(outside):
    assert app_image.docker_run_args("/w", image_ref="ghcr.io/partcad/partcad:0.10.20")[-1] == (
        "ghcr.io/partcad/partcad:0.10.20"
    )
