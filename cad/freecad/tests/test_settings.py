#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Preferences, through the fallback store used when FreeCAD is not present."""

import os

import pytest
from partcad_freecad import settings


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    store = tmp_path / "freecad-addon.json"
    monkeypatch.setattr(settings, "_fallback_path", lambda: str(store))
    for name in ("PC_CAD_PACKAGE_DIR", "PC_CAD_BUNDLE_DIR"):
        monkeypatch.delenv(name, raising=False)
    return store


def test_nothing_is_open_to_begin_with():
    assert settings.package_dir() is None


def test_the_open_package_is_remembered():
    settings.set_package_dir("/w/project")

    assert settings.package_dir() == "/w/project"


def test_the_environment_overrides_the_stored_package():
    settings.set_package_dir("/w/project")
    os.environ["PC_CAD_PACKAGE_DIR"] = "/w/other"
    try:
        assert settings.package_dir() == "/w/other"
    finally:
        del os.environ["PC_CAD_PACKAGE_DIR"]


def test_recent_packages_are_most_recent_first_and_deduplicated():
    settings.set_package_dir("/w/a")
    settings.set_package_dir("/w/b")
    settings.set_package_dir("/w/a")

    assert settings.recent_packages() == ["/w/a", "/w/b"]


def test_the_recent_list_is_bounded():
    for index in range(12):
        settings.set_package_dir("/w/%d" % index)

    assert len(settings.recent_packages()) == 8


def test_a_corrupted_recent_list_is_ignored():
    settings.set(settings.KEY_RECENT, "not json")

    assert settings.recent_packages() == []


def test_the_bundle_directory_can_be_overridden(monkeypatch):
    monkeypatch.setenv("PC_CAD_BUNDLE_DIR", "/opt/bundles")

    assert settings.cache_dir() == "/opt/bundles"
