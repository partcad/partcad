#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import copy
from unittest.mock import mock_open, patch

import pytest

import partcad as pc


@pytest.fixture(autouse=True)
def setup_function() -> None:
    """
    Automatically resets error states before each test.
    This fixture ensures a clean slate for testing.
    """
    pc.logging.reset_errors()


@pytest.fixture(autouse=True)
def restore_parameter_config():
    """
    Restores the user configuration parameter overrides after each test.

    'pc.user_config' is a process-wide singleton, so a test that overrides an
    object's parameters would otherwise leak them into every test that happens
    to run afterwards, making the outcome depend on the test order.
    """
    saved = copy.deepcopy(pc.user_config.parameter_config.to_dict())
    yield
    parameter_config = pc.user_config.parameter_config
    for key in list(parameter_config):
        del parameter_config[key]
    for key, value in saved.items():
        parameter_config[key] = value


@pytest.fixture
def mocked_git_open():
    """Mock the ``open()`` that ``partcad.project_factory_git`` uses, and only that one.

    A test that mocks the clone itself leaves the repository cache directory
    uncreated, so the guard file that ``project_factory_git`` writes beside the
    clone has nowhere to go and the write has to be mocked away.

    Patch the name in that module rather than ``builtins.open``: a global
    ``open()`` mock is also handed to the standard library, and the standard
    library opens files during ``pc.Context()`` on some platforms. On macOS
    ``Context.__init__`` computes the host tags, which reads the OS version out
    of ``/System/Library/CoreServices/SystemVersion.plist``; ``plistlib`` reads
    it in binary mode, so a mock handing back ``str`` fails there with
    ``TypeError: startswith first arg must be str or a tuple of str, not bytes``.
    That is invisible on Linux, so keep the mock where it belongs.

    ``create=True`` because ``open`` is a builtin: the module has no global of
    that name until this puts one there, which is exactly what makes the module
    find the mock while everyone else keeps the real thing.
    """

    def _patch():
        return patch("partcad.project_factory_git.open", mock_open(read_data=""), create=True)

    return _patch
