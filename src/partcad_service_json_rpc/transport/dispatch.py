#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Serving requests one at a time, apart from reading them.

The session is every client's at once and is not safe to use from two threads:
the emitter has one sink, which is bound to whichever connection is being
served; the warm contexts are reloaded in place between requests; ``activate``
reloads ``partcad`` itself. So the daemon serves one request at a time, as it
always has.

What changed is *who waits*. A connection used to be served by the thread that
read it, which held the one dispatch lock for as long as its request ran -- so
nothing more was read from that client meanwhile, a ``$/cancelRequest`` sat
unread behind the very request it was about, and a client that stopped reading
its answers stalled the daemon for everybody. Now each connection's reader only
reads, and hands requests to :class:`Dispatch`, whose one thread serves them.
The reader is free to take a cancellation as it arrives (see
``core.cancellation``) and every write goes through the connection's own writer,
so serving never waits on a client.

Turns are taken **per connection**: the dispatch thread serves the oldest
request of the next connection in turn, not the oldest request of all. A client
that sends ten requests at once -- the editor, when a selection asks for several
tabs -- would otherwise put a ``pc`` command typed meanwhile behind all ten. A
connection's own requests are served in the order it sent them.
"""

import collections
import contextlib
import logging
import sys
import threading
import traceback
from typing import Callable, Optional

from ..core.cancellation import CancelToken, cancelled_response
from ..rpc.dispatcher import INTERNAL_ERROR

_logger = logging.getLogger(__name__)

# What a request still queued is told when the daemon stops before serving it.
STOPPING = "Request cancelled: the PartCAD service is stopping"


def request_id_of(request):
    """``(True, id)`` for a request that is owed an answer, ``(False, None)`` otherwise."""
    if isinstance(request, dict) and "id" in request:
        return True, request["id"]
    return False, None


class Job:
    """One request, from the moment it is read until it is answered.

    ``sink`` is bound to the session's emitter while it runs, so that what the
    request emits reaches its own client; None leaves the emitter alone (stdio,
    which binds its one sink for good). ``respond`` writes an answer and must
    not raise. ``on_finish`` runs once, when nothing more will be written for
    it -- after the answer, or once it is known there will be none.
    """

    __slots__ = ("request", "token", "sink", "_respond", "_on_finish", "_finished", "_lock")

    def __init__(self, request, sink, respond: Callable[[dict], None], on_finish: Callable[["Job"], None]):
        self.request = request
        self.token = CancelToken()
        self.sink = sink
        self._respond = respond
        self._on_finish = on_finish
        self._finished = False
        self._lock = threading.Lock()

    @property
    def owed_answer(self) -> bool:
        return request_id_of(self.request)[0]

    def respond(self, response: Optional[dict]) -> None:
        if response is not None:
            self._respond(response)

    def finish(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._on_finish(self)

    def drop(self, why: Optional[str] = None) -> bool:
        """Cancel it; if it had not started, answer it with ``why`` (unless None) and finish it.

        True when it had not started. A running request is only flagged, and is
        finished by whoever is running it.
        """
        if not self.token.cancel():
            return False
        owed, request_id = request_id_of(self.request)
        if owed and why is not None:
            self.respond(cancelled_response(request_id, why))
        self.finish()
        return True


class Requests:
    """One connection's requests that are queued or running.

    What ``$/cancelRequest`` looks a request up in, by its id, and what a
    connection waits on before it is closed, so that what its client asked for
    is answered even after the client has stopped sending.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._jobs: set = set()
        self._by_id: dict = {}

    def track(self, job: Job) -> None:
        owed, request_id = request_id_of(job.request)
        with self._cond:
            self._jobs.add(job)
            if owed:
                try:
                    self._by_id[request_id] = job
                except TypeError:
                    # An id JSON-RPC does not allow (an object, an array): it is
                    # still answered, it just cannot be cancelled.
                    pass

    def untrack(self, job: Job) -> None:
        owed, request_id = request_id_of(job.request)
        with self._cond:
            self._jobs.discard(job)
            if owed:
                try:
                    if self._by_id.get(request_id) is job:
                        del self._by_id[request_id]
                except TypeError:
                    pass
            self._cond.notify_all()

    def cancel(self, params) -> None:
        """Act on a ``$/cancelRequest``: answer the request now if it is still queued, or flag it.

        One that is not here -- answered already, or never sent -- is nothing to
        do: a cancellation crosses its answer on the wire all the time.
        """
        request_id = params.get("id") if isinstance(params, dict) else None
        with self._cond:
            try:
                job = self._by_id.get(request_id)
            except TypeError:
                job = None
        if job is not None:
            job.drop("Request cancelled")

    def cancel_all(self) -> None:
        """Cancel everything owed an answer: the client can no longer read one.

        Nothing is answered, since there is nobody to answer. A notification is
        left to run: its client asked for what it does, not for a reply.
        """
        with self._cond:
            owed = [job for job in self._jobs if job.owed_answer]
        for job in owed:
            job.drop(None)

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Wait until nothing is queued or running; False if ``timeout`` ran out first."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._jobs, timeout)


