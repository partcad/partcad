#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Cancelling a request: the flag ``$/cancelRequest`` sets, and the points that look at it.

A client that has stopped wanting an answer says so with ``$/cancelRequest``,
the notification the Language Server Protocol uses and ``vscode-jsonrpc`` sends
when the token a request was made with is cancelled. The editor does that when
a newer selection makes a viewer or tab request stale; until this existed the
stale request ran to the end, its answer was thrown away on arrival, and every
request behind it waited for it.

What a cancellation does depends on where the request is:

* **Queued.** It is answered at once with :data:`REQUEST_CANCELLED` and never
  runs. Nothing about it has started, so there is nothing to undo.
* **Running.** Nothing is interrupted. A flag is set, and the operation stops at
  the next *safe point* that looks at it -- :func:`check` -- by raising
  :class:`RequestCancelled`, which is answered with :data:`REQUEST_CANCELLED`.
  A request that reaches no safe point after being cancelled finishes and is
  answered as usual, which the protocol allows: a cancellation is a hint.

Safe points are where an operation is between units of work, never inside one:
before an assembly is built (after its sub-assemblies are known to be ready),
when an object of a recursive command or a row of a table gets its turn. A
partly written render or a half-tessellated shape is never left behind by one.

The flag reaches an operation without being passed to it: the dispatcher sets
it as the request being served (a context variable) for as long as the handler
runs, so :func:`check` works from the operation's own thread and from the
coroutines it runs with ``asyncio.run`` -- each task starts with a copy of the
context it was created in. It does not reach a worker thread of a pool, which
is fine: the safe points are in the service's own operations, not in PartCAD.
"""

import contextlib
import contextvars
import threading
from typing import Optional

# LSP's RequestCancelled, which is what 'vscode-jsonrpc' and every LSP client
# expect a cancelled request to be answered with. Not one of JSON-RPC's own
# codes, which define no cancellation at all.
REQUEST_CANCELLED = -32800

# The notification a client cancels a request with, carrying ``{"id": <id>}``.
CANCEL_METHOD = "$/cancelRequest"


class RequestCancelled(BaseException):
    """Raised at a safe point of a request its client has cancelled.

    A ``BaseException``, like ``asyncio.CancelledError``: an operation that
    catches ``Exception`` to report one object's failure and carry on with the
    next -- most of them do -- must not catch this, or a cancelled table would
    report every remaining row as failed instead of stopping.
    """


class CancelToken:
    """Whether one request has been cancelled, and whether it has started.

    The two are decided together, under one lock, because the answer to a
    cancellation depends on which came first: a request still waiting is
    answered by whoever cancelled it and must then never start, while one that
    has started is only asked to stop.
    """

    _QUEUED, _RUNNING, _DROPPED = range(3)

    __slots__ = ("_lock", "_state", "_cancelled")

    def __init__(self):
        self._lock = threading.Lock()
        self._state = self._QUEUED
        self._cancelled = False

    def cancel(self) -> bool:
        """Cancel the request; True if it had not started, and now never will.

        A True answer makes the caller the one who answers the request.
        """
        with self._lock:
            self._cancelled = True
            if self._state == self._QUEUED:
                self._state = self._DROPPED
                return True
            return False

    def start(self) -> bool:
        """Claim the request for running; False if it was cancelled first."""
        with self._lock:
            if self._state != self._QUEUED:
                return False
            self._state = self._RUNNING
            return True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


_serving: contextvars.ContextVar = contextvars.ContextVar("partcad_request_cancellation", default=None)


@contextlib.contextmanager
def serving(token: Optional[CancelToken]):
    """Make ``token`` the one :func:`check` looks at, for as long as a handler runs."""
    reset = _serving.set(token)
    try:
        yield
    finally:
        _serving.reset(reset)


def cancelled() -> bool:
    """Whether the request being served has been cancelled."""
    token = _serving.get()
    return token is not None and token.cancelled


def check() -> None:
    """A safe point: stop here if the request being served has been cancelled.

    Does nothing outside a request, so an operation called directly -- by a
    test, or by the legacy adapter -- is never stopped by one.
    """
    if cancelled():
        raise RequestCancelled()


def cancelled_response(request_id, why: str = "Request cancelled") -> dict:
    """The answer to a request that was cancelled before it finished."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": REQUEST_CANCELLED, "message": why}}
