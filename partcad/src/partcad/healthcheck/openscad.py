import os
import shutil
import zipfile
import hashlib
import platform
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
if platform.system() == "Windows":
    import winreg

from partcad.user_config import UserConfig
from partcad.logging import logging as pc_logging
from partcad.healthcheck.tests import HealthCheckReport, HealthCheckTest


class OpenSCADCheck(HealthCheckTest):
    def __init__(self):
        super().__init__("OpenSCAD", ["openscad"], "Check the availability of an OpenSCAD executable.")

    def auto_fixable(self) -> bool:
        return True

    def is_applicable(self) -> bool:
        return False

    def test(self) -> HealthCheckReport:
        if shutil.which("openscad") is None:
            self.findings.append("OpenSCAD executable not found in PATH")
        return HealthCheckReport(self.name, self.findings)


class LinuxOpenSCADCheck(OpenSCADCheck):
    def __init__(self):
        super().__init__()

    def is_applicable(self) -> bool:
        return platform.system() == "Linux"

    def fix(self) -> bool:
        """Attempt to install OpenSCAD on linux using apt-get"""
        try:
            pc_logging.info("Updating apt package index...")

            result = subprocess.run(["sudo", "apt-get", "update"], check=True, capture_output=True)

            if result.returncode != 0:
                pc_logging.error("OpenSCAD installation failed.")
                pc_logging.debug(result.stderr)
                return False

        except subprocess.CalledProcessError as e:
            pc_logging.error("Failed to update apt package index.")
            pc_logging.debug(e)
        except Exception as e:
            pc_logging.exception("Unexpected error during 'apt-get update'")
            return False

        try:
            pc_logging.info("Installing OpenSCAD...")
            result = subprocess.run(["sudo", "apt-get", "install", "-y", "openscad"], check=True, capture_output=True)

            if result.returncode != 0:
                pc_logging.error("OpenSCAD installation failed.")
                pc_logging.debug(result.stderr)
                return False

            pc_logging.info("OpenSCAD installation completed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            pc_logging.error("OpenSCAD installation failed.")
            pc_logging.debug(e)
        except Exception as e:
            pc_logging.exception("Unexpected error during OpenSCAD installation.")

        return False


class MacOpenSCADCheck(OpenSCADCheck):
    def __init__(self):
        super().__init__()

    def is_applicable(self) -> bool:
        return platform.system().lower() == "darwin"

    def fix(self) -> bool:
        """Attempt to install OpenSCAD using Homebrew."""
        env = os.environ.copy()
        env["HOMEBREW_NO_AUTO_UPDATE"] = "1"

        install_cmd = ["brew", "install", "-f", "openscad"]
        cache_dir = Path.home() / "Library" / "Caches" / "Homebrew" / "downloads"

        try:
            pc_logging.info("Attempting to install OpenSCAD via Homebrew...")
            if cache_dir.exists():
                for file in cache_dir.glob("*openscad*.dmg"):
                    try:
                        file.unlink(missing_ok=True)
                        pc_logging.debug(f"Deleted cached file: {file}")
                    except Exception as unlink_error:
                        pc_logging.warning(f"Could not delete {file}: {unlink_error}")

            result = subprocess.run(install_cmd, check=True, env=env, capture_output=True)

            if result.returncode != 0:
                pc_logging.error("OpenSCAD installation failed.")
                pc_logging.debug(result.stderr)
                return False

            return True
        except subprocess.CalledProcessError as error:
            pc_logging.error("OpenSCAD installation failed.")
            pc_logging.debug(error)
        return False


class WindowsOpenSCADCheck(OpenSCADCheck):
    def __init__(self):
        super().__init__()
        self.installation_path = os.path.join(UserConfig.get_config_dir(), "OpenSCAD")
        self.openscad_zip_url = "https://files.openscad.org/OpenSCAD-2021.01-x86-64.zip"
        self.openscad_zip_sha256_url = f"{self.openscad_zip_url}.sha256"
        self.openscad_zip_path = os.path.join(UserConfig.get_config_dir(), "openscad.zip")
        self.openscad_zip_sha256_path = os.path.join(UserConfig.get_config_dir(), "openscad.zip.sha256")

    @property
    def executable_path(self):
        return os.path.join(self.installation_path, "openscad-2021.01")

    def is_applicable(self) -> bool:
        return platform.system() == "Windows"

    @staticmethod
    def add_to_user_path(dir_path: str):
        """Add the given directory to the user's PATH environment variable (permanently)."""
        try:
            resolved_path = Path(dir_path).resolve(strict=True)
            if not resolved_path.is_dir():
                pc_logging.error(f"Provided path exists but is not a directory: {resolved_path}")
                return
        except FileNotFoundError:
            pc_logging.error(f"Directory does not exist: {dir_path}")
            return
        except Exception as e:
            pc_logging.exception(f"Failed to resolve path '{dir_path}': {e}")
            return

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS) as key:
                try:
                    current_path, _ = winreg.QueryValueEx(key, "PATH")
                except FileNotFoundError:
                    current_path = ""

                paths = current_path.split(";") if current_path else []
                resolved_str = str(resolved_path)
                if resolved_str not in paths:
                    new_path = ";".join(paths + [resolved_str])
                    winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
                    pc_logging.info(f"Added '{resolved_str}' to user PATH.")
                    pc_logging.info("You may need to restart your PowerShell session or log out and back in for changes to take effect.")
                else:
                    pc_logging.info(f"'{resolved_str}' is already in the user PATH. No changes made.")
                return True
        except PermissionError:
            pc_logging.error("Permission denied while accessing the Windows Registry. Try running as administrator.")
        except OSError as e:
            pc_logging.exception(f"Failed to modify PATH in registry: {e}")
        except Exception as e:
            pc_logging.exception(f"Unexpected error occurred: {e}")

        return False


    def fix(self) -> bool:
        pc_logging.info(f"Downloading OpenSCAD in '{self.installation_path}'...")
        try:
            urllib.request.urlretrieve(self.openscad_zip_url, self.openscad_zip_path)
            urllib.request.urlretrieve(self.openscad_zip_sha256_url, self.openscad_zip_sha256_path)
        except urllib.error.URLError as e:
            pc_logging.error(f"Failed to download OpenSCAD.")
            pc_logging.debug(str(e))
            return False

        # Read expected checksum
        try:
            with open(self.openscad_zip_sha256_path, "r") as f:
                expected = f.read().strip().split()[0]
        except FileNotFoundError:
            pc_logging.error(f"SHA256 checksum file '{self.openscad_zip_sha256_path}' not found")
            return False
        except Exception as e:
            pc_logging.error(f"Error reading SHA256 checksum file.")
            pc_logging.debug(str(e))
            return False

        # Compute actual checksum
        try:
            h = hashlib.sha256()
            with open(self.openscad_zip_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            actual = h.hexdigest()
        except Exception as e:
            pc_logging.error(f"Error computing SHA256 checksum")
            pc_logging.debug(str(e))
            return False

        if actual != expected:
            pc_logging.error(f"SHA256 mismatch: expected {expected}, got {actual}")
            return False

        # unpack
        try:
            with zipfile.ZipFile(self.openscad_zip_path, "r") as z:
                z.extractall(self.installation_path)
        except zipfile.BadZipfile as e:
            pc_logging.error(f"Failed to unpack OpenSCAD package.")
            pc_logging.debug(str(e))
            return False
        except Exception as e:
            pc_logging.error(f"Error unpacking OpenSCAD package.")
            pc_logging.debug(str(e))
            return False

        pc_logging.info(f"OpenSCAD installed to '{self.installation_path}'")
        success = self.add_to_user_path(self.installation_path)
        if not success:
            pc_logging.warning(f"Please add '{self.installation_path}' to your PATH to use OpenSCAD.")
        return True
