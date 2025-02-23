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
import socket
import threading
from typing import Any, Dict, Union

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
        self.socket = None
        self._connected = False

        self.lock = threading.RLock()
        self.tls = threading.local()

    def get_async_lock(self):
        if not hasattr(self.tls, "async_rpc_locks"):
            self.tls.async_rpc_locks = {}
        self_id = id(self)
        if self_id not in self.tls.async_rpc_locks:
            self.tls.async_rpc_locks[self_id] = asyncio.Lock()
        return self.tls.async_rpc_locks[self_id]

    def _connect(self):
        """Establish connection if not already connected."""
        with self.lock:
            if not self._connected:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.host, self.port))
                self._connected = True

    async def _connect_async(self):
        """Establish connection if not already connected."""
        with self.lock:
            async with self.get_async_lock():
                if not self._connected:
                    # TODO(clairbee): use asyncio to connect
                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.socket.connect((self.host, self.port))
                    self._connected = True

    def execute(self, command: str, params: Dict[str, Any] = None) -> Union[Dict, None]:
        """Execute a command on the server using JSON-RPC.

        Args:
          command: The CLI command to execute
          params: Optional parameters for the command

        Returns:
          The server's response as a dictionary, or None if there's an error
        """
        self._connect()

        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": "execute",
            "params": {"command": command, **(params or {})},
            "id": self.request_id,
        }

        try:
            # Send the request
            self.socket.sendall(json.dumps(request).encode() + b"\n")

            # Receive the response
            response = self.socket.recv(4096).decode()
            return json.loads(response)
        except (socket.error, json.JSONDecodeError) as e:
            print(f"Error during RPC call: {e}")
            self._connected = False  # Reset connection state on error
            return None

    async def execute_async(self, command: str, params: Dict[str, Any] = None) -> Union[Dict, None]:
        """Execute a command on the server using JSON-RPC.

        Args:
          command: The CLI command to execute
          params: Optional parameters for the command

        Returns:
          The server's response as a dictionary, or None if there's an error
        """
        await self._connect_async()

        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": "execute",
            "params": {"command": command, **(params or {})},
            "id": self.request_id,
        }

        try:
            # Send the request
            self.socket.sendall(json.dumps(request).encode() + b"\n")

            # Receive the response
            response = self.socket.recv(4096).decode()
            return json.loads(response)
        except (socket.error, json.JSONDecodeError) as e:
            print(f"Error during RPC call: {e}")
            self._connected = False  # Reset connection state on error
            return None

    def __del__(self):
        """Clean up the socket connection when the object is destroyed."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
