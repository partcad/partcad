#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-16
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import json
import requests
import threading
from typing import Any, Dict, Union

from . import logging as pc_logging

"""
PartCAD Runtime JSON RPC Client Module.

This module provides a JSON-RPC client for communicating with the RPC servers found in `tools/containers/_common/pc-container-json-rpc.py`
"""


class RuntimeJsonRpcClient:
    """JSON-RPC client for PartCAD runtime communication."""

    def __init__(self, host: str = "localhost", port: int = 5000):
        """Initialize the JSON-RPC client with host and port.

        Args:
          host: Server hostname (default: localhost)
          port: Server port number (default: 5000)
        """
        self.host = host
        self.port = port
        self.request_id = 0

        self.lock = threading.RLock()
        self.tls = threading.local()

    def get_async_lock(self):
        if not hasattr(self.tls, "async_rpc_locks"):
            self.tls.async_rpc_locks = {}
        self_id = id(self)
        if self_id not in self.tls.async_rpc_locks:
            self.tls.async_rpc_locks[self_id] = asyncio.Lock()
        return self.tls.async_rpc_locks[self_id]

    def get_request_id_locked(self):
        self.request_id += 1
        return self.request_id

    def get_request_id(self):
        with self.lock:
            return self.get_request_id_locked()

    async def get_request_id_async(self):
        with self.lock:
            async with self.get_async_lock():
                return self.get_request_id_locked()

    def execute(self, command: list[str], params: Dict[str, Any] = None) -> Union[Dict, None]:
        """Execute a command on the server using JSON-RPC.

        Args:
          command: The CLI command to execute
          params: Optional parameters for the command

        Returns:
          The server's response as a dictionary, or None if there's an error
        """

        request = {
            "jsonrpc": "2.0",
            "method": "execute",
            "params": {"command": command, **(params or {})},
            "id": self.get_request_id(),
        }

        request_string = json.dumps(request)
        pc_logging.debug(f"Sending request: {request_string}")

        try:
            response = requests.post(f"http://{self.host}:{self.port}/jsonrpc", json=request)
            pc_logging.debug(f"Received response: {response.content}")
            return json.loads(response.content)
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            pc_logging.error(f"Error during RPC call: {e}")
            return None

    async def execute_async(self, command: str, params: Dict[str, Any] = None) -> Union[Dict, None]:
        """Execute a command on the server using JSON-RPC.

        Args:
          command: The CLI command to execute
          params: Optional parameters for the command

        Returns:
          The server's response as a dictionary, or None if there's an error
        """

        request = {
            "jsonrpc": "2.0",
            "method": "execute",
            "params": {"command": command, **(params or {})},
            "id": await self.get_request_id_async(),
        }

        request_string = json.dumps(request)
        pc_logging.debug(f"Sending request: {request_string}")

        try:
            response = requests.post(f"http://{self.host}:{self.port}/jsonrpc", json=request)
            pc_logging.debug(f"Received response: {response.content}")
            return json.loads(response.content)
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            pc_logging.error(f"Error during RPC call: {e}")
            return None
