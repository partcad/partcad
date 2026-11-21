#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc upgrade` refuses inside the PartCAD image.

The image's PartCAD is an ordinary wheel in `site-packages`, so without this it
reads as a wheel installation, and `pc upgrade` pip-installs a newer PartCAD
into the container: gone the next time the image is run, and meanwhile replacing
the PartCAD that image was tested with. A newer PartCAD is a newer image, and
the refusal says how to get one.
"""

import pytest

from partcad_client import selfupdate
from partcad_utils import app_image


@pytest.fixture
def in_the_image(monkeypatch):
    monkeypatch.setenv(app_image.MANAGED_BY_ENV, app_image.MANAGED_BY_IMAGE)
    monkeypatch.delenv(app_image.IMAGE_ENV, raising=False)


def test_the_image_says_so(in_the_image):
    assert selfupdate.installation_kind() == selfupdate.KIND_IMAGE


def test_the_check_says_to_pull_instead(in_the_image):
    status = selfupdate.check()
    assert status["kind"] == selfupdate.KIND_IMAGE
    assert status["update_available"] is False
    assert "docker pull ghcr.io/partcad/partcad:latest" in status["reason"]


def test_a_pinned_version_is_the_tag_to_pull(in_the_image):
    assert "docker pull ghcr.io/partcad/partcad:0.10.1" in selfupdate.check(to_version="0.10.1")["reason"]


def test_the_image_it_names_is_the_one_this_runs_in(in_the_image, monkeypatch):
    monkeypatch.setenv(app_image.IMAGE_ENV, "ghcr.io/someone/partcad")
    assert "docker pull ghcr.io/someone/partcad:latest" in selfupdate.check()["reason"]


def test_the_update_refuses_before_touching_anything(in_the_image, monkeypatch):
    """Nothing is looked up, stopped or installed: the refusal comes first."""

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("an image installation must not reach the installer")

    monkeypatch.setattr(selfupdate, "latest_version", must_not_run)
    monkeypatch.setattr(selfupdate, "_install_wheels", must_not_run)
    with pytest.raises(selfupdate.SelfUpdateError, match="docker pull"):
        selfupdate.update(before_install=must_not_run)


def test_the_extensions_value_is_still_the_extensions(monkeypatch):
    """One variable, two values: the image's must not read as the extension's, nor the other way round."""
    monkeypatch.setenv(app_image.MANAGED_BY_ENV, selfupdate.MANAGED_BY_EXTENSION)
    assert selfupdate.installation_kind() == selfupdate.KIND_IDE_MANAGED
