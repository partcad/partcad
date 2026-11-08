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
    """The curated tools and 'execute' are all that is served, each with a schema, a title and a description."""
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
            "login",
            "instructions",
            "compare",
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
    """A tool that only reads says so; one that writes, logs in or runs anything does not claim to be read-only."""
    _, server = serve(tmp_path)
    tools = {tool.name: tool.annotations for tool in using(server, lambda client: client.list_tools()).tools}
    for name in ("list_objects", "info", "render", "test", "lint", "bom", "search", "instructions", "compare"):
        assert tools[name].read_only_hint is True, name
    assert tools["export"].read_only_hint is False
    assert tools["export"].destructive_hint is True
    assert tools["execute"].read_only_hint is False
    assert tools["execute"].destructive_hint is True
    assert tools["execute"].idempotent_hint is False
    assert tools["login"].read_only_hint is False


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


def test_a_list_value_is_written_the_way_a_name_spells_it(tmp_path):
    """'{"include": ["UP", "DOWN"]}' is 'include=UP,DOWN', not "include=['UP', 'DOWN']"."""
    daemon, server = serve(tmp_path, {"bom": lambda params, emit: None})
    call(server, "bom", {"object": "panel", "params": {"include": ["UP", "DOWN"]}})
    (request,) = requests(daemon, "bom")
    assert request["params"] == ["include=UP,DOWN"]


@pytest.mark.parametrize(
    "tool, method, arguments",
    [
        ("render", "render.inline", {}),
        ("export", "render.inline", {"format": "step", "path": "out/box.step"}),
        ("test", "test.run", {}),
        ("instructions", "assembly.guide", {}),
    ],
)
def test_every_tool_naming_an_object_takes_its_parameter_values(tmp_path, tool, method, arguments):
    """The values reach the daemon as `pc -p` sends them, and the daemon writes them into the name."""
    answer = rendered("png", PNG) if method == "render.inline" else (lambda params, emit: None)
    daemon, server = serve(tmp_path, {method: answer})
    call(server, tool, {"object": "box", "params": {"width": 10}, **arguments})
    (request,) = requests(daemon, method)
    assert request["object"] == "box"
    assert request["params"] == ["width=10"]


def test_compare_sends_what_pc_compare_json_sends(tmp_path):
    """The 'compare' tool sends the request 'pc compare --json' sends."""
    daemon, server = serve(tmp_path, {"compare.objects": lambda params, emit: {"passed": None}})
    result = call(server, "compare", {"reference": "bracket-v1", "current": "bracket-v2", "surface_distance": 0.5})
    assert not result.is_error
    (request,) = requests(daemon, "compare.objects")
    assert request["object"] == "bracket-v1"
    assert request["current"] == "bracket-v2"
    assert request["surface_distance"] == 0.5
    assert request["max_volume_difference"] is None
    assert request["displacement"] is False
    assert request["max_displacement_difference"] is None
    assert request["worst"] == 10
    assert request["json"] is True


def test_compare_asks_for_the_displacements_as_pc_compare_displacement_does(tmp_path):
    """'displacement' and its limit reach the daemon as the options of 'pc compare' send them."""
    daemon, server = serve(tmp_path, {"compare.objects": lambda params, emit: {"passed": True}})
    arguments = {"reference": "a", "current": "b", "displacement": True, "max_displacement_difference": 2}
    result = call(server, "compare", arguments)
    assert not result.is_error
    (request,) = requests(daemon, "compare.objects")
    assert request["displacement"] is True
    assert request["max_displacement_difference"] == 2


def test_a_comparison_that_does_not_hold_is_a_failed_result(tmp_path):
    """'passed: false' is a failed tool result, with the report kept in it."""
    _, server = serve(tmp_path, {"compare.objects": lambda params, emit: {"passed": False}})
    result = call(server, "compare", {"reference": "a", "current": "b", "max_mass_difference": 2})
    assert result.is_error
    reply = body(result)
    assert reply["ok"] is False
    assert reply["error"] == "b does not hold to a"
    assert reply["result"] == {"passed": False}


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


