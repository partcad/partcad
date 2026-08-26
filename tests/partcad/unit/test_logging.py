#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from unittest import mock

import partcad.logging as pc_logging


# All tests patch ``partcad.logging.sentry_sdk.capture_message`` and
# ``partcad.logging.sentry_sdk.capture_exception`` directly. This makes the
# assertions independent of whether a real Sentry backend is configured: even
# when Sentry is disabled (and the real functions are no-ops), the mocks still
# record exactly which API was invoked and with what arguments. Asserting the
# dispatch -- not merely the absence of a crash -- is what catches a regression
# back to the wrong Sentry API (e.g. forwarding a string to capture_exception).


def test_exception_with_plain_string_dispatches_capture_message():
    """A preformatted string must go to capture_message, not capture_exception.

    Several callers log an already-stringified error (e.g. a wrapper's error
    text) via exception(). Sentry's capture_exception rejects a non-exception,
    which used to turn the logging call itself into a ValueError. The string
    must be routed to capture_message(..., level="error") instead.
    """
    with mock.patch("partcad.logging.sentry_sdk.capture_message") as capture_message, \
         mock.patch("partcad.logging.sentry_sdk.capture_exception") as capture_exception:
        pc_logging.exception("a plain string, not an exception")

    capture_message.assert_called_once_with("a plain string, not an exception", level="error")
    capture_exception.assert_not_called()


def test_exception_with_exception_object_dispatches_capture_exception():
    """An actual exception object must go to capture_exception unchanged."""
    err = ValueError("boom")
    with mock.patch("partcad.logging.sentry_sdk.capture_message") as capture_message, \
         mock.patch("partcad.logging.sentry_sdk.capture_exception") as capture_exception:
        try:
            raise err
        except ValueError as e:
            pc_logging.exception(e)

    capture_exception.assert_called_once_with(err)
    capture_message.assert_not_called()


def test_exception_with_format_string_and_arg_dispatches_capture_message():
    """exception("formatted %s", 42) -- a format string plus an argument.

    This is how logging is normally called. exception() only inspects args[0]
    to decide the Sentry route: args[0] ("formatted %s") is not a BaseException,
    so it is dispatched to capture_message(..., level="error").

    Observed current behavior (see report):
      - the stdlib logger records the *formatted* message "formatted 42";
      - Sentry's capture_message receives the *raw* format string "formatted %s"
        -- args[1] (42) is NOT applied.
      - capture_exception is not called.

    So we assert the raw, unformatted string is what reaches Sentry, matching
    the code as written. NOTE: the logger ("formatted 42") and Sentry
    ("formatted %s") disagree; the %-args are dropped from the Sentry message.
    This is flagged in the report as a real, if minor, discrepancy rather than
    being papered over -- the assertion pins the current behavior so a future
    change to it is visible.
    """
    with mock.patch("partcad.logging.sentry_sdk.capture_message") as capture_message, \
         mock.patch("partcad.logging.sentry_sdk.capture_exception") as capture_exception:
        pc_logging.exception("formatted %s", 42)

    # Raw format string reaches Sentry; the 42 argument is not substituted.
    capture_message.assert_called_once_with("formatted %s", level="error")
    capture_exception.assert_not_called()
