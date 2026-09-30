#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A memcached server, in Python, for the tests of the 'cacheRemote' tier.

Enough of the memcached text protocol for a client to store and fetch entries:
'set', 'get'/'gets', 'delete', 'version', 'flush_all' and 'quit'. That is the
whole of what the cache backend uses, and running it here is what lets the test
suite exercise a real socket, a real protocol and real byte payloads without
depending on a memcached being installed.

It runs on its own event loop in its own thread, which is not incidental: a
PartCAD process drives its async work through many separate 'asyncio.run()'
calls, and a server tied to one of those loops would stop answering the moment
that loop closed. Out of the way in its own thread, it serves all of them, just
as a real memcached on another machine would - which is exactly the property the
cache backend has to get right.

It is deliberately a mock and not a memcached: entries never expire on their own
and nothing is evicted, so a test sees exactly what it stored. Two things a real
server does are kept, because the backend depends on both: 'max_item_size'
rejects an oversized value the way memcached does, and values are returned as
the exact bytes they arrived as - the zstd-compressed BREP frame travels through
this server untouched.

Usage:

    with serve_memcached() as server:
        ...  # point the client at server.host, server.port
"""

import asyncio
import threading
from contextlib import contextmanager

# What memcached itself accepts by default; the backend's size window is
# declared against this, so the mock enforces the same bound.
DEFAULT_MAX_ITEM_SIZE = 1024 * 1024


class MemcachedServer:
    """An in-process memcached, listening on a port the OS picks."""

    def __init__(self, host: str = "127.0.0.1", max_item_size: int = DEFAULT_MAX_ITEM_SIZE) -> None:
        self.host = host
        self.port = None
        self.max_item_size = max_item_size
        # The entries, as bytes, exactly as they were stored.
        self.storage: dict[bytes, bytes] = {}
        # What each key was stored with, so a test can assert on the protocol
        # rather than only on the round trip.
        self.flags: dict[bytes, int] = {}
        self.expirations: dict[bytes, int] = {}

    async def serve_forever(self, ready: threading.Event) -> None:
        server = await asyncio.start_server(self._serve, self.host, 0)
        self.port = server.sockets[0].getsockname()[1]
        ready.set()
        async with server:
            await server.serve_forever()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                terms = line.split()
                if not terms:
                    continue
                command = terms[0].lower()

                if command in (b"get", b"gets"):
                    self._write_values(writer, terms[1:], with_cas=command == b"gets")
                elif command == b"set":
                    await self._store(reader, writer, terms)
                elif command == b"delete":
                    found = self.storage.pop(terms[1], None) is not None
                    writer.write(b"DELETED\r\n" if found else b"NOT_FOUND\r\n")
                elif command == b"flush_all":
                    self.storage.clear()
                    writer.write(b"OK\r\n")
                elif command == b"version":
                    writer.write(b"VERSION 1.6.0-partcad-mock\r\n")
                elif command == b"quit":
                    break
                else:
                    writer.write(b"ERROR\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    def _write_values(self, writer: asyncio.StreamWriter, keys, with_cas: bool) -> None:
        for key in keys:
            value = self.storage.get(key)
            if value is None:
                continue
            header = b"VALUE %s %d %d" % (key, self.flags.get(key, 0), len(value))
            if with_cas:
                # The cache never does a compare-and-swap, so one token for
                # every entry is as much as the protocol needs here.
                header += b" 1"
            writer.write(header + b"\r\n" + value + b"\r\n")
        writer.write(b"END\r\n")

    async def _store(self, reader, writer: asyncio.StreamWriter, terms) -> None:
        # set <key> <flags> <exptime> <bytes>\r\n<data block>\r\n
        key, flags, exptime, length = terms[1], int(terms[2]), int(terms[3]), int(terms[4])
        data = (await reader.readexactly(length + 2))[:-2]
        if length > self.max_item_size:
            writer.write(b"SERVER_ERROR object too large for cache\r\n")
            return
        self.storage[key] = data
        self.flags[key] = flags
        self.expirations[key] = exptime
        writer.write(b"STORED\r\n")


@contextmanager
def serve_memcached(max_item_size: int = DEFAULT_MAX_ITEM_SIZE):
    """Run the server for the duration of the block, yielding it."""
    server = MemcachedServer(max_item_size=max_item_size)
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    serving = {}

    def run():
        asyncio.set_event_loop(loop)
        serving["task"] = loop.create_task(server.serve_forever(ready))
        try:
            loop.run_until_complete(serving["task"])
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not ready.wait(timeout=10):
        raise RuntimeError("the mock memcached server did not start")
    try:
        yield server
    finally:
        # Cancelling the task, not stopping the loop: 'loop.stop()' interrupts
        # 'run_until_complete' without unwinding 'async with server', so the
        # listening socket would still be open after 'loop.close()'.
        loop.call_soon_threadsafe(serving["task"].cancel)
        thread.join(timeout=10)
        loop.close()