def rendered(extension, data, attached=True):
    """What `render.inline` answers: the file's bytes, which a daemon sends this
    server as an attachment -- or, from a daemon older than those, base64."""
    return lambda params, emit: {
        "object": "//pkg:box",
        "format": params["format"],
        "filename": "box." + extension,
        "extension": extension,
        "content": data if attached else base64.b64encode(data).decode(),
    }


# A daemon that sends files as bytes, and one from before that, which sends base64.
DAEMONS = pytest.mark.parametrize("attached", [True, False], ids=["bytes", "base64"])


@DAEMONS
def test_render_returns_the_picture_and_not_its_base64(tmp_path, attached):
    daemon, server = serve(tmp_path, {"render.inline": rendered("png", PNG, attached)})
    result = call(server, "render", {"object": "box"})
    assert not result.is_error
    assert isinstance(result.content[1], ImageContent)
    assert result.content[1].mime_type == "image/png"
    assert base64.b64decode(result.content[1].data) == PNG
    assert base64.b64encode(PNG).decode() not in result.content[0].text
    # No 'kind': the daemon looks it up from the name (see 'operations._kind_of').
    assert requests(daemon, "render.inline") == [
        {"package": None, "object": "box", "format": "png", "context": "ctx-1"}
    ]


def test_render_sends_the_kind_it_is_told(tmp_path):
    """Saying the kind skips the daemon's lookup, so it travels as it was said."""
    daemon, server = serve(tmp_path, {"render.inline": rendered("png", PNG)})
    call(server, "render", {"object": "box", "kind": "assembly"})
    assert requests(daemon, "render.inline") == [
        {"package": None, "object": "box", "format": "png", "kind": "assembly", "context": "ctx-1"}
    ]


@pytest.mark.parametrize(
    "tool, arguments",
    [("render", {}), ("export", {"format": "svg", "path": "out/box.svg"})],
)
def test_the_overlays_and_callouts_are_asked_for_as_pc_render_asks(tmp_path, tool, arguments):
    """Each under the name `pc render` sends it, and each name switch only when it is off."""
    daemon, server = serve(tmp_path, {"render.inline": rendered("svg", b"<svg/>")})
    call(
        server,
        tool,
        {
            "object": "box",
            "with_ports": True,
            "with_interfaces": True,
            "with_internals": True,
            "with_component_names": True,
            "with_component_prices": True,
            "with_materials": True,
            "with_port_names": False,
            "with_interface_names": False,
            **arguments,
        },
    )
    (request,) = requests(daemon, "render.inline")
    assert {key: value for key, value in request.items() if key.startswith("with_")} == {
        "with_ports": True,
        "with_interfaces": True,
        "with_internals": True,
        "with_component_names": True,
        "with_component_prices": True,
        "with_materials": True,
        "with_port_names": False,
        "with_interface_names": False,
    }


def test_a_picture_asked_for_nothing_extra_is_the_request_it_always_was(tmp_path):
    """The defaults are not sent: the daemon keeps its cached picture, and an older daemon is asked what it knows."""
    daemon, server = serve(tmp_path, {"render.inline": rendered("png", PNG)})
    call(server, "render", {"object": "box", "with_port_names": True, "with_component_names": False})
    (request,) = requests(daemon, "render.inline")
    assert not [key for key in request if key.startswith("with_")]


def test_the_overlay_and_callout_switches_are_the_ones_pc_render_has(tmp_path):
    """A switch the tool offers is one `pc render` sends, so the two cannot come to mean different things."""
    import inspect

    from partcad_cli.click.commands import render as pc_render

    sent = set(re.findall(r'"(with_[a-z_]+)"', inspect.getsource(pc_render)))
    _, server = serve(tmp_path)
    tools = {tool.name: tool for tool in using(server, lambda client: client.list_tools()).tools}
    for name in ("render", "export"):
        offered = {key for key in tools[name].input_schema["properties"] if key.startswith("with_")}
        assert offered, name
        assert offered <= sent, (name, offered - sent)


