#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import re

import check_install_paths
import jsonc
from check_install_paths import INSTALL_LOCATIONS, MAX_DIRECTORY, MAX_FILE

from conftest import COMPONENT_ROOT

PER_USER = INSTALL_LOCATIONS["for one user"]
# What is left of MAX_PATH below the longer of the two installation
# directories, and its separator.
BUDGET = MAX_FILE - len(PER_USER) - 1


def add_file(root, relative):
    path = root.joinpath(*relative.split("\\"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def deep_file(length, extension="ms-python.python-2026.10.0-win32-x64"):
    """A path `length` characters long below the application, in an extension's directory."""
    head = f"resources\\app\\extensions\\{extension}\\"
    # Directories of 40 characters, so that no one of them is over a file
    # system's 255, and the file name making up the rest.
    remainder = length - len(head)
    parts = []
    while remainder > 60:
        parts.append("d" * 40)
        remainder -= 41
    parts.append("f" * remainder)
    path = head + "\\".join(parts)
    assert len(path) == length
    return path


def test_the_longer_location_is_the_one_for_one_user():
    # Which is why the budget above is measured from it.
    assert len(PER_USER) > len(INSTALL_LOCATIONS["for all users"])
    assert len(PER_USER) == len("C:\\Users\\") + 20 + len("\\AppData\\Local\\PartCAD IDE")


def test_an_application_that_fits_passes(tmp_path, capsys):
    add_file(tmp_path, deep_file(BUDGET))

    assert check_install_paths.main(["--root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert f"deepest file for one user: {MAX_FILE} of {MAX_FILE} characters, 0 to spare" in output
    assert "(extension ms-python.python-2026.10.0-win32-x64)" in output


def test_one_character_over_fails_and_names_the_file_and_its_extension(tmp_path, capsys):
    # 2026.10.0 of the Python extension, exactly: its deepest file is the same
    # file as 2026.4.0's, which is exactly at the limit, in a directory one
    # character longer for the extra digit in the version.
    path = deep_file(BUDGET + 1)
    add_file(tmp_path, path)

    assert check_install_paths.main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert f"{MAX_FILE + 1} characters for one user, over {MAX_FILE}: {PER_USER}\\{path}" in output
    assert "(extension ms-python.python-2026.10.0-win32-x64)" in output
    assert '"version" in extensions.json' in output


def test_a_directory_is_held_to_the_shorter_limit(tmp_path, capsys):
    # A directory deep enough that CreateDirectory refuses it, holding a file
    # short enough to be within MAX_PATH -- were the directory there.
    directory = deep_file(MAX_DIRECTORY - len(PER_USER))
    add_file(tmp_path, directory + "\\x")

    assert check_install_paths.main(["--root", str(tmp_path)]) == 1
    assert f"{MAX_DIRECTORY + 1} characters for one user, over {MAX_DIRECTORY}" in capsys.readouterr().out


def test_another_location_is_checked_too(tmp_path, capsys):
    # The directory the compiler reads the application from, which build.sh
    # passes: the compiler is not long-path aware either.
    add_file(tmp_path, deep_file(100))
    build = "D:\\" + "b" * (MAX_FILE - 100)

    assert check_install_paths.main(["--root", str(tmp_path), "--location", build]) == 1
    assert f"characters in {build}, over {MAX_FILE}" in capsys.readouterr().out


def test_only_the_first_few_are_named(tmp_path, capsys):
    for index in range(check_install_paths.SHOWN + 3):
        add_file(tmp_path, deep_file(BUDGET + 1, extension=f"a.b{index:02d}-1.0.0"))

    assert check_install_paths.main(["--root", str(tmp_path)]) == 1
    assert "... and 3 more for one user" in capsys.readouterr().out


def test_a_missing_application_is_an_error(tmp_path):
    assert check_install_paths.main(["--root", str(tmp_path / "missing")]) == 2


def test_the_locations_are_the_ones_the_installer_uses():
    # The check is only as good as its idea of where Setup puts the
    # application, and that is decided in the .iss.
    script = (COMPONENT_ROOT / "installer" / "partcad-ide.iss").read_text(encoding="utf-8")
    assert re.search(r"^DefaultDirName=\{code:DefaultAppDir\}$", script, re.MULTILINE)
    (function,) = re.findall(r"function DefaultAppDir\(.*?\nend;", script, re.DOTALL)
    assert "ExpandConstant('{commonpf}\\{#AppName}')" in function
    assert "ExpandConstant('{localappdata}\\{#AppName}')" in function
    assert re.search(r'^#define AppName "PartCAD IDE"$', script, re.MULTILINE)
    assert check_install_paths.APP_NAME == "PartCAD IDE"


def test_the_shipped_hold_on_the_python_extension_says_why():
    # The hold this check exists to explain: lifting it without running the
    # check is how the installer broke.
    policy = jsonc.loads((COMPONENT_ROOT / "extensions.json").read_text(encoding="utf-8"))
    entry = policy["extra"]["ms-python.python"]
    assert entry["version"] == "2026.4.0"
    assert "Windows installer" in entry["reason"]
