#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One tag, read the same way by everything that addresses PartCAD's images.

The Python sandbox images and the KiCad sandbox are PartCAD's own, and every
reader of them builds the reference the same way: the image name, then the
release. A run that builds those images out of the commit under test rather
than pulling the ones the release published has to redirect all of them at
once, and `PC_CONTAINER_IMAGE_TAG` is how -- so what matters is that no reader
has its own idea of the tag, and that an installed PartCAD, where the variable
is unset, still asks for the release.
"""

import importlib

import pytest

from partcad_utils import container_image


@pytest.fixture(autouse=True)
def _no_inherited_override(monkeypatch):
    """The variable must not leak in from the environment running the suite.

    CI sets it on the runs that build branch images, and this file's whole
    subject is what happens with and without it.
    """
    monkeypatch.delenv(container_image.ENV_VAR, raising=False)


def test_the_release_is_the_tag_when_nothing_says_otherwise():
    assert container_image.image_tag("0.8.70") == "0.8.70"


def test_the_override_replaces_it(monkeypatch):
    monkeypatch.setenv(container_image.ENV_VAR, "0.8.70-my-branch")
    assert container_image.image_tag("0.8.70") == "0.8.70-my-branch"


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_blank_is_unset_rather_than_a_tag(monkeypatch, value):
    """A reference ending in ':' is one no registry resolves.

    An empty value is a CI expression that evaluated to nothing, and the
    failure it would otherwise cause is a pull error a long way from the
    expression that went wrong.
    """
    monkeypatch.setenv(container_image.ENV_VAR, value)
    assert container_image.image_tag("0.8.70") == "0.8.70"


def test_the_python_sandbox_image_follows_it(monkeypatch):
    from partcad import runtime_python_docker

    assert runtime_python_docker.image_for("3.11", "0.8.70").endswith(":0.8.70-py3.11")

    monkeypatch.setenv(container_image.ENV_VAR, "0.8.70-my-branch")
    assert runtime_python_docker.image_for("3.11", "0.8.70").endswith(":0.8.70-my-branch-py3.11")


def test_the_kicad_image_pc_open_starts_follows_it(monkeypatch):
    """`partcad_client.external` resolves it at import, so reload to see it.

    That is the one reader whose tag is a module-level constant rather than a
    call, which is fine where it is used -- CI exports the variable before the
    process starts -- and is worth pinning precisely because it is the odd one.
    """
    import partcad_client.external as external

    assert external.TOOLS["kicad"].image.endswith(":" + external.__version__)

    monkeypatch.setenv(container_image.ENV_VAR, external.__version__ + "-my-branch")
    reloaded = importlib.reload(external)
    try:
        assert reloaded.TOOLS["kicad"].image.endswith(":" + external.__version__ + "-my-branch")
    finally:
        monkeypatch.delenv(container_image.ENV_VAR, raising=False)
        importlib.reload(external)


def test_no_reader_spells_the_tag_for_itself():
    """Every reference to one of PartCAD's images goes through `image_tag`.

    A second place that writes `":" + __version__` would be a reader the
    redirection silently misses -- which looks like the images being rebuilt
    and the tests still running against the release's.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    for source in ("src/partcad/part_factory_kicad.py", "src/partcad_client/external.py"):
        text = (root / source).read_text()
        assert "image_tag(" in text, source
        assert 'partcad-container-kicad:" + __version__' not in text, source

    docker_runtime = (root / "src/partcad/runtime_python_docker.py").read_text()
    assert "container_image.image_tag(release)" in docker_runtime
