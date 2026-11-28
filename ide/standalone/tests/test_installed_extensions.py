#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json

import installed_extensions
import pytest


def add_extension(extensions_dir, publisher, name, version, platform=None):
    suffix = f"-{platform}" if platform else ""
    directory = extensions_dir / f"{publisher.lower()}.{name}-{version}{suffix}"
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(
        json.dumps({"publisher": publisher, "name": name, "version": version}), encoding="utf-8"
    )
    return directory.name


def staging(tmp_path):
    """What the editor left after the 0.10.42 build's installs, as far as this tool can see it."""
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    add_extension(extensions, "ms-python", "black-formatter", "2026.8.0", "universal")
    # Brought in as a dependency of black-formatter, then replaced by the held
    # version: out of the editor's list, still on disk.
    add_extension(extensions, "ms-python", "python", "2026.10.0", "win32-x64")
    add_extension(extensions, "ms-python", "python", "2026.4.0", "universal")
    add_extension(extensions, "PartCAD", "partcad-official", "0.10.42")
    # What the editor keeps beside the extensions; not one of them.
    (extensions / "extensions.json").write_text("[]", encoding="utf-8")
    (extensions / ".obsolete").write_text('{"ms-python.python-2026.10.0-win32-x64": true}', encoding="utf-8")
    return extensions


# As `--list-extensions --show-versions` prints it: ids as the publisher spells
# them, sorted, and on Windows each line ending in "\r\n".
LISTING = "ms-python.black-formatter@2026.8.0\r\nms-python.python@2026.4.0\r\nPartCAD.partcad-official@0.10.42\r\n"


def test_only_what_the_editor_lists_is_selected(tmp_path):
    assert installed_extensions.select(staging(tmp_path), LISTING) == [
        "ms-python.black-formatter-2026.8.0-universal",
        "ms-python.python-2026.4.0-universal",
        "partcad.partcad-official-0.10.42",
    ]


def test_the_directories_are_printed_one_per_line(tmp_path, capsys):
    extensions = staging(tmp_path)
    listed = tmp_path / "listed.txt"
    listed.write_text(LISTING, encoding="utf-8")

    assert installed_extensions.main(["--extensions", str(extensions), "--listed", str(listed)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "ms-python.black-formatter-2026.8.0-universal",
        "ms-python.python-2026.4.0-universal",
        "partcad.partcad-official-0.10.42",
    ]


def test_a_listed_extension_with_no_directory_fails(tmp_path, capsys):
    extensions = staging(tmp_path)
    listed = tmp_path / "listed.txt"
    listed.write_text(LISTING + "yzhang.markdown-all-in-one@3.6.2\n", encoding="utf-8")

    assert installed_extensions.main(["--extensions", str(extensions), "--listed", str(listed)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "yzhang.markdown-all-in-one@3.6.2 is listed as installed, and no directory holds it" in captured.err


def test_a_listed_extension_in_two_directories_fails(tmp_path):
    extensions = staging(tmp_path)
    add_extension(extensions, "ms-python", "python", "2026.4.0", "win32-x64")

    with pytest.raises(ValueError, match="ms-python.python@2026.4.0 is in more than one directory"):
        installed_extensions.select(extensions, LISTING)


def test_a_line_that_is_not_an_id_and_a_version_fails(tmp_path):
    # Read strictly: a listing in a shape this does not know is one it cannot
    # say anything about, and copying nothing would ship an IDE without them.
    with pytest.raises(ValueError, match="not `<id>@<version>`"):
        installed_extensions.select(staging(tmp_path), "Extensions installed on this machine:\n" + LISTING)


def test_blank_lines_are_ignored():
    assert installed_extensions.parse_listing("\n\nms-python.python@2026.4.0\r\n\r\n") == [
        ("ms-python.python", "2026.4.0")
    ]
