#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import platform

from .healthcheck import HealthCheckReport, HealthCheckTest
import partcad.logging as pc_logging

if platform.system() == "Windows":
    import winreg


class WindowsRegistryCheck(HealthCheckTest):
    #  Base class for all Windows registry checks
    registry_path: str | None = None
    registry_key: str | None = None
    expected_value: str | None = None
    value_type: int | None = None

    def __init__(self, name: str):
        super().__init__(
            name=name,
            tags=["windows", "registry"],
            description=f"Check whether the windows registry key '{name}' is {'enabled' if self.expected_value == 1 else 'disabled'}",
        )

    def auto_fixable(self) -> bool:
        return True

    def is_applicable(self) -> bool:
        return platform.system() == "Windows"

    def test(self):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path) as key:
                value, _ = winreg.QueryValueEx(key, self.registry_key)
                if value != self.expected_value:
                    self.findings.append(f"{self.registry_key} is not set to {self.expected_value}")
        except FileNotFoundError as e:
            pc_logging.debug(e)
            self.findings.append(f"{self.registry_key} registry key not found")
        return HealthCheckReport(self.name, self.findings, False)

    def fix(self):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self.registry_key, 0, self.value_type, self.expected_value)
            return True
        except Exception as e:
            pc_logging.error(e)

        return False


class LongPathsEnabledCheck(WindowsRegistryCheck):
    registry_path = r"SYSTEM\CurrentControlSet\Control\FileSystem"
    registry_key = "LongPathsEnabled"

    # Must be enabled to support long file paths in Windows
    expected_value = 1

    def __init__(self):
        super().__init__("LongPathsEnabledCheck")
        if platform.system() == "Windows":
            LongPathsEnabledCheck.value_type = winreg.REG_DWORD


class NoDefaultCurrentDirectoryCheck(WindowsRegistryCheck):
    registry_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    registry_key = "NoDefaultCurrentDirectoryInExePath"

    # Must be disabled to allow the default resolution of the current
    # directory from the directory of an executable.
    expected_value = 0

    def __init__(self):
        super().__init__("NoDefaultCurrentDirectoryCheck")
        if platform.system() == "Windows":
            NoDefaultCurrentDirectoryCheck.value_type = winreg.REG_DWORD
