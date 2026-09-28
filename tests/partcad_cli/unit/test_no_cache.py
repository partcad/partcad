#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc --no-cache`: one run that neither reads from nor writes to any cache tier."""

from partcad import cache_backend
from partcad_cli.click.command import _bypass_cache, cli
from partcad_utils.user_config import UserConfig


def test_the_flag_is_a_global_option():
    option = next(param for param in cli.params if param.name == "cache_bypass")
    assert "--no-cache" in option.opts
    assert option.envvar == "PC_CACHE_BYPASS"


def test_the_flag_travels_to_the_daemon(monkeypatch, tmp_path):
    """What the daemon builds its context from is 'to_dict()', not the attributes.

    Set as an attribute alone, a command served by a warm daemon would go on
    reading and writing the cache it was told to leave alone.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_CACHE_BYPASS", raising=False)
    config = UserConfig()

    _bypass_cache(config, {"cache_bypass": True})

    assert config.cache_bypass is True
    assert UserConfig.from_dict(config.to_dict()).cache_bypass is True


def test_without_the_flag_nothing_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_CACHE_BYPASS", raising=False)
    config = UserConfig()

    _bypass_cache(config, {"cache_bypass": None})

    assert config.cache_bypass is False
    assert config.to_dict().get("cacheBypass") is False


def test_a_bypassed_configuration_has_no_cache_tier(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = UserConfig()
    config.cache = True
    assert cache_backend.build(config, "shapes")

    config.cache_bypass = True
    assert cache_backend.build(config, "shapes") == []
