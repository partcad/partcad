#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import partcad.logging as pc_logging


def test_exception_accepts_a_string():
    """pc_logging.exception() must tolerate a preformatted string.

    Several callers log an already-stringified error (e.g. a wrapper's error
    text) via exception(). Sentry's capture_exception rejects a non-exception,
    which used to turn the logging call itself into a ValueError. This must not
    happen.
    """
    pc_logging.exception("a plain string, not an exception")
    pc_logging.exception("formatted %s" % 42)


def test_exception_accepts_an_exception():
    """An actual exception object is still accepted."""
    try:
        raise ValueError("boom")
    except ValueError as e:
        pc_logging.exception(e)
