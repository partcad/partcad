#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

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
        where="/sandbox",
    )
    assert "killed by signal 11 (SIGSEGV)" in message
    assert "wrapper_export.py" in message
    assert "/sandbox" in message


def test_describe_termination_guesses_nothing_when_the_wrapper_spoke():
    # A wrapper that printed a traceback has already said more than a guess
    # would; all that is missing is that it was killed rather than that it failed
    message = process_crash.describe_termination(
        ["/sandbox/python"], -int(signal.SIGSEGV), where="/sandbox", silent=False
    )
    assert "killed by signal 11 (SIGSEGV)" in message
    assert "cadquery-ocp" not in message


def test_describe_termination_does_not_blame_the_sandbox_for_a_kill():
    # An out-of-memory kill is not a crash: there is nothing about the
    # sandbox's own build to suspect
    message = process_crash.describe_termination(["/sandbox/python"], -int(signal.SIGKILL), where="/sandbox")
    assert "killed by signal 9 (SIGKILL)" in message
    assert "cadquery-ocp" not in message
    assert "out-of-memory" in message


def test_describe_termination_says_only_what_it_knows_about_sigterm():
    monkeypatch_free = process_crash.describe_termination(["/sandbox/python"], -int(signal.SIGTERM))
    assert monkeypatch_free == "/sandbox/python was killed by signal 15 (SIGTERM)."
