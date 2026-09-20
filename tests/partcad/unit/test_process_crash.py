#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json
import os
import signal

from partcad import process_crash


def test_killed_by_signal_only_for_a_signal():
    assert process_crash.killed_by_signal(-int(signal.SIGSEGV))
    assert process_crash.killed_by_signal(3221225477)
    assert not process_crash.killed_by_signal(0)
    assert not process_crash.killed_by_signal(1)
    assert not process_crash.killed_by_signal(None)


def test_command_failure_names_the_signal_rather_than_the_number():
    message = process_crash.command_failure(["/sandbox/python", "wrapper_export.py"], -int(signal.SIGSEGV))
    assert "wrapper_export.py" in message
    # The whole point: a negative exit code is a death by signal, and it says so
    assert "killed by signal 11 (SIGSEGV)" in message
    assert "-11" not in message


def test_command_failure_leaves_an_ordinary_failure_alone():
    assert (
        process_crash.command_failure(["/sandbox/python"], 2)
        == "Failed to execute command '/sandbox/python': exit code 2"
    )


def test_describe_termination_is_only_for_a_crash():
    # An interpreter that exited with a traceback is not a native crash, and
    # there is nothing here to add to what it already said
    assert process_crash.describe_termination(["/sandbox/python"], 1) is None
    assert process_crash.describe_termination(["/sandbox/python"], 0) is None


def test_describe_termination_names_the_signal_and_the_sandbox():
    message = process_crash.describe_termination(
        ["/sandbox/python", "wrapper_export.py"],
        -int(signal.SIGSEGV),
        pid=0,
        where="/sandbox",
    )
    assert "killed by signal 11 (SIGSEGV)" in message
    assert "wrapper_export.py" in message
    assert "/sandbox" in message


def test_describe_termination_guesses_nothing_when_the_wrapper_spoke():
    # A wrapper that printed a traceback has already said more than a guess
    # would; all that is missing is that it was killed rather than that it failed
    message = process_crash.describe_termination(
        ["/sandbox/python"], -int(signal.SIGSEGV), pid=0, where="/sandbox", silent=False
    )
    assert "killed by signal 11 (SIGSEGV)" in message
    assert "cadquery-ocp" not in message


def _write_report(directory, name, pid):
    """A file shaped like a macOS .ips crash report: a header line, then the report."""
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(json.dumps({"app_name": "python3.11"}) + "\n")
        f.write(json.dumps({"pid": pid, "procName": "python3.11"}))
    return path


def test_crash_report_is_found_by_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(process_crash.sys, "platform", "darwin")
    monkeypatch.setattr(process_crash, "CRASH_REPORT_DIR", str(tmp_path))
    _write_report(str(tmp_path), "python3.11-2026-01-01-000000.ips", 1111)
    wanted = _write_report(str(tmp_path), "python3.11-2026-01-01-000001.ips", 2222)

    # Matched on the pid inside the report, not on the name: every sandbox
    # interpreter on the machine is called the same thing
    assert process_crash.crash_report(2222, timeout=0) == wanted
    assert process_crash.crash_report(3333, timeout=0) is None


def test_crash_report_is_named_in_the_message(tmp_path, monkeypatch):
    monkeypatch.setattr(process_crash.sys, "platform", "darwin")
    monkeypatch.setattr(process_crash, "CRASH_REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(process_crash, "CRASH_REPORT_TIMEOUT", 0)
    report = _write_report(str(tmp_path), "python3.11-2026-01-01-000000.ips", 4242)

    message = process_crash.describe_termination(["/sandbox/python"], -int(signal.SIGSEGV), pid=4242)
    assert report in message


def test_crash_report_ignores_one_an_earlier_run_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(process_crash.sys, "platform", "darwin")
    monkeypatch.setattr(process_crash, "CRASH_REPORT_DIR", str(tmp_path))
    report = _write_report(str(tmp_path), "python3.11-2026-01-01-000000.ips", 4242)
    os.utime(report, (1_000_000, 1_000_000))

    assert process_crash.crash_report(4242, since=2_000_000, timeout=0) is None
    assert process_crash.crash_report(4242, since=500_000, timeout=0) == report


def test_crash_report_is_never_looked_for_off_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(process_crash.sys, "platform", "linux")
    monkeypatch.setattr(process_crash, "CRASH_REPORT_DIR", str(tmp_path))
    _write_report(str(tmp_path), "python3.11-2026-01-01-000000.ips", 4242)

    assert process_crash.crash_report(4242, timeout=0) is None


def test_a_broken_report_does_not_break_the_failure_it_explains(tmp_path, monkeypatch):
    monkeypatch.setattr(process_crash.sys, "platform", "darwin")
    monkeypatch.setattr(process_crash, "CRASH_REPORT_DIR", str(tmp_path))
    with open(os.path.join(str(tmp_path), "python3.11-2026-01-01-000000.ips"), "w") as f:
        f.write("not json at all")

    assert process_crash.crash_report(4242, timeout=0) is None


def test_describe_termination_does_not_blame_the_sandbox_for_a_kill(tmp_path, monkeypatch):
    # An out-of-memory kill is not a crash: there is no report to look for, and
    # nothing about the sandbox's own build to suspect
    monkeypatch.setattr(process_crash, "crash_report", lambda *a, **k: "SHOULD NOT BE LOOKED FOR")
    message = process_crash.describe_termination(["/sandbox/python"], -int(signal.SIGKILL), pid=1, where="/sandbox")
    assert "killed by signal 9 (SIGKILL)" in message
    assert "cadquery-ocp" not in message
    assert "SHOULD NOT BE LOOKED FOR" not in message
    assert "out-of-memory" in message


def test_describe_termination_says_only_what_it_knows_about_sigterm():
    monkeypatch_free = process_crash.describe_termination(["/sandbox/python"], -int(signal.SIGTERM))
    assert monkeypatch_free == "/sandbox/python was killed by signal 15 (SIGTERM)."