class Dispatch:
    """The one thread that serves requests, taking connections in turn.

    Started with the first request and ended by :meth:`stop`, which answers
    whatever is still queued rather than leaving its clients to wait for a
    daemon that is leaving.
    """

    def __init__(self, dispatcher, session, name: str = "partcad-dispatch"):
        self._dispatcher = dispatcher
        self._session = session
        self._name = name
        self._cond = threading.Condition()
        # Each connection's queue, and the connections that have something
        # queued, in the order they get their turn.
        self._queues: dict = {}
        self._turns: collections.deque = collections.deque()
        self._stopped = False
        self._thread: Optional[threading.Thread] = None

    def submit(self, job: Job, connection) -> None:
        """Queue ``job`` behind the other requests of ``connection`` (any hashable key)."""
        with self._cond:
            if not self._stopped:
                queue = self._queues.get(connection)
                if queue is None:
                    queue = self._queues[connection] = collections.deque()
                    self._turns.append(connection)
                queue.append(job)
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
                    self._thread.start()
                self._cond.notify()
                return
        job.drop(STOPPING)

    def stop(self) -> None:
        """Serve nothing more; answer what is still queued. The running request is left to finish."""
        with self._cond:
            self._stopped = True
            left = [job for queue in self._queues.values() for job in queue]
            self._queues.clear()
            self._turns.clear()
            self._cond.notify_all()
        for job in left:
            job.drop(STOPPING)

    def _next(self) -> Optional[Job]:
        with self._cond:
            while not self._turns and not self._stopped:
                self._cond.wait()
            if self._stopped:
                return None
            connection = self._turns.popleft()
            queue = self._queues[connection]
            job = queue.popleft()
            if queue:
                # Its next request waits for every other connection's turn.
                self._turns.append(connection)
            else:
                del self._queues[connection]
            return job

    def _run(self) -> None:
        while True:
            job = self._next()
            if job is None:
                return
            self._serve(job)

    def _serve(self, job: Job) -> None:
        if not job.token.start():
            # Cancelled while it waited, and answered by whoever cancelled it.
            job.finish()
            return
        session = self._session
        if job.sink is not None:
            session.emitter.set_sink(job.sink)
        response = None
        try:
            response = self._dispatcher.dispatch(job.request, session, job.token)
        except BaseException as e:  # pylint: disable=broad-except
            # The dispatcher answers every Exception itself; this is anything
            # else a handler let out (a SystemExit, say). It is that request's
            # failure, and this thread is every client's: it must not end here.
            detail = traceback.format_exc()
            _logger.error("Unhandled %s in JSON-RPC dispatch: %s", e.__class__.__name__, detail)
            print("PartCAD daemon: a request ended in %r" % e, file=sys.stderr)
            owed, request_id = request_id_of(job.request)
            if owed:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": INTERNAL_ERROR, "message": str(e) or e.__class__.__name__},
                }
        finally:
            if job.sink is not None:
                session.emitter.set_sink(None)
        try:
            self._answer(job, response)
        finally:
            job.finish()

    @staticmethod
    def _answer(job: Job, response) -> None:
        """Write the answer -- or, if it cannot be encoded, say so instead.

        The transport encodes it here, on this thread, and an answer JSON cannot
        carry (a handler returning an object it does not know) raises. On the
        thread a connection used to be served by, that ended the connection; on
        this one it would end serving for everybody.
        """
        try:
            job.respond(response)
        except Exception as e:  # pylint: disable=broad-except
            owed, request_id = request_id_of(job.request)
            _logger.error("The answer to a JSON-RPC request could not be sent: %s", e)
            if owed:
                with contextlib.suppress(Exception):
                    job.respond(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": INTERNAL_ERROR, "message": "The answer could not be sent: %s" % e},
                        }
                    )
