#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Client, framing and facade together, over a real socket.

A stand-in service speaks the same wire protocol the daemon does -- framed
JSON-RPC with the notifications interleaved before each response -- so this
covers what the per-module tests cannot: that a call written by the addon is
read back correctly across a socket, and that the tree and the STEP path come
out of the notification stream in the right order.
"""

import socket
import threading

import pytest
from partcad_freecad.client import JsonRpcClient
from partcad_freecad.framing import read_message, write_message
from partcad_freecad.model import KIND_ASSEMBLY, KIND_PART
from partcad_freecad.service import PartCadService

ITEMS_ROOT = {
    "name": "//",
    "packages": [{"name": "//pub", "type": "git"}],
    "parts": [{"name": "cube", "type": "cadquery", "parameters": {"width": {"type": "float", "default": 10.0}}}],
    "assemblies": [{"name": "logo", "type": "assy"}],
}


class FakeService(threading.Thread):
    """Serves framed JSON-RPC on a socket, the way the daemon does."""

    daemon = True

    def __init__(self, sock, step_path=None):
        super().__init__()
        self.stream = sock.makefile("rwb")
        self.step_path = step_path
        self.requests = []

    def run(self):
        while True:
            request = read_message(self.stream)
            if request is None:
                return
            self.requests.append(request)
            for event, payload in self._events(request):
                write_message(self.stream, {"jsonrpc": "2.0", "method": event, "params": payload})
            write_message(self.stream, {"jsonrpc": "2.0", "id": request["id"], "result": None})

    def _events(self, request):
        method = request["method"]
        if method == "package.load":
            return [
                ("packageLoaded", {"root": "//", "configPath": "/w/partcad.yaml"}),
                ("items", ITEMS_ROOT),
            ]
        if method == "list.all":
            return [("items", {"name": "//pub", "parts": [{"name": "bolt", "type": "step"}]})]
        if method.startswith("export.") and self.step_path is not None:
            with open(self.step_path, "w", encoding="utf-8") as step:
                step.write("ISO-10303-21;\nENDSEC;\n")
            return [("log", {"kind": "log", "levelno": 20, "message": "Rendering: %s" % self.step_path})]
        return []


@pytest.fixture
def connected(tmp_path):
    client_sock, server_sock = socket.socketpair()
    service_thread = FakeService(server_sock, str(tmp_path / "cube.step"))
    service_thread.start()
    stream = client_sock.makefile("rwb")

    def closer():
        # The file object holds its own reference to the descriptor, so closing
        # only the socket would leave the service waiting on a connection that
        # never reaches end of input -- the same ordering client.connect() uses.
        stream.close()
        client_sock.close()

    service = PartCadService("/unused", "/w", client=JsonRpcClient(stream, stream, closer=closer))
    try:
        yield service, service_thread, str(tmp_path / "cube.step")
    finally:
        service.close()
        server_sock.close()
        service_thread.join(timeout=5)


def test_loading_a_package_builds_the_tree(connected):
    service, _thread, _step = connected

    contents = service.load_package()

    assert [(item.kind, item.name) for item in contents] == [
        ("package", "//pub"),
        (KIND_ASSEMBLY, "logo"),
        (KIND_PART, "cube"),
    ]


def test_expanding_a_package_lists_only_that_package(connected):
    service, thread, _step = connected
    service.load_package()

    contents = service.list_package("//pub")

    assert [item.name for item in contents] == ["bolt"]
    assert [request["method"] for request in thread.requests] == ["package.load", "list.all"]


def test_exporting_a_part_writes_the_step_the_addon_asked_for(connected):
    service, thread, step = connected
    contents = service.load_package()
    cube = contents.of_kind(KIND_PART)[0]

    assert service.export(cube, step, {"width": 20.0}) == step

    request = thread.requests[-1]
    assert request["method"] == "export.part"
    assert request["params"]["type"] == "step"
    assert request["params"]["params"] == {"width": 20.0}
    assert open(step, encoding="utf-8").read().startswith("ISO-10303-21;")