@DAEMONS
def test_render_returns_an_svg_as_text(tmp_path, attached):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    _, server = serve(tmp_path, {"render.inline": rendered("svg", svg, attached)})
    result = call(server, "render", {"object": "box", "format": "svg"})
    assert result.content[1].text == svg.decode()


@DAEMONS
def test_export_writes_the_file_into_the_workspace(tmp_path, attached):
    _, server = serve(tmp_path, {"render.inline": rendered("step", b"ISO-10303-21;", attached)})
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


@DAEMONS
def test_execute_shows_a_picture_a_result_carries(tmp_path, attached):
    big = PNG + b"\0" * 8192
    _, server = serve(tmp_path, {"render.inline": rendered("png", big, attached)})
    result = call(server, "execute", {"method": "render.inline", "params": {"object": "box", "format": "png"}})
    assert isinstance(result.content[1], ImageContent)
    assert base64.b64decode(result.content[1].data) == big
    assert "attached below" in body(result)["result"]["content"]


def test_execute_never_shows_bytes_as_text(tmp_path):
    # A file that is not a picture -- a thumbnail of a table, a model -- is said
    # to be there, and how big, rather than written into the JSON as 'b"..."'.
    details = {
        "items": [{"name": "//pkg:box", "thumbnail": b"<svg/>"}],
        "model": {"content": b"glTF", "extension": "glb"},
    }
    _, server = serve(tmp_path, {"manufacturing.details": lambda params, emit: details})
    reply = body(call(server, "execute", {"method": "manufacturing.details", "params": {"objects": []}}))
    assert reply["result"]["items"][0]["thumbnail"] == "<6 bytes>"
    assert reply["result"]["model"]["content"] == "<4 bytes; the export tool writes it to a file>"


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


def test_a_question_without_a_context_is_asked_again_on_a_new_connection(tmp_path):
    """Nothing went ahead of it to find the connection dead, and asking again changes nothing."""
    daemon, server = serve(tmp_path, {"version": lambda params, emit: {"partcad": "9.9.9"}})
    daemon.drops.append("version")
    result = call(server, "version")
    assert not result.is_error, body(result)
    assert daemon.connections == 2
    assert len(requests(daemon, "version")) == 2


def test_a_request_without_a_context_that_does_something_is_not_sent_again(tmp_path):
    daemon, server = serve(tmp_path, {"adhoc.convert": lambda params, emit: None})
    daemon.drops.append("adhoc.convert")
    result = call(server, "execute", {"method": "adhoc.convert"})
    assert result.is_error
    assert "may or may not have finished" in body(result)["error"]
    assert len(requests(daemon, "adhoc.convert")) == 1


# --- Logging in ----------------------------------------------------------------


LOGIN_SPEC = {
    "url": "https://example.com/login",
    "title": "Example",
    "capture": [{"name": "token", "cookie": {"url": "https://example.com/", "name": "t"}}],
    "require": "all",
    "instructions": "An API key from https://example.com/keys does as well.",
}


def _login_daemon(params, emit):
    if params.get("values"):
        if params["values"].get("token") != "good":
            return {"plugin": "//p:repo", "status": "failed", "message": "the site does not take it"}
        return {"plugin": "//p:repo", "status": "done", "parameters": {"token": "good"}, "message": "Logged in"}
    return {"plugin": "//p:repo", "status": "instructions", "spec": LOGIN_SPEC}


