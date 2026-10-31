#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The caller's half of `partcad_utils.container_service`.

Here rather than in `partcad` because both a client and a daemon speak it: the
daemon runs sandboxes, KiCad imports and plugin containers through it, and `pc
open` runs an application through it, from a process that has to stay cheap to
import. It needs `requests` and nothing else.

Two dialects, as the service has (see its docstring): `call` and `run` speak
frames, which is what PartCAD uses with every container it starts and with a
`partcad-service-remote-docker` that says it can (`protocol`); `execute` speaks
the JSON one, for a service of an older release.

**Connections are kept.** A render sends a container a command per part, and a
connection per command was a TCP handshake and a server thread per command. A
`requests.Session` keeps them open; it is one per thread rather than one shared,
because a session's connection pool is safe to share and the rest of it --
cookies, adapters being mounted -- is not documented to be, and commands are
sent from every thread of the executor at once.

And one per server, which an address does not name: a session's pool hands
out connections by host and port, and a port can be published again for
another container while a connection to the last one is still open. A
connection that still reaches the old server -- which the in-process ones in
the tests do, after their listener has closed -- then carries this server's
request to that one, and its token is refused. Every container PartCAD starts
has a token of its own, so a session per URL *and* token is a session per
container.
"""

import asyncio
import collections
import json
import os
import threading
from typing import Any, Dict, Optional, Union

import requests
import urllib3

from . import container_files, container_service
from . import logging as pc_logging

_SESSIONS = threading.local()
# The sessions a thread keeps, least recently used first out. More than one
# process needs at once -- a sandbox per interpreter, KiCad, a plugin or two --
# and few enough that a long-running daemon, which goes on starting containers,
# does not keep a connection to each one it ever started.
MAX_SESSIONS = 8


def _session(url: str, token: Optional[str]) -> requests.Session:
    """This thread's session for the server at ``url`` holding ``token``.

    And new ones in a process forked from the one that made them: a forked
    child inherits its parent's sockets, and two processes writing requests
    into one connection is two garbled conversations.
    """
    held = getattr(_SESSIONS, "held", None)
    if held is None or held[0] != os.getpid():
        held = (os.getpid(), collections.OrderedDict())
        _SESSIONS.held = held
    sessions = held[1]
    key = (url, token)
    session = sessions.pop(key, None) or requests.Session()
    sessions[key] = session
    while len(sessions) > MAX_SESSIONS:
        sessions.popitem(last=False)[1].close()
    return session


def close_sessions() -> None:
    """Close this thread's sessions, and with them every connection they keep open.

    For a test, whose servers are gone once it ends: a connection left open to
    one of them keeps the thread serving it alive, for whatever the process
    runs next to find (see `tests/conftest.py`).
    """
    held = getattr(_SESSIONS, "held", None)
    _SESSIONS.held = None
    if held is not None and held[0] == os.getpid():
        for session in held[1].values():
            session.close()


# The protocol each service answered with, by URL: asked once per process.
_PROTOCOLS: Dict[str, int] = {}
_PROTOCOLS_GUARD = threading.Lock()


def _summary(command, params) -> str:
    """What a request is, for a log line: the command, and how much rides with it.

    Not the request itself. A request in upload mode carries whole files, and
    logging that at debug level wrote megabytes per command.
    """
    params = params or {}

    def size(value) -> int:
        if isinstance(value, dict) and "zlib" in value:
            value = value["zlib"]
        if isinstance(value, (bytes, bytearray, memoryview)):
            return memoryview(value).nbytes
        return len(value or "")

    sizes = []
    for key in ("input_files", "input_dirs", "blobs"):
        payload = params.get(key) or {}
        if payload:
            sizes.append("%s: %d (%d bytes)" % (key, len(payload), sum(size(v) for v in payload.values())))
    trees = params.get("input_trees") or {}
    if trees:
        files = sum(len(tree.get("files") or ()) for tree in trees.values())
        sizes.append("input_trees: %d (%d files)" % (len(trees), files))
    for key in ("output_files", "output_dirs"):
        if params.get(key):
            sizes.append("%s: %d" % (key, len(params[key])))
    return "%s%s" % (command, (" [" + ", ".join(sizes) + "]") if sizes else "")


class _Body:
    """A frame's buffers as one request body, sent buffer by buffer.

    Iterable and sized, which is what makes `requests` send it with a
    Content-Length and without joining it -- the service reads a body by its
    length and does not speak chunked encoding.
    """

    def __init__(self, parts):
        self.parts = parts
        self.length = container_service.frame_length(parts)

    def __len__(self):
        return self.length

    def __iter__(self):
        return iter(self.parts)


class RuntimeJsonRpcClient:
    """JSON-RPC client for the service inside a container PartCAD started."""

    def __init__(self, host: str = "localhost", port: int = 5000, token: str = None, scheme: str = "http"):
        """Who to talk to.

        Args:
          host: Server hostname.
          port: Server port number.
          token: The bearer token the server was started with, if any. Every
            container PartCAD starts has one (see `partcad_utils.containers`);
            `partcad-service-remote-docker` listening anywhere but loopback
            refuses to start without one.
          scheme: 'http' or 'https'. A container on this machine speaks plain
            HTTP on a loopback port; anything off this machine is the caller's to
            secure.
        """
        self.host = host
        self.port = port
        self.token = token
        self.scheme = scheme
        self.request_id = 0
        self.lock = threading.RLock()

    @property
    def url(self) -> str:
        host = "[%s]" % self.host if ":" in self.host and not self.host.startswith("[") else self.host
        return "%s://%s:%s" % (self.scheme, host, self.port)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": "Bearer %s" % self.token} if self.token else {}

    def get_request_id(self):
        with self.lock:
            self.request_id += 1
            return self.request_id

    def ping(self, timeout: float = 2.0) -> Optional[int]:
        """The protocol the server speaks, or None if nothing answered.

        Unauthenticated and side-effect free on the server, so it is what tells
        a freshly started container from a ready one.
        """
        try:
            response = requests.get(self.url + "/", timeout=timeout)
            if response.status_code != 200:
                return None
            return int(json.loads(response.content).get("protocol") or 1)
        except (requests.exceptions.RequestException, ValueError, AttributeError):
            return None

    def protocol(self, timeout: float = 10.0) -> Optional[int]:
        """The protocol the server speaks, asked once per process; None while nothing answers.

        For `partcad-service-remote-docker`, which is installed on its own
        machine and may be any release. One that predates the question has no
        `GET /` at all and answers 501 -- which is an answer, and is 1; no
        answer is not remembered, so a service that was down is asked again.
        """
        with _PROTOCOLS_GUARD:
            if self.url in _PROTOCOLS:
                return _PROTOCOLS[self.url]
        try:
            response = _session(self.url, self.token).get(self.url + "/", timeout=timeout)
        except requests.exceptions.RequestException:
            return None
        found = 1
        if response.status_code == 200:
            try:
                found = int(json.loads(response.content).get("protocol") or 1)
            except (ValueError, AttributeError, TypeError):
                found = 1
        elif response.status_code >= 500 and response.status_code != 501:
            # The service, or a proxy in front of it, failing: not an answer.
            return None
        with _PROTOCOLS_GUARD:
            _PROTOCOLS[self.url] = found
        return found

    # ---------------------------------------------------------------- frames --

    def _post_frame(self, parts, timeout):
        """POST a frame; ``(status, content type, body)``. The one place a frame meets the network."""
        headers = dict(self._headers())
        headers["Content-Type"] = container_service.FRAME_TYPE
        response = _session(self.url, self.token).post(
            self.url + "/jsonrpc", data=_Body(parts), headers=headers, timeout=timeout, stream=True
        )
        # In one read rather than through `response.content`, which reads in
        # ten-kilobyte pieces: half the time for an answer of fifty megabytes.
        # Read to its end, the connection goes back to the pool by itself.
        try:
            body = response.raw.read(decode_content=True)
        except urllib3.exceptions.HTTPError as e:
            # What `response.content` would have raised: `requests` wraps
            # urllib3's errors only on its own way of reading. Unwrapped, an
            # answer cut off by a container dying mid-reply escaped `call` as
            # urllib3's, past every caller that asks whether the container
            # stopped when no answer came.
            response.close()
            raise requests.exceptions.ConnectionError(e, response=response)
        return response.status_code, response.headers.get("Content-Type", ""), body

    def call(self, method: str, params: Dict[str, Any], timeout: float = None) -> Optional[Dict]:
        """One JSON-RPC call in the frame dialect: the response object, or None if none arrived.

        Every bytes value of ``params`` travels as it is, and every bytes value
        of the answer comes back as a `memoryview` of what was read.
        """
        request = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.get_request_id()}
        pc_logging.debug("JSON-RPC %s %s: %s" % (self.url, method, _summary(params.get("command"), params)))
        try:
            status, content_type, body = self._post_frame(container_service.encode_frame(request), timeout)
            if status == 401:
                return {"error": {"code": -32001, "message": "The container refused this client's token"}}
            if container_service.is_frame(content_type):
                answer = container_service.decode_frame(body)
            else:
                # What answers without speaking frames -- a proxy in front of
                # the service, or the service refusing before it read the body --
                # may still have said something worth reading.
                answer = json.loads(body)
            # A response is an object; anything else is no response at all.
            return answer if isinstance(answer, dict) else None
        except (requests.exceptions.RequestException, ValueError) as e:
            pc_logging.error("Error during RPC call to %s: %s" % (self.url, e))
            return None

    def run(
        self,
        command: list,
        request: "container_files.Request",
        timeout: float = None,
        route: Optional[dict] = None,
    ) -> Optional[Dict]:
        """`execute` ``command`` in the frame dialect, sending only what the server lacks (see `container_files`)."""
        key = (self.url, self.token, tuple(sorted((route or {}).items())))
        return container_files.execute(self.call, key, command, request, timeout=timeout, route=route)

    # ------------------------------------------------------------------ JSON --

    def execute(self, command: list, params: Dict[str, Any] = None, timeout: float = None) -> Union[Dict, None]:
        """Run `command` on the server, in the JSON dialect.

        Returns the JSON-RPC response object -- `result` or `error` -- or None if
        no response arrived at all. `timeout` is seconds to wait, None for no
        bound: an application opened for editing runs for as long as somebody
        is editing.
        """
        request = {
            "jsonrpc": "2.0",
            "method": "execute",
            "params": {"command": command, **(params or {})},
            "id": self.get_request_id(),
        }
        pc_logging.debug("JSON-RPC %s: %s" % (self.url, _summary(command, params)))
        try:
            response = _session(self.url, self.token).post(
                self.url + "/jsonrpc", json=request, headers=self._headers(), timeout=timeout
            )
            if response.status_code == 401:
                return {"error": {"code": -32001, "message": "The container refused this client's token"}}
            return json.loads(response.content)
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            pc_logging.error("Error during RPC call to %s: %s" % (self.url, e))
            return None

    def which(self, names: list, timeout: float = 30) -> Optional[Dict[str, Optional[str]]]:
        """Where each of ``names`` resolves in the container, or None for each that does not."""
        request = {"jsonrpc": "2.0", "method": "which", "params": {"names": list(names)}, "id": self.get_request_id()}
        try:
            response = _session(self.url, self.token).post(
                self.url + "/jsonrpc", json=request, headers=self._headers(), timeout=timeout
            )
            answer = json.loads(response.content)
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            pc_logging.error("Error during RPC call to %s: %s" % (self.url, e))
            return None
        return answer.get("result") if isinstance(answer, dict) else None

    async def execute_async(
        self, command: list, params: Dict[str, Any] = None, timeout: float = None
    ) -> Union[Dict, None]:
        """`execute`, without holding up the event loop while the command runs.

        It used to call `requests.post` straight from the coroutine, which
        blocked every other task on the loop for as long as the container took
        -- so a tree of parts rendering "concurrently" rendered one at a time.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.execute(command, params, timeout))
