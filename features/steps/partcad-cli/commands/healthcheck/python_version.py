from behave import *
from unittest.mock import Mock
from collections import namedtuple

VersionInfo = namedtuple("VersionInfo", ["major", "minor"])

@given('system python version is "{python_version}"')
def step_impl(context, python_version):
    major, minor = map(int, python_version.split("."))

    context.mock_sys = Mock()
    context.mock_sys.version_info = VersionInfo(major, minor)