def test_login_asks_for_nobody_at_the_screen_and_says_what_the_user_is_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    daemon, server = serve(tmp_path, {"plugin.login": _login_daemon})
    answer = body(call(server, "login", {"plugin": "//p:repo"}))
    assert answer["ok"] is True
    assert requests(daemon, "plugin.login")[0]["non_interactive"] is True
    result = answer["result"]
    assert result["status"] == "instructions" and result["names"] == ["token"]
    assert "https://example.com/login" in result["instructions"]
    assert "An API key from https://example.com/keys" in result["instructions"]
    assert "values {'token': '...'}" in result["instructions"]
    assert not (tmp_path / ".partcad" / "config.yaml").exists()


def test_login_hands_the_values_over_and_keeps_what_works_without_repeating_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    daemon, server = serve(tmp_path, {"plugin.login": _login_daemon})
    answer = body(call(server, "login", {"plugin": "//p:repo", "values": {"token": "good"}}))
    assert answer["ok"] is True, answer
    assert requests(daemon, "plugin.login")[0]["values"] == {"token": "good"}
    assert answer["result"]["saved"] == ["token"]
    assert "good" not in json.dumps(answer["result"])
    import yaml

    assert yaml.safe_load((tmp_path / ".partcad" / "config.yaml").read_text())["parameters"] == {
        "//p:repo": {"token": "good"}
    }


def test_login_that_the_site_refuses_is_a_failed_result(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _, server = serve(tmp_path, {"plugin.login": _login_daemon})
    result = call(server, "login", {"plugin": "//p:repo", "values": {"token": "bad"}})
    assert result.is_error and "the site does not take it" in body(result)["error"]
    assert not (tmp_path / ".partcad" / "config.yaml").exists()


class ConfigWithParameters:
    """A configuration whose parameter overrides are sent, as the CLI's is."""

    def __init__(self):
        self.parameter_config = {"//p:repo": {"formats": "stl"}}

    def to_dict(self):
        return {"parameters": {name: dict(values) for name, values in self.parameter_config.items()}}


def test_what_login_saved_is_sent_with_every_request_after_it(tmp_path, monkeypatch):
    """The server read the configuration file once; what it saved must not wait for a restart."""
    monkeypatch.setenv("HOME", str(tmp_path))
    daemon = FakeDaemon({"plugin.login": _login_daemon, "list.objects": lambda params, emit: None})
    bridge = Bridge(str(tmp_path), connect=daemon.connect, user_config=ConfigWithParameters())
    server = build_server(bridge, PathScope([bridge.root]))

    assert body(call(server, "login", {"plugin": "//p:repo", "values": {"token": "good"}}))["ok"] is True
    call(server, "list_objects", {})
    sent = [params["userConfig"] for name, params in daemon.calls if name == "context.create"][-1]
    assert sent["parameters"]["//p:repo"] == {"formats": "stl", "token": "good"}


def test_login_asked_to_be_interactive_with_no_browser_to_open_answers_with_instructions(tmp_path, monkeypatch):
    """Nothing to open means nobody to send to it: the instructions now, not a wait on a page nobody sees."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from partcad_client import browser as pc_browser

    monkeypatch.setattr(pc_browser, "choose", lambda name=None: None)
    daemon, server = serve(tmp_path, {"plugin.login": _login_daemon})
    answer = body(call(server, "login", {"plugin": "//p:repo", "interactive": True}))
    assert answer["ok"] is True and answer["result"]["status"] == "instructions"
    assert requests(daemon, "plugin.login")[0]["non_interactive"] is True


def test_login_with_a_browser_that_will_not_start_says_so_rather_than_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from partcad_client import browser as pc_browser

    def browser_step(params, emit):
        return {"plugin": "//p:repo", "status": "browser", "spec": LOGIN_SPEC}

    def will_not_start(url, chosen):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pc_browser, "choose", lambda name=None: pc_browser.Browser("chrome", ["/x/chrome"]))
    monkeypatch.setattr(pc_browser, "open_browser", will_not_start)
    _, server = serve(tmp_path, {"plugin.login": browser_step})
    result = call(server, "login", {"plugin": "//p:repo", "interactive": True})
    assert result.is_error and "could not start Google Chrome" in body(result)["error"]
