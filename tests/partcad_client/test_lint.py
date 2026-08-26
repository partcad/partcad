#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the client-side file check (`partcad_client.lint`).

What is pinned here is the *client* half: which files get checked at all, where
their content comes from (the disk, or a buffer an editor has not saved), and
the shape the answer comes back in. The checking itself belongs to
``partcad_utils.assy_lint`` and is covered by that package's tests.
"""

import pytest

from partcad_client import lint


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_a_clean_assy_file_reports_nothing(tmp_path):
    report = lint.check_file(write(tmp_path, "logo.assy", "links:\n  - part: cube\n"))
    assert report.checked is True
    assert report.diagnostics == []
    assert report.failed is False


def test_a_broken_assy_file_is_reported_with_positions(tmp_path):
    path = write(tmp_path, "logo.assy", "links:\n  - part: cube\n    location: [0, 0, 0]\n")
    report = lint.check_file(path)
    assert report.failed is True
    assert all(d.line == 2 for d in report.diagnostics)


def test_the_supplied_buffer_wins_over_the_file_on_disk(tmp_path):
    # The point of the whole arrangement: an editor checks what is on screen,
    # which is why this never became a request to a daemon that can only see
    # what was saved.
    path = write(tmp_path, "logo.assy", "links:\n  - part: cube\n")
    assert lint.check_file(path).diagnostics == []
    edited = lint.check_file(path, "links:\n  - part: cube\n    locaton: 1\n")
    assert [d.message for d in edited.diagnostics] == ["unexpected property 'locaton'"]


def test_a_file_type_with_no_checks_is_not_reported_as_clean(tmp_path):
    report = lint.check_file(write(tmp_path, "notes.txt", "not an assembly"))
    assert report.checked is False
    assert report.diagnostics == []
    assert report.failed is False


def test_a_missing_file_raises(tmp_path):
    # A caller that named a file it cannot open wants to hear about it, rather
    # than get an empty (and therefore reassuring) report back.
    with pytest.raises(OSError):
        lint.check_file(str(tmp_path / "gone.assy"))


def test_a_missing_file_is_fine_when_the_content_is_supplied(tmp_path):
    # An editor can check a buffer for a file that was never saved.
    report = lint.check_file(str(tmp_path / "untitled.assy"), "links:\n  - part: cube\n")
    assert report.checked is True
    assert report.diagnostics == []


def test_paths_come_back_exactly_as_they_went_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "logo.assy", "links:\n  - part: cube\n")
    assert [report.path for report in lint.check_files(["logo.assy"])] == ["logo.assy"]


def test_check_files_reports_every_path(tmp_path):
    paths = [
        write(tmp_path, "a.assy", "links:\n  - part: cube\n"),
        write(tmp_path, "b.assy", "links:\n  - part: cube\n    locaton: 1\n"),
    ]
    reports = lint.check_files(paths)
    assert [report.path for report in reports] == paths
    assert [len(report.diagnostics) for report in reports] == [0, 1]


def test_supplied_content_needs_exactly_one_file(tmp_path):
    with pytest.raises(ValueError):
        lint.check_files(["a.assy", "b.assy"], "links:\n")


def test_report_serializes_for_a_json_consumer(tmp_path):
    path = write(tmp_path, "logo.assy", "links:\n  - part: cube\n    locaton: 1\n")
    payload = lint.check_file(path).to_dict()
    assert payload["path"] == path
    assert payload["checked"] is True
    finding = payload["diagnostics"][0]
    assert finding["severity"] == "warning"
    assert (finding["line"], finding["column"]) == (2, 4)
    assert finding["source"] == "partcad"
