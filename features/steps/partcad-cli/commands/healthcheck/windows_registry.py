import platform
from behave import *
from unittest.mock import MagicMock, Mock

@given("the system is running on Windows")
def step_impl(context):
    if platform.system() != "Windows":
        context.scenario.skip("Skipping Windows-specific tests on non-Windows platform")
    context.reg_key_values = {}
    context.mock_winreg = Mock()
    context.mock_winreg.OpenKey = MagicMock()

@given('"{reg_key}" registry key is set to "{val}"')
def step_impl(context, reg_key, val):
    context.reg_key_values[reg_key] = int(val)
    context.mock_winreg.QueryValueEx = lambda key, value: (context.reg_key_values[value], None)

@given('"{reg_key}" registry key is missing')
def step_impl(context, reg_key):
    context.mock_winreg.OpenKey.side_effect = FileNotFoundError
