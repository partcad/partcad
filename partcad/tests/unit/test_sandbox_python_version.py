#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which interpreter a sandbox ends up on.

Two halves of one question: what a package that names no Python gets, and what
happens when the version asked for is one the pinned CAD stack has no wheels
for. The first used to be decided by the interpreter PartCAD itself had been
installed on, and the second had no answer at all - the version was passed
through and every part rendered in that sandbox failed on an import of something
pip had never managed to install.
"""

import pytest

import partcad as pc
from partcad import sandbox_versions
from partcad.project_config import Configuration
from partcad.user_config import UserConfig


def test_a_package_that_names_no_python_gets_the_pinned_one(tmp_path):
    """Not the one PartCAD is running on, which is what this used to be.

    Matching the host bought nothing - a conda sandbox is built from scratch at
    whatever version is asked for, and a 'none' sandbox ignores the version
    entirely - while making the sandbox a property of how PartCAD happened to be
    installed.
    """
    config = Configuration("test", str(tmp_path), config_obj={})
    assert config.python_version == sandbox_versions.DEFAULT_PYTHON_VERSION


def test_a_package_that_names_a_python_keeps_it(tmp_path):
    config = Configuration("test", str(tmp_path), config_obj={"pythonVersion": "3.12"})
    assert config.python_version == "3.12"


@pytest.fixture
def ctx(tmp_path):
    """A context whose sandboxes are the host interpreter, so none get built.

    get_python_runtime() only constructs the runtime object; the sandbox itself
    is not provisioned until something renders in it.
    """
    (tmp_path / "partcad.yaml").write_text("desc: which interpreter\n")
    user_config = UserConfig()
    user_config.set("python_sandbox", "none")
    return pc.Context(str(tmp_path), search_root=False, user_config=user_config)


def test_a_python_newer_than_the_pins_is_held_down(ctx):
    """Every sandbox is preloaded with the CAD stack, so every sandbox is bounded."""
    assert ctx.get_python_runtime("3.99").version == sandbox_versions.MAX_PYTHON_VERSION_CAD


@pytest.mark.parametrize("version", ["3.11", "3.12", sandbox_versions.MAX_PYTHON_VERSION_CAD])
def test_a_python_the_pins_cover_is_left_alone(ctx, version):
    assert ctx.get_python_runtime(version).version == version


def test_the_floor_is_not_applied_here(ctx):
    """Only the ceiling is universal. The floor belongs to CadQuery alone.

    CadQuery has no 3.10 release, so the factories that need it render on 3.11 or
    newer - but a 3.10 sandbox is a perfectly good place to convert an STL, and
    forcing every one of them up to 3.11 would provision a second sandbox to do
    what the first could.
    """
    assert ctx.get_python_runtime("3.10").version == "3.10"


def test_holding_a_version_down_is_said_out_loud_once(ctx, caplog):
    """Silently rendering on an interpreter nobody asked for is its own bug report."""
    with caplog.at_level("WARNING"):
        ctx.get_python_runtime("3.99")
        ctx.get_python_runtime("3.99")

    said = [record for record in caplog.records if "3.99" in record.message]
    assert len(said) == 1
    assert sandbox_versions.MAX_PYTHON_VERSION_CAD in said[0].message


def test_no_version_at_all_is_the_pinned_one(ctx):
    """The same default as a package's, for the callers that name no version."""
    assert ctx.get_python_runtime().version == sandbox_versions.DEFAULT_PYTHON_VERSION


def test_a_version_the_bound_cannot_read_is_passed_through(ctx):
    """'pc init' writes ">=<host version>", and the schema's pattern allows it.

    Such a value is already one neither the bound nor the sandbox naming can
    reason about. That is worth fixing somewhere, but not by having the bound be
    what discovers it: a package carrying one has to keep working exactly as it
    did.
    """
    assert ctx.get_python_runtime(">=3.12").version == ">=3.12"
