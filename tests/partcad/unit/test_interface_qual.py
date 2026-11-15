#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Qualifying an interface: building it, with a verdict like any other object's.

An interface has no geometry, so no check of 'partcad.qual' applies to it; what
'pc qual test' asks of one is that it can be built -- its ports, and everything
it inherits. That used to answer None, which 'Project.test()' read as a failure
of every package declaring an interface; a declaration that could not be built
raised out of the whole run instead of failing as one object; and the half-built
interface was kept, so it passed the second time it was asked.
"""

import asyncio

import pytest
import yaml

import partcad as pc
import partcad.logging as pc_logging

GOOD = {"interfaces": {"mount": {"ports": {"top": {"location": [[0, 0, 10], [0, 0, 1], 0]}}}}}

# Inherits an interface nobody declares: refused as it is built, by raising.
MISSING_PARENT = {"interfaces": {"mount": {"inherits": {"nowhere": ""}}}}

# A 'ports:' section that is neither a list, a name nor a mapping.
INVALID_PORTS = {"interfaces": {"mount": {"ports": 5}}}


@pytest.fixture(autouse=True)
def _no_errors_left_behind():
    pc_logging.reset_errors()
    yield
    pc_logging.reset_errors()


def _project(tmp_path, package):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(package))
    ctx = pc.Context(str(tmp_path))
    return ctx, ctx.get_project("//")


def test_a_package_with_an_interface_that_builds_qualifies(tmp_path):
    ctx, project = _project(tmp_path, GOOD)
    assert project.test(ctx) is True
    assert project.test_log_wrapper(ctx) is True
    assert asyncio.run(project.test_async(ctx)) is True
    assert not pc_logging.had_errors


def test_an_interface_that_builds_qualifies_on_its_own(tmp_path):
    ctx, project = _project(tmp_path, GOOD)
    interface = project.get_interface("mount")
    assert interface.test() is True
    # What the 'test' method of the service, and so the editor, asks of it.
    assert interface.test_log_wrapper(ctx) is True
    assert not pc_logging.had_errors


@pytest.mark.parametrize(
    "package, reason",
    [(MISSING_PARENT, "Failed to find the interface to inherit: nowhere"), (INVALID_PORTS, "Invalid 'ports'")],
    ids=["missing-parent", "invalid-ports"],
)
def test_an_interface_that_does_not_build_fails_the_package_saying_why(tmp_path, monkeypatch, package, reason):
    logged = []
    error = pc_logging.error
    monkeypatch.setattr(pc_logging, "error", lambda *args, **kwargs: (logged.append(args), error(*args, **kwargs)))
    ctx, project = _project(tmp_path, package)
    # A verdict, not an exception out of the whole run.
    assert project.test(ctx) is False
    assert pc_logging.had_errors
    assert any("Qualification failed: //:mount" in str(args[0]) and reason in str(args[0]) for args in logged), logged


@pytest.mark.parametrize("package", [MISSING_PARENT, INVALID_PORTS], ids=["missing-parent", "invalid-ports"])
def test_an_interface_that_does_not_build_fails_every_time_it_is_asked(tmp_path, package):
    """Not half built and kept: a warm daemon asks the same object again on the next run."""
    ctx, project = _project(tmp_path, package)
    interface = project.get_interface("mount")
    assert interface.test() is False
    pc_logging.reset_errors()
    assert interface.test() is False
    assert pc_logging.had_errors
    with pytest.raises(Exception):
        interface.get_ports()
