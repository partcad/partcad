#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the client-side remote logging backend (partcad_utils).

A thin client (the CLI) receives the structured events the daemon forwards and
replays them locally: as plain lines under --no-ansi, or through
:mod:`partcad_utils.logging_ansi_terminal` (colours + progress footer) when ANSI
is wanted.
"""

import datetime
import io
import logging
import re
from unittest import mock

import partcad_utils.logging as pc_logging
import partcad_utils.logging_remote_client as remote_client


def teardown_function():
    remote_client.fini()


def test_plain_log_event_written_to_stream():
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)

    remote_client.handle({"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "hello client"})

    assert "hello client" in buf.getvalue()


def test_plain_mode_ignores_process_events():
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)

    remote_client.handle({"kind": "process_start", "op": "build", "package": "//pkg", "item": None})

    assert buf.getvalue() == ""


def test_ansi_mode_initializes_and_finalizes_ansi_terminal():
    buf = io.StringIO()
    with (
        mock.patch.object(remote_client.logging_ansi_terminal, "init") as m_init,
        mock.patch.object(remote_client.logging_ansi_terminal, "fini") as m_fini,
    ):
        remote_client.init(want_ansi=True, stream=buf)
        m_init.assert_called_once()

        remote_client.fini()
        m_fini.assert_called_once()


def test_ansi_process_event_replayed_through_ops():
    buf = io.StringIO()
    remote_client.init(want_ansi=True, stream=buf)
    try:
        with mock.patch.object(pc_logging.ops, "process_start") as m:
            remote_client.handle({"kind": "process_start", "op": "build", "package": "//pkg", "item": "x"})
            m.assert_called_once_with("build", "//pkg", "x")
    finally:
        remote_client.fini()


def test_an_error_forwarded_from_the_daemon_is_recorded_for_the_exit():
    """Most of the work runs in the daemon, so most errors arrive this way.

    The flag was already mirrored here; without the message beside it, a
    command whose only error came from the daemon still exited over an error it
    could not name.
    """
    pc_logging.reset_errors()

    remote_client.handle(
        {"kind": "log", "levelno": logging.ERROR, "message": "conda env install error: netlink descriptor 9"}
    )

    assert pc_logging.had_errors is True
    assert "netlink descriptor 9" in pc_logging.first_error


# ---- plain mode is a log you can time ----------------------------------------

_PLAIN_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3})Z (INFO|WARNING|ERROR):partcad:(.*)$")


def _lines(buf):
    return buf.getvalue().splitlines()


def test_a_plain_line_leads_with_the_utc_time_of_the_event():
    """The daemon's time, not the moment the client got round to printing it."""
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)
    # 2026-10-02T14:31:01.816Z, whatever the local time zone of this machine.
    created = datetime.datetime(2026, 10, 2, 14, 31, 1, 816000, tzinfo=datetime.timezone.utc).timestamp()

    remote_client.handle({"kind": "log", "levelno": logging.WARNING, "message": "a stamped line", "created": created})

    assert _lines(buf) == ["2026-10-02T14:31:01.816Z WARNING:partcad:a stamped line"]


def test_an_event_from_an_older_daemon_is_stamped_when_it_arrives():
    """A daemon from before 'created' was sent still gets a time on its lines."""
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)

    before = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    remote_client.handle({"kind": "log", "levelno": logging.INFO, "message": "no time sent"})
    after = datetime.datetime.now(datetime.timezone.utc)

    (line,) = _lines(buf)
    match = _PLAIN_LINE.match(line)
    assert match and match.group(2, 3) == ("INFO", "no time sent"), line
    stamp = datetime.datetime.fromisoformat(match.group(1)).replace(tzinfo=datetime.timezone.utc)
    assert before <= stamp <= after


def test_a_record_below_the_level_is_not_rendered():
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)
    logging.getLogger("partcad").setLevel(logging.INFO)

    remote_client.handle({"kind": "log", "levelno": logging.DEBUG, "message": "quiet", "created": 0.0})

    assert buf.getvalue() == ""


def test_plain_mode_still_drops_action_markers():
    """The daemon logs a DONE line when an action ends; the markers themselves
    only drive the ANSI footer, so plain mode adds no line for them."""
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)

    remote_client.handle({"kind": "action_start", "op": "Test", "package": "//pkg", "item": None})
    remote_client.handle({"kind": "action_end", "op": "Test", "package": "//pkg", "item": None})

    assert buf.getvalue() == ""
