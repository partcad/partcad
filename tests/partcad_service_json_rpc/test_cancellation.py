#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Cancelling a request, and serving requests one at a time apart from reading them.

``core.cancellation`` is the flag a ``$/cancelRequest`` sets and the safe points
that look at it; ``transport.dispatch`` is the one thread that serves requests,
in turns per connection, and what each connection keeps of its own requests so
that a cancellation can find them. The transports that use both are tested
beside them (``test_socket_server.py``, ``test_stdio.py``,
``test_win_pipe_serving.py``); these pin the pieces on their own.
"""

import asyncio
import threading
import time

import pytest

from partcad_service_json_rpc.core import cancellation
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.rpc.dispatcher import INTERNAL_ERROR, REQUEST_CANCELLED, Dispatcher
from partcad_service_json_rpc.transport.dispatch import STOPPING, Dispatch, Job, Requests

# Long enough not to matter on a loaded machine; every wait below ends as soon
# as what it waits for happens.
TIMEOUT = 30


class Session:
    def __init__(self):
        self.emitter = EventEmitter()


# ---- the flag ----------------------------------------------------------------


def test_a_request_cancelled_while_queued_never_starts_and_is_answered_by_whoever_cancelled_it():
    token = cancellation.CancelToken()
    assert token.cancel() is True
    assert token.start() is False
    assert token.cancelled


def test_a_request_cancelled_while_running_is_only_asked_to_stop():
    token = cancellation.CancelToken()
    assert token.start() is True
    assert token.cancel() is False
    assert token.cancelled


def test_a_safe_point_outside_a_request_does_nothing():
    # An operation called directly -- by a test, by the legacy adapter -- is
    # never stopped by one.
    cancellation.check()
    assert cancellation.cancelled() is False


def test_a_safe_point_stops_a_cancelled_request_and_only_while_it_is_served():
    token = cancellation.CancelToken()
    token.cancel()
    with cancellation.serving(token):
        with pytest.raises(cancellation.RequestCancelled):
            cancellation.check()
    cancellation.check()


def test_a_safe_point_inside_the_coroutines_a_request_runs_sees_the_flag():
    # Operations run their work with 'asyncio.run' and 'gather'; each task
    # starts with a copy of the context it was made in, and so with the flag.
    token = cancellation.CancelToken()
    token.cancel()

    async def one():
        cancellation.check()

    async def everything():
        return await asyncio.gather(one(), one(), return_exceptions=True)

    with cancellation.serving(token):
        results = asyncio.run(everything())
    assert all(isinstance(result, cancellation.RequestCancelled) for result in results)


# ---- the dispatcher ------------------------------------------------------------


def test_a_handler_that_stops_at_a_safe_point_is_answered_request_cancelled():
    token = cancellation.CancelToken()
    token.start()

    def work(session, params):
        try:
            token.cancel()
            cancellation.check()
        except Exception:  # pylint: disable=broad-except
            # What an operation reporting one object's failure and carrying on
            # does: it must not swallow a cancellation.
            return "swallowed"
        return "finished"

    response = Dispatcher({"work": work}).dispatch({"jsonrpc": "2.0", "id": 4, "method": "work"}, None, token)
    assert response == {"jsonrpc": "2.0", "id": 4, "error": {"code": REQUEST_CANCELLED, "message": "Request cancelled"}}


def test_a_cancelled_notification_is_answered_with_nothing():
    token = cancellation.CancelToken()
    token.start()
    token.cancel()
    response = Dispatcher({"work": lambda s, p: cancellation.check()}).dispatch(
        {"jsonrpc": "2.0", "method": "work"}, None, token
    )
    assert response is None


def test_a_request_that_reaches_no_safe_point_finishes_as_usual():
    # A cancellation is a hint, and the protocol allows answering anyway.
    token = cancellation.CancelToken()
    token.start()

    def work(session, params):
        token.cancel()
        return "done"

    response = Dispatcher({"work": work}).dispatch({"jsonrpc": "2.0", "id": 1, "method": "work"}, None, token)
    assert response["result"] == "done"


# ---- serving one at a time -------------------------------------------------------


class Served:
    """Answers and finishes, recorded per request id."""

    def __init__(self):
        self.answers = {}
        self.finished = []
        self.lock = threading.Lock()

    def job(self, request, requests=None, sink=None):
        def respond(response):
            with self.lock:
                self.answers[response.get("id")] = response

        def finish(job):
            with self.lock:
                self.finished.append(job.request.get("id"))
            if requests is not None:
                requests.untrack(job)

        job = Job(request, sink, respond, finish)
        if requests is not None:
            requests.track(job)
        return job


def request(request_id, method, **params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def gate():
    """A handler that waits until the test lets it go; released however the test ends."""
    entered = threading.Event()
    release = threading.Event()

    def wait(session, params):
        entered.set()
        assert release.wait(TIMEOUT)
        return "released"

    yield entered, release, wait
    release.set()


def test_connections_take_turns_rather_than_one_going_first_with_everything(gate):
    entered, release, wait = gate
    order = []

    def note(session, params):
        order.append(params["who"])
        return params["who"]

    dispatch = Dispatch(Dispatcher({"wait": wait, "note": note}), Session())
    served = Served()
    try:
        dispatch.submit(served.job(request(0, "wait")), "editor")
        assert entered.wait(TIMEOUT)
        # The editor asks for three tabs at once; a command typed meanwhile
        # is served after the first of them, not after all three.
        for n in (1, 2, 3):
            dispatch.submit(served.job(request(n, "note", who="editor %d" % n)), "editor")
        dispatch.submit(served.job(request(9, "note", who="pc")), "pc")
        release.set()
        assert eventually(lambda: len(served.finished) == 5)
        assert order == ["editor 1", "pc", "editor 2", "editor 3"]
    finally:
        dispatch.stop()


def eventually(condition, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_a_queued_request_cancelled_is_answered_at_once_and_never_runs(gate):
    entered, release, wait = gate
    ran = []
    dispatch = Dispatch(Dispatcher({"wait": wait, "quick": lambda s, p: ran.append(1)}), Session())
    served = Served()
    requests = Requests()
    try:
        dispatch.submit(served.job(request(1, "wait"), requests), requests)
        assert entered.wait(TIMEOUT)
        dispatch.submit(served.job(request(2, "quick"), requests), requests)

        requests.cancel({"id": 2})

        # Answered before the request ahead of it has finished.
        assert served.answers[2]["error"]["code"] == REQUEST_CANCELLED
        assert 1 not in served.answers
        release.set()
        assert requests.wait_idle(TIMEOUT)
        assert served.answers[1]["result"] == "released"
        assert ran == []
    finally:
        dispatch.stop()


def test_a_running_request_cancelled_stops_at_its_next_safe_point():
    started = threading.Event()
    stopped_at = []

    def steps(session, params):
        started.set()
        for step in range(1000):
            try:
                cancellation.check()
            except cancellation.RequestCancelled:
                stopped_at.append(step)
                raise
            time.sleep(0.01)
        return "all of them"

    dispatch = Dispatch(Dispatcher({"steps": steps}), Session())
    served = Served()
    requests = Requests()
    try:
        dispatch.submit(served.job(request(1, "steps"), requests), requests)
        assert started.wait(TIMEOUT)
        requests.cancel({"id": 1})
        assert requests.wait_idle(TIMEOUT)
        assert served.answers[1]["error"]["code"] == REQUEST_CANCELLED
        assert stopped_at and stopped_at[0] < 1000
    finally:
        dispatch.stop()


def test_a_cancellation_for_a_request_that_is_not_there_is_nothing_to_do():
    # It crosses the answer on the wire all the time.
    requests = Requests()
    requests.cancel({"id": 7})
    requests.cancel(None)
    requests.cancel([7])
    assert requests.wait_idle(0)


def test_a_client_that_cannot_be_reached_has_its_requests_cancelled_but_not_its_notifications(gate):
    entered, release, wait = gate
    ran = []
    dispatch = Dispatch(Dispatcher({"wait": wait, "note": lambda s, p: ran.append(p)}), Session())
    served = Served()
    requests = Requests()
    try:
        dispatch.submit(served.job(request(1, "wait"), requests), requests)
        assert entered.wait(TIMEOUT)
        dispatch.submit(served.job(request(2, "note", n=2), requests), requests)
        dispatch.submit(served.job({"jsonrpc": "2.0", "method": "note", "params": {"n": 3}}, requests), requests)

        requests.cancel_all()
        release.set()

        assert requests.wait_idle(TIMEOUT)
        # Nobody to answer the queued one, and it did not run; the running one
        # was flagged and finished (it reached no safe point); the notification
        # is what the client asked to have done, and was.
        assert 2 not in served.answers
        assert ran == [{"n": 3}]
    finally:
        dispatch.stop()


def test_stopping_answers_what_is_still_queued_and_ends_the_thread(gate):
    entered, release, wait = gate
    dispatch = Dispatch(Dispatcher({"wait": wait, "quick": lambda s, p: "ran"}), Session(), name="pc-test-dispatch")
    served = Served()
    dispatch.submit(served.job(request(1, "wait")), "c")
    assert entered.wait(TIMEOUT)
    dispatch.submit(served.job(request(2, "quick")), "c")

    dispatch.stop()

    assert served.answers[2]["error"] == {"code": REQUEST_CANCELLED, "message": STOPPING}
    release.set()
    thread = dispatch._thread  # pylint: disable=protected-access
    thread.join(TIMEOUT)
    assert not thread.is_alive()
    # And anything sent after is answered the same, not left waiting.
    dispatch.submit(served.job(request(3, "quick")), "c")
    assert served.answers[3]["error"]["message"] == STOPPING


def test_a_handler_that_lets_out_more_than_an_exception_does_not_take_the_thread_with_it():
    def leave(session, params):
        raise SystemExit(3)

    dispatch = Dispatch(Dispatcher({"leave": leave, "quick": lambda s, p: "still here"}), Session())
    served = Served()
    requests = Requests()
    try:
        dispatch.submit(served.job(request(1, "leave"), requests), requests)
        dispatch.submit(served.job(request(2, "quick"), requests), requests)
        assert requests.wait_idle(TIMEOUT)
        assert served.answers[1]["error"]["code"] == INTERNAL_ERROR
        assert served.answers[2]["result"] == "still here"
    finally:
        dispatch.stop()


def test_what_a_request_emits_reaches_its_own_sink_only_while_it_runs():
    seen = []
    session = Session()

    def work(session, params):
        session.emitter.emit("items", params["n"])
        return params["n"]

    dispatch = Dispatch(Dispatcher({"work": work}), session)
    served = Served()
    requests = Requests()
    try:
        dispatch.submit(served.job(request(1, "work", n=1), requests, lambda e, p: seen.append(("a", p))), requests)
        dispatch.submit(served.job(request(2, "work", n=2), requests, lambda e, p: seen.append(("b", p))), requests)
        assert requests.wait_idle(TIMEOUT)
        assert seen == [("a", 1), ("b", 2)]
        session.emitter.emit("items", 3)
        assert seen == [("a", 1), ("b", 2)]
    finally:
        dispatch.stop()


def test_an_answer_that_cannot_be_encoded_is_said_so_and_serving_goes_on():
    # The transport encodes the answer on the dispatch thread; an answer JSON
    # cannot carry must not end serving for everybody.
    import json

    answers = []

    def respond(response):
        answers.append(json.loads(json.dumps(response)))

    dispatch = Dispatch(Dispatcher({"odd": lambda s, p: object(), "quick": lambda s, p: "fine"}), Session())
    requests = Requests()
    try:
        for job in (
            Job(request(1, "odd"), None, respond, requests.untrack),
            Job(request(2, "quick"), None, respond, requests.untrack),
        ):
            requests.track(job)
            dispatch.submit(job, requests)
        assert requests.wait_idle(TIMEOUT)
        assert answers[0]["id"] == 1 and answers[0]["error"]["code"] == INTERNAL_ERROR
        assert answers[1] == {"jsonrpc": "2.0", "id": 2, "result": "fine"}
    finally:
        dispatch.stop()
