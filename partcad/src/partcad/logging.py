#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-02-04
#
# Licensed under Apache License, Version 2.0.

import logging
from logging import DEBUG, INFO, WARN, WARNING, ERROR, CRITICAL
import threading
import time

import sentry_sdk

from opentelemetry import trace
from . import telemetry


# Track if any errors occurred during the execution for test purposes and for
# the main program to know if it should exit with an error code.
had_errors = False

# Other packages (such as 'pip' or 'pytest') may mess with the root logger
# in a way that we don't want. We create a separate logger for our own use.
# For example, 'pip' sets up a filter that drops 'extra's from log records,
# thus turning 'process_start' and 'process_end' into regular error messages.
logging.getLogger("partcad").propagate = False

# Wrap the logger to make it easier to use
setLevel = lambda *a, **kw: logging.getLogger("partcad").setLevel(*a, **kw)
getLevel = lambda: logging.getLogger("partcad").level
log = lambda *a, **kw: logging.getLogger("partcad").log(*a, **kw)
debug = lambda *a, **kw: logging.getLogger("partcad").debug(*a, **kw)
info = lambda *a, **kw: logging.getLogger("partcad").info(*a, **kw)
warn = lambda *a, **kw: logging.getLogger("partcad").warn(*a, **kw)
warning = lambda *a, **kw: logging.getLogger("partcad").warning(*a, **kw)


def reset_errors():
    """
    Reset the error tracking.

    This should be called before running a new test. This function modifies a global variable and should be called
    with appropriate thread safety considerations.
    """
    global had_errors
    had_errors = False


# TODO(clairbee): replace this with some kind of a hook, so that it can be handled differently in CLI and IDE, and ignored in backend jobs
def _track_error(args):
    global had_errors
    if args and len(args) > 1:
        if "conda run pythonw" in args[0]:
            return
    had_errors = True


def error(*args, **kwargs):
    _track_error(args)
    logging.getLogger("partcad").error(*args, **kwargs)
    sentry_sdk.capture_message(str(args) + str(kwargs), level="error")
    current_span = trace.get_current_span()
    if current_span:
        current_span.set_status(trace.Status(trace.StatusCode.ERROR, str(args)))


def critical(*args, **kwargs):
    logging.getLogger("partcad").critical(*args, **kwargs)
    sentry_sdk.capture_message(str(args) + str(kwargs), level="debug")


# Some pytest versions/configurations/plugins mess with the exception method
# so lambdas don't work
def exception(
    *args,
):
    _track_error(args)
    logging.getLogger("partcad").exception(*args)
    sentry_sdk.capture_exception(args[0])


# Create 'ops' that are used for dependency injection of the logic to control
# the logging context (e.g. the current state of processes and actions).
def default_process_start(self_ops, op: str, package: str, item: str | None = None):
    if item is None:
        debug("Starting process: %s: %s" % (op, package))
    else:
        debug("Starting process: %s: %s: %s" % (op, package, item))


def default_process_end(self_ops, op: str, package: str, item: str = None):
    pass


def default_action_start(self_ops, op: str, package: str, item: str | None = None):
    if item is None:
        debug("Starting action: %s: %s" % (op, package))
    else:
        debug("Starting action: %s: %s: %s" % (op, package, item))


def default_action_end(self_ops, op: str, package: str, item: str = None):
    if item is None:
        debug("Finished action: %s: %s" % (op, package))
    else:
        debug("Finished action: %s: %s: %s" % (op, package, item))


# Dependency injection point for logging plugins
class Ops:
    process_start = default_process_start
    process_end = default_process_end
    action_start = default_action_start
    action_end = default_action_end


ops = Ops()


# Only one 'process' at a time, no recursion
process_lock = threading.Lock()

process_transaction = None
process_span = None


# Classes to be used with "with()" to alter the logging context.
class Process(object):
    def __init__(
        self,
        op: str,
        package: str,
        item: str = None,
    ):
        self.op = op
        self.package = package
        self.item = item
        self.succeeded = False
        self.start = 0.0
        self.span_ctx_mgr = None

    async def __aenter__(self):
        self.__enter__()

    def __enter__(self):
        global process_lock
        global process_transaction
        global process_span

        if process_lock.acquire():
            self.start = time.time()
            attributes = {
                "package": self.package,
            }
            if self.item:
                attributes["item"] = self.item

            self.span_ctx_mgr = telemetry.start_as_current_span(
                f"Process: {self.op}",
                attributes=attributes,
            )
            self.span_ctx_mgr.__enter__()
            ops.process_start(self.op, self.package, self.item)
            self.succeeded = True
        else:
            error("Nested process is detected. Status reporting is invalid.")
            self.succeeded = False

    async def __aexit__(self, *args):
        self.__exit__(*args)

    def __exit__(self, *_args):
        global process_lock
        global info

        if self.succeeded:
            process_lock.release()
            ops.process_end(self.op, self.package, self.item)
            self.span_ctx_mgr.__exit__(*_args)
            delta = time.time() - self.start
            if self.item is None:
                info("DONE: %s: %s: %.2fs" % (self.op, self.package, delta))
            else:
                info("DONE: %s: %s: %s: %.2fs" % (self.op, self.package, self.item, delta))


class Action(object):
    def __init__(
        self,
        op: str,
        package: str,
        item: str = None,
        extra: str = None,
    ):
        self.op = op
        self.package = package
        self.span_ctx_mgr = None

        if extra:
            self.item = item + " : " + extra
        else:
            self.item = item

    async def __aenter__(self):
        self.__enter__()

    def __enter__(self):
        attributes = {
            "package": self.package,
        }
        if self.item:
            attributes["item"] = self.item

        self.span_ctx_mgr = telemetry.start_as_current_span(
            f"Action: {self.op}",
            attributes=attributes,
        )
        self.span_ctx_mgr.__enter__()
        ops.action_start(self.op, self.package, self.item)

    async def __aexit__(self, *args):
        self.__exit__(*args)

    def __exit__(self, *args):
        ops.action_end(self.op, self.package, self.item)
        self.span_ctx_mgr.__exit__(*args)
