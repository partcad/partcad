#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc mcp` driven the way an agent drives it: through an MCP client, and only that.

The daemon is a fake that records what it is sent and answers what a test tells
it to, so every test here says two things: what reached the daemon, and what the
agent got back. The real daemon is `test_mcp_e2e.py`'s.
"""

import base64
import json
import os
import re

import anyio
import pytest
from mcp import Client
from mcp_types import ImageContent, TextContent

from partcad_client.client import DaemonError
from partcad_client.mcp_server import Bridge, PathScope
from partcad_client.mcp_server import server as mcp_server
from partcad_client.mcp_server.server import build_server

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


class FakeDaemon:
    """Answers each method with ``handlers[method](params, emit)``, and records the request."""

    def __init__(self, handlers=None):
        self.handlers = {"context.create": lambda params, emit: {"context": "ctx-1"}, **(handlers or {})}
        self.calls = []
        self.connections = 0
        # Methods that, the next time they are asked for, find the connection
        # gone -- the way a daemon that restarted while the server sat idle does.
        self.drops = []

    def connect(self):
        self.connections += 1
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, daemon):
        self.daemon = daemon
        self.closed = False

    def call(self, method, params=None, on_event=None):
        self.daemon.calls.append((method, params))
        if method in self.daemon.drops:
            self.daemon.drops.remove(method)
            raise RuntimeError("the PartCAD service closed the connection")
        handler = self.daemon.handlers.get(method)
        if handler is None:
            raise DaemonError({"code": -32601, "message": "Method not found: %s" % method})
        return handler(params, on_event or (lambda name, payload: None))

    def close(self):
        self.closed = True


class StubConfig:
    def to_dict(self):
        return {"offline": True}


def serve(workspace, handlers=None, roots=(), unrestricted=False):
    daemon = FakeDaemon(handlers)
    bridge = Bridge(str(workspace), connect=daemon.connect, user_config=StubConfig())
    scope = PathScope([bridge.root, *roots], unrestricted=unrestricted)
    return daemon, build_server(bridge, scope)


def using(server, body):
    """Run ``body(client)`` against ``server``, in process."""

    async def main():
        async with Client(server) as client:
            return await body(client)

    return anyio.run(main)


def call(server, tool, arguments=None, **kwargs):
    return using(server, lambda client: client.call_tool(tool, arguments or {}, **kwargs))


def body(result) -> dict:
    assert isinstance(result.content[0], TextContent)
    return json.loads(result.content[0].text)


def log(level, message):
    return {"kind": "log", "levelno": level, "levelname": "", "message": message, "created": 0}


def requests(daemon, method):
    return [params for name, params in daemon.calls if name == method]


# --- What is served ----------------------------------------------------------


def test_the_tools_are_the_curated_set_and_the_escape_hatch(tmp_path):
    _, server = serve(tmp_path)
    tools = using(server, lambda client: client.list_tools()).tools
    assert sorted(tool.name for tool in tools) == sorted(
        [
            "list_objects",
            "info",
            "render",
            "export",
            "test",
            "lint",
            "bom",
            "search",
            "instructions",
            "version",
            "list_methods",
            "execute",
        ]
    )
    for tool in tools:
        assert tool.input_schema["type"] == "object"
        assert tool.title and tool.description, tool.name
        assert "ctx" not in tool.input_schema.get("properties", {}), tool.name


def test_the_annotations_do_not_claim_less_than_the_truth(tmp_path):
    _, server = serve(tmp_path)
    tools = {tool.name: tool.annotations for tool in using(server, lambda client: client.list_tools()).tools}
    for name in ("list_objects", "info", "render", "test", "lint", "bom", "search", "instructions"):
        assert tools[name].read_only_hint is True, name
    assert tools["export"].read_only_hint is False
    assert tools["export"].destructive_hint is True
    assert tools["execute"].read_only_hint is False
    assert tools["execute"].destructive_hint is True
    assert tools["execute"].idempotent_hint is False


def test_the_instructions_name_only_real_tools(tmp_path):
    """An instruction naming a tool that was renamed sends every agent looking for it."""
    _, server = serve(tmp_path)
    names = {tool.name for tool in using(server, lambda client: client.list_tools()).tools}
    text = mcp_server.instructions(Bridge(str(tmp_path)), PathScope([str(tmp_path)]))
    for word in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text):
        assert word in names, word
    for name in ("list_objects", "info", "render", "test", "export", "list_methods", "execute"):
        assert re.search(r"\b%s\b" % name, text), name


# --- Requests ----------------------------------------------------------------


def test_a_tool_sends_what_pc_sends_in_the_workspaces_context(tmp_path):
    daemon, server = serve(tmp_path, {"list.objects": lambda params, emit: None})
    call(server, "list_objects", {"kind": "assemblies", "recursive": True})
    (create,) = requests(daemon, "context.create")
    assert create == {"url": tmp_path.resolve().as_uri(), "userConfig": {"offline": True}}
    assert requests(daemon, "list.objects") == [
        {"kind": "assemblies", "package": None, "recursive": True, "context": "ctx-1"}
    ]


def test_packages_are_listed_by_their_own_method(tmp_path):
    daemon, server = serve(tmp_path, {"list.packages": lambda params, emit: None})
    call(server, "list_objects", {"kind": "packages"})
    assert requests(daemon, "list.packages") == [{"package": None, "recursive": False, "context": "ctx-1"}]


def test_a_kind_is_the_flag_pc_sets_and_parameters_are_assignments(tmp_path):
    daemon, server = serve(tmp_path, {"info.object": lambda params, emit: None})
    call(server, "info", {"object": "//pkg:box", "kind": "assembly", "params": {"width": 10, "hollow": True}})
    (request,) = requests(daemon, "info.object")
    assert request["object"] == "//pkg:box"
    assert request["assembly"] is True
    assert request["params"] == ["width=10", "hollow=true"]


def test_assembly_instructions_carry_this_machines_build_vs_buy_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server.garage, "load_all_bvb", lambda: {"//pkg:bolt": "buy"})
    daemon, server = serve(tmp_path, {"assembly.guide": lambda params, emit: {"steps": []}})
    call(server, "instructions", {"object": "robot"})
    (request,) = requests(daemon, "assembly.guide")
    assert request["bvb"] == {"//pkg:bolt": "buy"}
    assert request["object"] == "robot"


# --- Results -----------------------------------------------------------------


def test_the_log_is_the_answer_of_a_method_that_logs_it(tmp_path):
    def listing(params, emit):
        emit("log", log(20, "PartCAD parts:\n\tbox    A box"))
        emit("info", "a bare-string notification")
        return None

    _, server = serve(tmp_path, {"list.objects": listing})
    result = call(server, "list_objects")
    assert not result.is_error
    reply = body(result)
    assert reply["ok"] is True
    assert reply["log"] == ["INFO: PartCAD parts:\n\tbox    A box", "INFO: a bare-string notification"]
    assert "result" not in reply


def test_an_error_line_is_a_failed_result(tmp_path):
    def failing(params, emit):
        emit("log", log(40, "Part //pkg:box failed to build"))
        return None

    _, server = serve(tmp_path, {"test.run": failing})
    result = call(server, "test", {"object": "box"})
    assert result.is_error
    reply = body(result)
    assert reply["ok"] is False
    assert reply["errors"] == ["Part //pkg:box failed to build"]


def test_a_daemon_error_is_a_result_and_not_a_protocol_error(tmp_path):
    def refusing(params, emit):
        emit("log", log(20, "Loading //pkg"))
        raise DaemonError({"code": -32002, "message": "Part //pkg:nope is not found"})

    _, server = serve(tmp_path, {"bom": refusing})
    result = call(server, "bom", {"object": "nope"})
    assert result.is_error
    reply = body(result)
    assert reply["error"] == "Part //pkg:nope is not found"
    assert reply["code"] == -32002
    assert reply["log"] == ["INFO: Loading //pkg"]


def test_other_notifications_are_kept_as_events(tmp_path):
    _, server = serve(tmp_path, {"list.all": lambda params, emit: emit("items", [{"name": "box"}])})
    reply = body(call(server, "execute", {"method": "list.all"}))
    assert reply["events"] == [{"method": "items", "params": [{"name": "box"}]}]


def test_a_long_log_keeps_its_head_and_its_tail():
    lines = ["line %d" % n for n in range(1000)]
    trimmed = mcp_server._trimmed(lines)
    assert trimmed[0] == "line 0"
    assert trimmed[-1] == "line 999"
    assert len(trimmed) == mcp_server._LOG_HEAD + mcp_server._LOG_TAIL + 1
    assert "omitted" in trimmed[mcp_server._LOG_HEAD]


def test_progress_reaches_a_client_that_asked_for_it(tmp_path):
    def testing(params, emit):
        emit("log", {"kind": "process_start", "op": "Test", "package": "//pkg", "item": None})
        emit("log", {"kind": "action_start", "op": "Test", "package": "//pkg", "item": "box"})
        emit("log", {"kind": "action_end", "op": "Test", "package": "//pkg", "item": "box"})
        return None

    _, server = serve(tmp_path, {"test.run": testing})
    seen = []

    async def progress(value, total, message):
        seen.append((value, message))

    call(server, "test", progress_callback=progress)
    assert seen == [(1, "Test //pkg"), (2, "Test //pkg box")]


# --- Pictures and files ------------------------------------------------------


def rendered(extension, data):
    return lambda params, emit: {
        "object": "//pkg:box",
        "format": params["format"],
        "filename": "box." + extension,
        "extension": extension,
        "content": base64.b64encode(data).decode(),
    }


def test_render_returns_the_picture_and_not_its_base64(tmp_path):
    daemon, server = serve(tmp_path, {"render.inline": rendered("png", PNG)})
    result = call(server, "render", {"object": "box"})
    assert not result.is_error
    assert isinstance(result.content[1], ImageContent)
    assert result.content[1].mime_type == "image/png"
    assert base64.b64decode(result.content[1].data) == PNG
    assert base64.b64encode(PNG).decode() not in result.content[0].text
    assert requests(daemon, "render.inline") == [
        {"package": None, "object": "box", "kind": "part", "format": "png", "context": "ctx-1"}
    ]


def test_render_returns_an_svg_as_text(tmp_path):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    _, server = serve(tmp_path, {"render.inline": rendered("svg", svg)})
    result = call(server, "render", {"object": "box", "format": "svg"})
    assert result.content[1].text == svg.decode()


def test_export_writes_the_file_into_the_workspace(tmp_path):
    _, server = serve(tmp_path, {"render.inline": rendered("step", b"ISO-10303-21;")})
    reply = body(call(server, "export", {"object": "box", "format": "step", "path": "out/box.step"}))
    assert reply["ok"] is True
    assert reply["result"]["path"] == "out/box.step"
    assert (tmp_path / "out" / "box.step").read_bytes() == b"ISO-10303-21;"


def test_export_into_a_directory_takes_the_name_partcad_chose(tmp_path):
    (tmp_path / "out").mkdir()
    _, server = serve(tmp_path, {"render.inline": rendered("stl", b"solid box")})
    reply = body(call(server, "export", {"object": "box", "format": "stl", "path": "out"}))
    assert reply["result"]["path"] == "out/box.stl"
    assert (tmp_path / "out" / "box.stl").read_bytes() == b"solid box"


@pytest.mark.parametrize("path", ["/etc/box.step", "../box.step", ".git/box.step", "out/../../box.step"])
def test_export_refuses_a_path_the_agent_may_not_use_and_asks_nothing(tmp_path, path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    daemon, server = serve(workspace, {"render.inline": rendered("step", b"x")})
    result = call(server, "export", {"object": "box", "format": "step", "path": path})
    assert result.is_error
    assert daemon.calls == []
    assert not (tmp_path / "box.step").exists()


def test_export_may_write_where_the_user_allowed(tmp_path):
    workspace, elsewhere = tmp_path / "ws", tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    _, server = serve(workspace, {"render.inline": rendered("step", b"x")}, roots=[str(elsewhere)])
    result = call(server, "export", {"object": "box", "format": "step", "path": str(elsewhere / "box.step")})
    assert not result.is_error
    assert (elsewhere / "box.step").read_bytes() == b"x"


# --- execute -----------------------------------------------------------------


@pytest.mark.parametrize("method", sorted(mcp_server._REFUSED))
def test_execute_refuses_what_is_not_the_agents_to_do(tmp_path, method):
    daemon, server = serve(tmp_path)
    result = call(server, "execute", {"method": method})
    assert result.is_error
    assert method in body(result)["error"]
    assert daemon.calls == []


def test_execute_refuses_a_healthcheck_that_fixes_the_host(tmp_path):
    daemon, server = serve(tmp_path, {"healthcheck": lambda params, emit: {}})
    assert call(server, "execute", {"method": "healthcheck", "params": {"fix": True}}).is_error
    assert daemon.calls == []
    assert not call(server, "execute", {"method": "healthcheck"}).is_error


def test_execute_hands_on_path_parameters_absolute_and_checked(tmp_path):
    daemon, server = serve(tmp_path, {"add.object": lambda params, emit: {"name": "a"}})
    call(server, "execute", {"method": "add.object", "params": {"obj_kind": "part", "path": "parts/a.py"}})
    (request,) = requests(daemon, "add.object")
    assert request["path"] == str((tmp_path / "parts" / "a.py").resolve())

    result = call(server, "execute", {"method": "add.object", "params": {"path": "/etc/passwd"}})
    assert result.is_error
    assert len(requests(daemon, "add.object")) == 1


def test_execute_leaves_a_network_url_alone_and_checks_a_file_url(tmp_path):
    daemon, server = serve(tmp_path, {"add.object": lambda params, emit: {"name": "a"}})
    url = "https://example.com/bolt.step"
    call(server, "execute", {"method": "add.object", "params": {"url": url}})
    assert requests(daemon, "add.object")[-1]["url"] == url
    assert call(server, "execute", {"method": "add.object", "params": {"url": "file:///etc/passwd"}}).is_error


def test_execute_asks_for_no_context_where_none_is_needed(tmp_path):
    daemon, server = serve(tmp_path, {"daemon.status": lambda params, emit: {"uptime": 1}})
    reply = body(call(server, "execute", {"method": "daemon.status"}))
    assert reply["result"] == {"uptime": 1}
    assert [name for name, _ in daemon.calls] == ["daemon.status"]


def test_execute_shows_a_picture_a_result_carries(tmp_path):
    big = PNG + b"\0" * 8192
    _, server = serve(tmp_path, {"render.inline": rendered("png", big)})
    result = call(server, "execute", {"method": "render.inline", "params": {"object": "box", "format": "png"}})
    assert isinstance(result.content[1], ImageContent)
    assert base64.b64decode(result.content[1].data) == big
    assert "attached below" in body(result)["result"]["content"]


def test_execute_of_an_unknown_method_says_so(tmp_path):
    result = call(serve(tmp_path)[1], "execute", {"method": "no.such"})
    assert result.is_error
    assert body(result)["code"] == -32601


def test_list_methods_filters_and_says_which_are_refused(tmp_path):
    methods = {"methods": [{"name": "render.inline", "summary": "Render"}, {"name": "daemon.reset", "summary": "x"}]}
    _, server = serve(tmp_path, {"rpc.discover": lambda params, emit: methods})
    reply = body(call(server, "list_methods", {"filter": "RENDER"}))
    assert reply["result"]["methods"] == [{"name": "render.inline", "summary": "Render"}]
    reply = body(call(server, "list_methods"))
    assert "refused" in reply["result"]["methods"][1]


def test_version_reports_both_ends(tmp_path):
    _, server = serve(tmp_path, {"version": lambda params, emit: {"partcad": "9.9.9"}})
    reply = body(call(server, "version"))
    assert reply["result"] == {"server": mcp_server.__version__, "daemon": "9.9.9"}


# --- The connection ----------------------------------------------------------


def test_a_connection_that_died_while_idle_is_replaced_before_the_request(tmp_path):
    daemon, server = serve(tmp_path, {"lint.run": lambda params, emit: None})
    call(server, "lint")
    daemon.drops.append("context.create")
    result = call(server, "lint")
    assert not result.is_error
    assert daemon.connections == 2
    assert len(requests(daemon, "lint.run")) == 2


def test_a_connection_lost_during_a_request_is_reported_and_not_resent(tmp_path):
    daemon, server = serve(tmp_path, {"add.object": lambda params, emit: {"name": "a"}})
    daemon.drops.append("add.object")
    result = call(server, "execute", {"method": "add.object", "params": {"obj_kind": "part"}})
    assert result.is_error
    assert "may or may not have finished" in body(result)["error"]
    assert len(requests(daemon, "add.object")) == 1
    # And the next call is made on a new connection.
    assert not call(server, "execute", {"method": "add.object"}).is_error
    assert daemon.connections == 2


def test_a_daemon_that_cannot_be_started_is_a_failed_result(tmp_path):
    def unreachable():
        raise RuntimeError("partcad-json-rpc exited with status 1")

    bridge = Bridge(str(tmp_path), connect=unreachable, user_config=StubConfig())
    server = build_server(bridge, PathScope([bridge.root]))
    result = call(server, "lint")
    assert result.is_error
    assert "status 1" in body(result)["error"]


# --- Resources ---------------------------------------------------------------


def test_the_resources_are_the_workspace_and_the_methods(tmp_path):
    def packages(params, emit):
        emit("log", log(20, "//\n//sub"))

    methods = {"methods": [{"name": "version", "summary": "v"}]}
    _, server = serve(tmp_path, {"list.packages": packages, "rpc.discover": lambda params, emit: methods})

    async def read(client):
        listed = await client.list_resources()
        return (
            sorted(str(resource.uri) for resource in listed.resources),
            await client.read_resource("partcad://workspace"),
            await client.read_resource("partcad://methods"),
        )

    uris, workspace, methods_read = using(server, read)
    assert uris == ["partcad://methods", "partcad://workspace"]
    workspace = json.loads(workspace.contents[0].text)
    assert workspace["root"] == os.path.realpath(tmp_path)
    assert workspace["packages"] == ["INFO: //\n//sub"]
    assert json.loads(methods_read.contents[0].text) == methods


def test_no_file_is_a_failure_and_nothing_is_written(tmp_path):
    """`render.inline` answers None when it has logged why, and None is not an empty file."""

    def missing(params, emit):
        emit("log", log(40, "Part //pkg:nope is not found"))
        return None

    (tmp_path / "keep.step").write_bytes(b"what was there")
    _, server = serve(tmp_path, {"render.inline": missing})
    exported = call(server, "export", {"object": "nope", "format": "step", "path": "keep.step"})
    assert exported.is_error
    assert "Part //pkg:nope is not found" in body(exported)["error"]
    assert (tmp_path / "keep.step").read_bytes() == b"what was there"

    rendered_nothing = call(server, "render", {"object": "nope"})
    assert rendered_nothing.is_error
    assert len(rendered_nothing.content) == 1


def test_a_long_daemon_traceback_keeps_only_where_it_failed(tmp_path):
    frames = "\n".join('  File "x.py", line %d, in f' % n for n in range(100))

    def crashing(params, emit):
        raise DaemonError({"code": -32603, "message": "boom", "data": {"traceback": frames + "\nValueError: boom"}})

    _, server = serve(tmp_path, {"info.object": crashing})
    traceback = body(call(server, "info", {"object": "box"}))["data"]["traceback"]
    assert traceback.startswith("...")
    assert traceback.endswith("ValueError: boom")
    assert len(traceback.splitlines()) == mcp_server._TRACEBACK_TAIL + 1
