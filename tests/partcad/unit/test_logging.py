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
    with (
        mock.patch("partcad.logging.sentry_sdk.capture_message") as capture_message,
        mock.patch("partcad.logging.sentry_sdk.capture_exception") as capture_exception,
    ):
        pc_logging.exception("a plain string, not an exception")

    capture_message.assert_called_once_with("a plain string, not an exception", level="error")
    capture_exception.assert_not_called()


def test_exception_with_exception_object_dispatches_capture_exception():
    """An actual exception object must go to capture_exception unchanged."""
    err = ValueError("boom")
    with (
        mock.patch("partcad.logging.sentry_sdk.capture_message") as capture_message,
        mock.patch("partcad.logging.sentry_sdk.capture_exception") as capture_exception,
    ):
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
    with (
        mock.patch("partcad.logging.sentry_sdk.capture_message") as capture_message,
        mock.patch("partcad.logging.sentry_sdk.capture_exception") as capture_exception,
    ):
        pc_logging.exception("formatted %s", 42)

    # Raw format string reaches Sentry; the 42 argument is not substituted.
    capture_message.assert_called_once_with("formatted %s", level="error")
    capture_exception.assert_not_called()


# `had_errors` is what turns into the CLI's exit status, and it is read at the
# very end of a command -- long after the error that set it scrolled past, and
# in the case that started this, after the run recovered from that error and
# finished all of its work successfully. `first_error` is what lets the exit say
# which error it is exiting over instead of click's bare "Aborted.".


def test_the_first_error_is_kept_so_the_exit_can_name_it():
    pc_logging.reset_errors()

    pc_logging.error("conda env install error: netlink descriptor 9")

    assert pc_logging.had_errors is True
    assert "netlink descriptor 9" in pc_logging.first_error


def test_only_the_first_error_is_kept():
    """Later errors are usually consequences of the first one.

    The conda failure that prompted this logged two: the create that glibc
    killed, and then "Not a conda environment" from the pip install that was
    handed the prefix the create never made. The second names the symptom.
    """
    pc_logging.reset_errors()

    pc_logging.error("the cause")
    pc_logging.error("the consequence")

    assert pc_logging.first_error == "the cause"


def test_a_lazily_formatted_error_is_rendered():
    """Callers use both the pre-formatted and the stdlib's deferred style."""
    pc_logging.reset_errors()

    pc_logging.error("conda pip install return code: %s", 1)

    assert pc_logging.first_error == "conda pip install return code: 1"


def test_a_message_that_cannot_be_rendered_falls_back_to_the_format_string():
    """Recording the message must never be the thing that fails.

    Tested against the renderer rather than through error(): the stdlib logger
    raises on a mismatched format of its own accord, which is behaviour that
    predates this and is not what is being guarded here.
    """
    assert pc_logging._rendered(("%s and %s", "only one")) == "%s and %s"
    assert pc_logging._rendered(()) is None


def test_reset_errors_clears_the_recorded_error():
    """The conftest fixture resets between tests; both halves must reset."""
    pc_logging.error("something")
    assert pc_logging.first_error is not None

    pc_logging.reset_errors()

    assert pc_logging.had_errors is False
    assert pc_logging.first_error is None
