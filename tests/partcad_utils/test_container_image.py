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
def _no_inherited_override(no_image_tag_override):
    """The variable must not leak in from the environment running the suite.

    CI sets it on the runs that build branch images, and this file's whole
    subject is what happens with and without it. The shared fixture in
    'tests/conftest.py' is the one implementation; every test here wants it, so
    it is taken automatically rather than named once per test.
    """


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

    Which is also why *both* halves reload. The suite itself may have been
    started with the variable set -- CI starts it that way on a run that
    rebuilt these images -- and the constant then carries that tag from before
    this test existed, whatever the environment says by the time it runs. So
    the "without" half is a reload too, under the fixture above.

    And why the module is put back under the environment the *suite* has rather
    than the one this test made. Reloading it with the variable removed leaves a
    constant saying "the release" in a process where the release image may not
    exist -- this being a run that published its own -- for whatever runs next
    in this worker. Nothing in the suite reads that constant after this file
    today, in the order a serial run happens to produce; `pytest-xdist` hands a
    worker whatever files it hands it, and "happens to produce" is not a thing
    to rest on. `monkeypatch.undo()` is what restores it: the fixture above and
    this test share one `monkeypatch`, so undoing it takes out the removal as
    well as the override, and the reload after it reads what the process started
    with.
    """
    import partcad_client.external as external

    assert importlib.reload(external).TOOLS["kicad"].image.endswith(":" + external.__version__)

    monkeypatch.setenv(container_image.ENV_VAR, external.__version__ + "-my-branch")
    reloaded = importlib.reload(external)
    try:
        assert reloaded.TOOLS["kicad"].image.endswith(":" + external.__version__ + "-my-branch")
    finally:
        monkeypatch.undo()
        importlib.reload(external)

    # Left agreeing with the environment, whichever environment that is: the
    # release on a developer machine, the tag this run published in CI.
    assert external.TOOLS["kicad"].image.endswith(":" + container_image.image_tag(external.__version__))


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


def test_the_owner_is_partcads_when_nothing_says_otherwise():
    assert container_image.image_name("ghcr.io/partcad/partcad-container-python") == (
        "ghcr.io/partcad/partcad-container-python"
    )


def test_the_owner_override_replaces_only_the_owner(monkeypatch):
    """The registry and the image's own name are not the fork's to change."""
    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "seekbirdy")
    assert container_image.image_name("ghcr.io/partcad/partcad-container-python") == (
        "ghcr.io/seekbirdy/partcad-container-python"
    )


def test_the_owner_is_lowercased(monkeypatch):
    """A GitHub login may hold capitals and a registry path may not.

    `ghcr.io/SeekBirdy/...` is refused at the push, with an error about the
    name rather than about the case -- and the run that hits it is a fork's
    first, which is the worst moment to hand somebody that.
    """
    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "SeekBirdy")
    assert container_image.image_name("ghcr.io/partcad/partcad-container-python") == (
        "ghcr.io/seekbirdy/partcad-container-python"
    )


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_a_blank_owner_is_unset_rather_than_an_owner(monkeypatch, value):
    monkeypatch.setenv(container_image.ENV_VAR_OWNER, value)
    assert container_image.image_name("ghcr.io/partcad/partcad-container-python") == (
        "ghcr.io/partcad/partcad-container-python"
    )


@pytest.mark.parametrize("name", ["partcad-container-python", "partcad/partcad-container-python"])
def test_a_name_this_cannot_parse_is_left_alone(monkeypatch, name):
    """Rewriting a segment of it would invent a reference rather than redirect one."""
    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "seekbirdy")
    assert container_image.image_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["ghcr.io/someone-else/their-image", "docker.io/library/alpine", "quay.io/acme/thing"],
)
def test_an_image_that_is_not_partcads_is_left_alone(monkeypatch, name):
    """This redirects PartCAD's own images and nothing else.

    `//builtin/open` is data: a user may declare a tool of their own with an
    image of their own, and `partcad_client.external` runs every declaration
    through here. Moving somebody else's image into a fork's namespace would
    point the run at a repository with nothing to do with it -- and would fail
    to pull, which is the better of the two outcomes.
    """
    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "seekbirdy")
    assert container_image.image_name(name) == name


def test_the_image_pc_open_starts_follows_the_owner(monkeypatch):
    """The second reader of the image `container-kicad.yml` publishes.

    That workflow publishes `<this repository>-container-kicad`, so in a fork
    the image is the fork's. `partcad.part_factory_kicad` follows the owner;
    this path is the other consumer, and one following while the other does not
    is how `pc open --with kicad` ends up reaching for a tag nobody published.
    """
    import importlib

    import partcad_client.external as external

    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "seekbirdy")
    reloaded = importlib.reload(external)
    try:
        assert reloaded.TOOLS["kicad"].image.startswith("ghcr.io/seekbirdy/")
    finally:
        monkeypatch.undo()
        importlib.reload(external)


def test_the_python_sandbox_image_follows_the_owner(monkeypatch):
    from partcad import runtime_python_docker

    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "seekbirdy")
    assert runtime_python_docker.image_for("3.11", "0.8.70").startswith("ghcr.io/seekbirdy/")


def test_both_overrides_apply_together(monkeypatch):
    """What a fork that built its own images actually exports: owner and tag."""
    from partcad import runtime_python_docker

    monkeypatch.setenv(container_image.ENV_VAR_OWNER, "seekbirdy")
    monkeypatch.setenv(container_image.ENV_VAR, "0.8.70-my-branch")
    assert runtime_python_docker.image_for("3.11", "0.8.70") == (
        "ghcr.io/seekbirdy/partcad-container-python:0.8.70-my-branch-py3.11"
    )
