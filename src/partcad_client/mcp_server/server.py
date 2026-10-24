#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The tools, resources and instructions `pc mcp` serves.

Every tool is a thin wrapper over one daemon method, named beside it, with the
parameters `pc` sends for the same command -- so a tool and the command it
mirrors cannot come to mean different things, and anything a tool does not
cover is one ``execute`` away. What a wrapper adds is a schema, honest
annotations, and a result an agent can read: the daemon's answer, the log it
wrote meanwhile, and an image instead of base64 wherever there is one.
"""

import base64
import json
import logging
from typing import Annotated, Any, Literal, Optional

import anyio
import anyio.from_thread
import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from partcad_client import __version__
from partcad_utils import garage, parameters

from .bridge import Bridge, CallFailed, Outcome
from .sandbox import OutsideScope, PathScope

# What each tool may do, said as the MCP hints say it. Every tool that loads a
# package is open-world: loading one fetches the packages it imports, from git
# or from a registry, the first time it is asked for.
_READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
_LOCAL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
_WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True)
_ANYTHING = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

# Daemon methods `execute` refuses, and why. Each would act on something that
# is not the agent's: the daemon every other client of this workspace shares,
# the user's own configuration, or this server's connection.
_REFUSED = {
    "daemon.reset": "it drops the daemon's state for every client of this workspace; ask the user to run "
    "`pc daemon reset`",
    "daemon.set.telemetry": "it changes the user's own configuration; ask the user to run `pc daemon set telemetry`",
    "daemon.stop": "it stops the daemon every client of this workspace shares; ask the user to run `pc daemon stop`",
    "daemon.settings": "it restarts the daemon with other settings, under every client of this workspace",
    "daemon.debug": "it is the editor extension's question to a daemon it is debugging",
    "log.mode": "it changes how the daemon writes to this server's own connection",
    "context.create": "this server creates the workspace's context itself, before every call",
}

# Methods that work without a package context. Asking for one first would make
# them fail in a directory that is not a package yet -- which is exactly where
# `version` and `list_methods` are most likely to be asked.
_CONTEXT_FREE = {
    "rpc.discover",
    "version",
    "adhoc.convert",
    "adhoc.render",
    "cae.defaults",
    "daemon.status",
    "daemon.status.config",
    "daemon.status.env",
    "healthcheck",
}

# The parameters of a daemon request that name a file or a directory on this
# machine, which `execute` checks against the scope and hands on absolute.
_PATH_PARAMS = ("path", "output_dir", "source", "input_filename", "output_filename", "url")

# What an MCP client can show as an image. SVG is text and goes back as such;
# everything else is bytes an agent should write to a file rather than read.
_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}

# A log a recursive run writes can be thousands of lines. The head says what
# was asked and the tail how it ended; errors are listed separately in full.
_LOG_HEAD = 40
_LOG_TAIL = 300
_TRACEBACK_TAIL = 12

# Base64 longer than this in a result is a file, not something to read.
_INLINE_LIMIT = 4096
# And an SVG longer than this is better written to a file and looked at there.
_SVG_LIMIT = 200_000

ObjectKind = Literal["part", "assembly", "scene", "sketch"]
TestKind = Literal["part", "assembly", "scene", "sketch", "interface"]
InfoKind = Literal["part", "assembly", "scene", "sketch", "interface", "software"]

# A name is one object of its package whatever its kind, so the daemon looks the
# kind up when it is not given; saying it only saves the lookup.
_KIND = "What the object is. Looked up from its name when left out, which is the usual way to call this."
ListKind = Literal["packages", "parts", "sketches", "assemblies", "scenes", "interfaces", "materials", "software"]
SearchKind = Literal["parts", "sketches", "assemblies", "scenes", "interfaces", "packages"]

_OBJECT = (
    "The object: its name in the package, or fully qualified as '//package/path:name'. A name with '...' in its "
    "package ('//pub/examples...:bolt') reaches every package below that one."
)
ObjectName = Annotated[str, Field(description=_OBJECT)]
SomeObjectName = Annotated[Optional[str], Field(description=_OBJECT + " The package itself when left out.")]
PackageName = Annotated[
    Optional[str],
    Field(
        description="The package, as '//package/path' or relative to the workspace's own; the workspace's own "
        "package when left out."
    ),
]
Parameters = Annotated[
    Optional[dict[str, Any]],
    Field(description="Values for the object's declared parameters, by name ('-p name=value' on the command line)."),
]


def instructions(bridge: Bridge, scope: PathScope) -> str:
    return (
        "PartCAD documents manufacturable products as code. A package is a directory with a partcad.yaml that "
        "declares parts, sketches, assemblies (ASSY files), scenes and interfaces, each made by a script "
        "(build123d, CadQuery, OpenSCAD, ...) or read from a file (STEP, STL, ...), and imports other packages. "
        "Objects are named '//package/path:name'; a bare name is in the workspace's own package. An object that "
        "declares parameters is asked for with particular values through a tool's params ({name: value}), which "
        "is the same as naming it 'name;param=value,...'. "
        "Start with list_objects (kind=packages for the package tree) and info; look at an object with render, "
        "which returns an image; check it against its declared requirements with test; write STEP, STL, 3MF and "
        "the rest with export. To create or change an object, edit partcad.yaml and its script with your own file "
        "tools -- the daemon reloads what changed -- then render and test again. Everything else PartCAD does "
        "(bom, instructions, cae, cam, simulations, add, import, convert, install) is a daemon method: "
        "list_methods names them and execute runs one. Results carry the daemon's log; when ok is false, the "
        "errors say why. "
        "Workspace: %s. Files reachable: %s." % (bridge.root, scope.describe())
    )


def build_server(bridge: Bridge, scope: PathScope) -> MCPServer:
    # 'MCPServer()' calls 'logging.basicConfig()', which configures the root
    # logger -- this process's, not the SDK's -- with a Rich handler, and every
    # library's warnings then come out of `pc mcp` drawn as boxed tables. The
    # root logger is put back the way `pc` left it.
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    server = MCPServer(
        name="partcad",
        title="PartCAD",
        description="Inspect, render, test and export the parts and assemblies of a PartCAD workspace",
        instructions=instructions(bridge, scope),
        website_url="https://partcad.org",
        version=__version__,
        log_level="WARNING",
    )
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
    root.setLevel(level)

    async def call(ctx: Context, method: str, params: dict, needs_context: bool = True) -> Outcome:
        """Run ``method`` on the daemon in a worker thread, passing its progress on."""
        started = 0

        def on_progress(message: str) -> None:
            nonlocal started
            started += 1
            try:
                anyio.from_thread.run(ctx.report_progress, started, None, message)
            except Exception:  # pylint: disable=broad-except
                pass  # a client that went away mid-call is not this call's failure

        return await anyio.to_thread.run_sync(lambda: bridge.call(method, params, needs_context, on_progress))

    async def run(ctx: Context, method: str, params: dict, needs_context: bool = True) -> CallToolResult:
        try:
            return report(await call(ctx, method, params, needs_context))
        except CallFailed as e:
            return report(e.outcome, failure=e)

    @server.tool(title="List objects", annotations=_READS)
    async def list_objects(
        ctx: Context,
        kind: Annotated[ListKind, Field(description="What to list.")] = "parts",
        package: PackageName = None,
        recursive: Annotated[bool, Field(description="Also list the packages below this one.")] = False,
    ) -> CallToolResult:
        """List the packages, parts, sketches, assemblies, scenes, interfaces, materials or software of a package.

        `pc list <kind>`. The listing is in the log of the result.
        """
        if kind == "packages":
            return await run(ctx, "list.packages", {"package": package, "recursive": recursive})
        return await run(ctx, "list.objects", {"kind": kind, "package": package, "recursive": recursive})

    @server.tool(title="Show an object's declaration", annotations=_READS)
    async def info(
        ctx: Context,
        object: SomeObjectName = None,
        kind: Annotated[Optional[InfoKind], Field(description=_KIND)] = None,
        package: PackageName = None,
        params: Parameters = None,
    ) -> CallToolResult:
        """Show an object's configuration, parameters and properties, or the package's when no object is named.

        `pc info`.
        """
        request = {"package": package, "object": object, "params": _assignments(params), **_kind_flag(kind)}
        return await run(ctx, "info.object", request)

    @server.tool(title="Look at an object", annotations=_READS)
    async def render(
        ctx: Context,
        object: ObjectName,
        kind: Annotated[Optional[ObjectKind], Field(description=_KIND)] = None,
        format: Annotated[
            str,
            Field(
                description="The file type: png (the default) and jpg come back as an image, svg as text; "
                "anything else, such as pdf or dxf, is better written with export."
            ),
        ] = "png",
        package: PackageName = None,
        options_package: Annotated[
            Optional[str],
            Field(description="A package whose 'render:' section implements the file type, such as a drawing style."),
        ] = None,
        params: Parameters = None,
    ) -> CallToolResult:
        """Render one part, assembly, scene or sketch and return the picture.

        `pc render`, returned instead of written. The first render of an object builds it, which can take minutes.
        """
        request = {"package": package, "object": object, "format": format, **_kind(kind)}
        if options_package:
            request["options_package"] = options_package
        if params:
            request["params"] = _assignments(params)
        try:
            outcome = _produced_a_file(await call(ctx, "render.inline", request), object, format)
        except CallFailed as e:
            return report(e.outcome, failure=e)
        return report(outcome, content=_file_content(outcome))

    @server.tool(title="Write an object to a file", annotations=_WRITES)
    async def export(
        ctx: Context,
        object: ObjectName,
        format: Annotated[str, Field(description="The file type: step, stl, 3mf, obj, gltf, brep, png, svg, ...")],
        path: Annotated[
            str,
            Field(
                description="Where to write it, relative to the workspace: a file, or an existing directory to "
                "write it into under the name PartCAD chooses. Overwrites what is there."
            ),
        ],
        kind: Annotated[Optional[ObjectKind], Field(description=_KIND)] = None,
        package: PackageName = None,
        options_package: Annotated[
            Optional[str],
            Field(description="A package whose 'export:' or 'render:' section implements the file type."),
        ] = None,
        params: Parameters = None,
    ) -> CallToolResult:
        """Export or render one object to a file in the workspace.

        `pc export` / `pc render` for one object, written where the agent says.
        """
        try:
            target = scope.check(path)
        except OutsideScope as e:
            return _refusal(str(e))
        request = {"package": package, "object": object, "format": format, **_kind(kind)}
        if options_package:
            request["options_package"] = options_package
        if params:
            request["params"] = _assignments(params)
        try:
            outcome = _produced_a_file(await call(ctx, "render.inline", request), object, format)
        except CallFailed as e:
            return report(e.outcome, failure=e)
        produced = outcome.result
        if target.is_dir() or path.endswith(("/", "\\")):
            target = scope.check(str(target / produced.get("filename", "export." + format)))
        data = base64.b64decode(produced.get("content") or "")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        outcome.result = {"object": produced.get("object"), "format": format, "path": scope.relative(target)}
        outcome.result["bytes"] = len(data)
        return report(outcome)

    @server.tool(title="Test objects", annotations=_READS)
    async def test(
        ctx: Context,
        object: Annotated[
            Optional[str], Field(description="The object to test; every object of the package when left out.")
        ] = None,
        kind: Annotated[Optional[TestKind], Field(description=_KIND)] = None,
        package: PackageName = None,
        recursive: Annotated[bool, Field(description="Also test the packages below this one.")] = False,
        params: Parameters = None,
    ) -> CallToolResult:
        """Check objects against the requirements and tests they declare.

        `pc test`. ok is false when any check failed, and the errors say which.
        """
        request = {"package": package, "object": object, "recursive": recursive, **_kind_flag(kind)}
        if params:
            request["params"] = _assignments(params)
        return await run(ctx, "test.run", request)

    @server.tool(title="Lint a package", annotations=_READS)
    async def lint(
        ctx: Context,
        package: PackageName = None,
        recursive: Annotated[bool, Field(description="Also lint the packages below this one.")] = False,
    ) -> CallToolResult:
        """Check a package's partcad.yaml, ASSY files and scripts for mistakes.

        `pc lint`.
        """
        return await run(ctx, "lint.run", {"package": package, "recursive": recursive})

    @server.tool(title="Bill of materials", annotations=_READS)
    async def bom(
        ctx: Context, object: ObjectName, package: PackageName = None, params: Parameters = None
    ) -> CallToolResult:
        """What has to be bought or made to build a part, an assembly or a scene.

        `pc bom --json`.
        """
        request = {"package": package, "object": object, "params": _assignments(params), "json": True}
        return await run(ctx, "bom", request)

    @server.tool(title="Search objects", annotations=_READS)
    async def search(
        ctx: Context,
        keyword: Annotated[str, Field(description="Words to look for in names and descriptions.")] = "",
        kind: Annotated[SearchKind, Field(description="What to look for.")] = "parts",
        package: Annotated[
            Optional[str],
            Field(description="Where to look; the workspace root, '//', when left out. '//pub' is the public catalog."),
        ] = None,
        recursive: Annotated[
            bool,
            Field(
                description="Also look in the packages below. Below '//pub' that is the whole public catalog, "
                "fetched over the network the first time."
            ),
        ] = False,
        interface: Annotated[
            Optional[str],
            Field(description="Only objects that implement this interface, or one derived from it."),
        ] = None,
    ) -> CallToolResult:
        """Find parts, sketches, assemblies, scenes, interfaces or packages by keyword or by interface.

        `pc search`. The matches are in the log of the result.
        """
        request = {"kind": kind, "package": package, "recursive": recursive, "keyword": keyword}
        if interface:
            request["interface"] = interface
        return await run(ctx, "search.objects", request)

    @server.tool(name="instructions", title="Assembly instructions", annotations=_READS)
    async def assembly_instructions(
        ctx: Context,
        object: ObjectName,
        package: PackageName = None,
        subassemblies: Annotated[bool, Field(description="Also write the steps of the subassemblies.")] = False,
        params: Parameters = None,
    ) -> CallToolResult:
        """The step-by-step build of an assembly: what goes where, in which order, with which parts.

        `pc instructions`, as data. The user's Build vs Buy choices on this machine are applied.
        """
        request = {"package": package, "object": object, "subassemblies": subassemblies, "bvb": garage.load_all_bvb()}
        if params:
            request["params"] = _assignments(params)
        return await run(ctx, "assembly.guide", request)

    @server.tool(title="PartCAD version", annotations=_LOCAL)
    async def version(ctx: Context) -> CallToolResult:
        """The version of this server and of the daemon serving the workspace, which should be the same."""
        try:
            outcome = await call(ctx, "version", {}, needs_context=False)
        except CallFailed as e:
            return report(e.outcome, failure=e)
        daemon = outcome.result.get("partcad") if isinstance(outcome.result, dict) else outcome.result
        outcome.result = {"server": __version__, "daemon": daemon}
        return report(outcome)

    @server.tool(title="List daemon methods", annotations=_LOCAL)
    async def list_methods(
        ctx: Context,
        filter: Annotated[
            Optional[str], Field(description="Only methods whose name or summary contains this, ignoring case.")
        ] = None,
    ) -> CallToolResult:
        """The methods the PartCAD daemon serves, each with a one-line summary, for use with execute."""
        try:
            outcome = await call(ctx, "rpc.discover", {}, needs_context=False)
        except CallFailed as e:
            return report(e.outcome, failure=e)
        methods = (outcome.result or {}).get("methods", [])
        if filter:
            needle = filter.lower()
            methods = [
                m for m in methods if needle in m.get("name", "").lower() or needle in m.get("summary", "").lower()
            ]
        outcome.result = {
            "methods": [dict(m, refused=_REFUSED[m["name"]]) if m.get("name") in _REFUSED else m for m in methods]
        }
        return report(outcome)

    @server.tool(title="Run a daemon method", annotations=_ANYTHING)
    async def execute(
        ctx: Context,
        method: Annotated[str, Field(description="The method, as list_methods names it, such as 'cae.analyze'.")],
        params: Annotated[
            Optional[dict[str, Any]],
            Field(
                description="Its parameters, as `pc` sends them: 'package' and 'object' for what it acts on, "
                "and 'params' for the values of the object's own parameters, as {name: value} or as "
                "['name=value', ...] ('-p name=value' on the command line, the same as naming the object "
                "'object;name=value'). The workspace's context is added for you. Paths are relative "
                "to the workspace."
            ),
        ] = None,
    ) -> CallToolResult:
        """Run any PartCAD daemon method -- everything the command line can do, and what the IDE asks for.

        The result carries the method's answer and its log.
        """
        if method in _REFUSED:
            return _refusal("'%s' is not available to an agent: %s." % (method, _REFUSED[method]))
        request = dict(params or {})
        if method == "healthcheck" and request.get("fix"):
            return _refusal(
                "A healthcheck that fixes the host is the user's to run: ask them to run `pc healthcheck --fix`."
            )
        try:
            for key in _PATH_PARAMS:
                if key in request:
                    request[key] = _checked(scope, key, request[key])
        except OutsideScope as e:
            return _refusal(str(e))
        try:
            outcome = await call(ctx, method, request, needs_context=method not in _CONTEXT_FREE)
        except CallFailed as e:
            return report(e.outcome, failure=e)
        return report(outcome)

    @server.resource(
        "partcad://workspace",
        name="workspace",
        title="The PartCAD workspace",
        description="Where the workspace is, which files an agent may use, and its package tree.",
        mime_type="application/json",
    )
    async def workspace() -> str:
        body = {"workspace": bridge.workspace, "root": bridge.root, "files": scope.describe()}
        try:
            outcome = await anyio.to_thread.run_sync(
                lambda: bridge.call("list.packages", {"package": "//", "recursive": True})
            )
            body["packages"] = outcome.log
        except CallFailed as e:
            body["error"] = str(e)
        return json.dumps(body, indent=2)

    @server.resource(
        "partcad://methods",
        name="methods",
        title="PartCAD daemon methods",
        description="Every method execute can run, with a one-line summary.",
        mime_type="application/json",
    )
    async def methods() -> str:
        try:
            outcome = await anyio.to_thread.run_sync(lambda: bridge.call("rpc.discover", {}, needs_context=False))
        except CallFailed as e:
            return json.dumps({"error": str(e)}, indent=2)
        return json.dumps(outcome.result, indent=2)

    return server


def report(outcome: Outcome, failure: Optional[CallFailed] = None, content=()) -> CallToolResult:
    """The tool result for a daemon request: what it answered and what it said.

    One JSON text block an agent can read -- ``ok``, then the error, the result,
    the error lines and the log -- followed by any image the result carried.
    """
    images = list(content)
    body = {"ok": failure is None and not outcome.errors}
    if failure is not None:
        body["error"] = str(failure)
        if failure.code is not None:
            body["code"] = failure.code
        if failure.data is not None:
            body["data"] = _shrink(_without_long_traceback(failure.data), images)
    if outcome.result is not None:
        body["result"] = _shrink(outcome.result, images)
    if outcome.errors:
        body["errors"] = outcome.errors
    if outcome.log:
        body["log"] = _trimmed(outcome.log)
    if outcome.events:
        body["events"] = _shrink(outcome.events, images)
    text = TextContent(type="text", text=json.dumps(body, indent=2, default=str))
    return CallToolResult(content=[text, *images], is_error=not body["ok"])


def _refusal(message: str) -> CallToolResult:
    """A call this server will not make, said as a failed result rather than a protocol error."""
    body = {"ok": False, "error": message}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body, indent=2))], is_error=True)


def _produced_a_file(outcome: Outcome, name: str, fmt: str) -> Outcome:
    """``outcome``, if `render.inline` answered with a file; :class:`CallFailed` if it did not.

    It answers ``None`` rather than an error when it has *logged* why -- an
    object that is not found, a package that did not load -- and a ``None``
    taken for a file would be an empty one written over whatever was at the
    path, reported with nothing but a log line to say it is empty.
    """
    if isinstance(outcome.result, dict) and outcome.result.get("content"):
        return outcome
    reason = outcome.errors[-1] if outcome.errors else "the daemon returned no file"
    raise CallFailed("No %s file was produced for %s: %s" % (fmt, name, reason), outcome)


def _file_content(outcome: Outcome) -> list:
    """What to show of the file `render.inline` returned: the picture, or the SVG's text."""
    produced = outcome.result if isinstance(outcome.result, dict) else {}
    extension = str(produced.get("extension", "")).lower()
    data = produced.get("content")
    if not data:
        return []
    if extension in _IMAGE_TYPES:
        # Taken out of the JSON here so that the text block says what it was
        # rather than carrying it a second time.
        produced["content"] = "<the %s image below, %d bytes>" % (extension, len(data) * 3 // 4)
        return [ImageContent(type="image", data=data, mime_type=_IMAGE_TYPES[extension])]
    if extension == "svg" and len(data) * 3 // 4 <= _SVG_LIMIT:
        produced["content"] = "<the SVG below>"
        return [TextContent(type="text", text=base64.b64decode(data).decode("utf-8", errors="replace"))]
    return []


def _shrink(value, images: list):
    """``value`` with every embedded file taken out of it.

    A result that carries a file -- ``{filename, extension, content}``, base64
    -- has it replaced by a note, and an image among them is attached as an
    image instead, so that `execute` of a method that returns a picture shows
    the picture. Anything else that long is cut, since no agent reads a megabyte
    of base64 and every one pays for it.
    """
    if isinstance(value, dict):
        extension = str(value.get("extension", "")).lower()
        shrunk = {}
        for key, item in value.items():
            if key == "content" and isinstance(item, str) and len(item) > _INLINE_LIMIT:
                size = len(item) * 3 // 4
                if extension in _IMAGE_TYPES:
                    images.append(ImageContent(type="image", data=item, mime_type=_IMAGE_TYPES[extension]))
                    shrunk[key] = "<a %s image, %d bytes, attached below>" % (extension, size)
                else:
                    shrunk[key] = "<%d bytes of base64; the export tool writes it to a file>" % size
            else:
                shrunk[key] = _shrink(item, images)
        return shrunk
    if isinstance(value, list):
        return [_shrink(item, images) for item in value]
    if isinstance(value, str) and len(value) > 4 * _INLINE_LIMIT:
        return value[:_INLINE_LIMIT] + "... <%d more characters>" % (len(value) - _INLINE_LIMIT)
    return value


def _without_long_traceback(data):
    """The daemon's error data, with a traceback cut to the frames that say where it failed.

    The daemon attaches the whole traceback of an exception it did not expect,
    which is dozens of frames of dispatcher and telemetry wrappers before the one
    that matters; the last few are where it went wrong and what was raised.
    """
    if isinstance(data, dict) and isinstance(data.get("traceback"), str):
        lines = data["traceback"].rstrip().splitlines()
        if len(lines) > _TRACEBACK_TAIL:
            data = dict(data, traceback="\n".join(["..."] + lines[-_TRACEBACK_TAIL:]))
    return data


def _trimmed(log: list) -> list:
    if len(log) <= _LOG_HEAD + _LOG_TAIL:
        return log
    omitted = len(log) - _LOG_HEAD - _LOG_TAIL
    return log[:_LOG_HEAD] + ["... %d lines omitted ..." % omitted] + log[-_LOG_TAIL:]


def _checked(scope: PathScope, key: str, value):
    """A path parameter, checked and made absolute; a URL that is not a file is left alone."""
    if isinstance(value, list):
        return [_checked(scope, key, item) for item in value]
    if not isinstance(value, str):
        return value
    if key == "url":
        if "://" in value and not value.startswith("file://"):
            return value  # a package or a file on the network, which the daemon fetches
        if value.startswith("file://"):
            from urllib.parse import unquote, urlparse

            return scope.check(unquote(urlparse(value).path)).as_uri()
    return str(scope.check(value))


def _assignments(params: Optional[dict]) -> list:
    """``{"width": 10}`` as the ``["width=10"]`` that `pc -p` sends.

    The daemon reads a mapping as well, but a list is what every daemon has read,
    so a server talking to an older one still gets its values across. Each value
    is written the way an object's name spells it: a flag as ``true``, a list
    joined by commas.
    """
    return ["%s=%s" % (key, parameters.format_assignment(value)) for key, value in (params or {}).items()]


def _kind_flag(kind: Optional[str]) -> dict:
    """The one flag `pc` sets for a kind of object, or none to have the daemon look the kind up.

    A part has no flag of its own -- `pc` never needed one -- so a part said is a
    part looked up, which is the first thing the lookup asks after anyway.
    """
    return {} if kind in (None, "part") else {kind: True}


def _kind(kind: Optional[str]) -> dict:
    """``kind`` for a method that takes it by that name, or nothing to have it looked up."""
    return {} if kind is None else {"kind": kind}
