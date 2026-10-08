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
"""

import asyncio
import json
import threading
from typing import Any, Dict, Optional, Union

import requests

from . import logging as pc_logging


def _summary(command, params) -> str:
    """What a request is, for a log line: the command, and how much rides with it.

    Not the request itself. A request in upload mode carries whole directories as
    base64, and logging that at debug level wrote megabytes per command.
    """
    params = params or {}
    sizes = []
    for key in ("input_files", "input_dirs"):
        payload = params.get(key) or {}
        if payload:
            sizes.append("%s: %d (%d bytes)" % (key, len(payload), sum(len(v or "") for v in payload.values())))
    for key in ("output_files", "output_dirs"):
        if params.get(key):
            sizes.append("%s: %d" % (key, len(params[key])))
    return "%s%s" % (command, (" [" + ", ".join(sizes) + "]") if sizes else "")


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

    def execute(self, command: list, params: Dict[str, Any] = None, timeout: float = None) -> Union[Dict, None]:
        """Run `command` on the server.

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
            response = requests.post(self.url + "/jsonrpc", json=request, headers=self._headers(), timeout=timeout)
            if response.status_code == 401:
                return {"error": {"code": -32001, "message": "The container refused this client's token"}}
            return json.loads(response.content)
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            pc_logging.error("Error during RPC call to %s: %s" % (self.url, e))
            return None

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
