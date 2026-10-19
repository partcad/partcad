#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc mcp` as an MCP client starts it: a subprocess on stdio, with a real daemon behind it.

What this proves that `test_mcp_server.py` cannot: that the `pc` root command
leaves stdout to the protocol, that the server finds and starts the workspace's
daemon, and that the daemon answers through it.
"""

import os
import shutil
import socket
import sys
import tempfile

import anyio
import pytest
from mcp import Client, StdioServerParameters

import partcad_cli
from partcad_client import daemon

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)

PACKAGE = """\
desc: A package for the MCP server to look at
"""


@pytest.fixture
def short_dirs(monkeypatch):
    # AF_UNIX socket paths cap at ~108 characters, and the daemon's socket is
    # under $HOME; pytest's tmp_path is far too deep for it.
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    workdir = tempfile.mkdtemp(prefix="pcw", dir="/tmp")
    # So that 'daemon.stop_daemon' below finds the socket the server's daemon
    # bound, which is under the same $HOME.
    monkeypatch.setenv("HOME", home)
    try:
        yield home, workdir
    finally:
        daemon.stop_daemon(workdir, wait=10)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)


def server(home, workdir):
    src = os.path.dirname(os.path.dirname(partcad_cli.__file__))
    env = dict(
        os.environ,
        HOME=home,
        PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""),
        PC_TELEMETRY_TYPE="none",
    )
    # `pc` without an installed console script: the same 'cli' the entry point names.
    command = "from partcad_cli.click.command import cli; cli()"
    return StdioServerParameters(command=sys.executable, args=["-c", command, "-p", workdir, "mcp"], env=env, cwd=home)


def test_an_agent_reaches_the_daemon_through_pc_mcp(short_dirs):
    home, workdir = short_dirs
    with open(os.path.join(workdir, "partcad.yaml"), "w", encoding="utf-8") as f:
        f.write(PACKAGE)

    async def session():
        async with Client(server(home, workdir)) as client:
            tools = await client.list_tools()
            version = await client.call_tool("version", {})
            methods = await client.call_tool("list_methods", {"filter": "render"})
            refused = await client.call_tool("export", {"object": "cube", "format": "step", "path": "/tmp/x.step"})
            return tools, version, methods, refused

    tools, version, methods, refused = anyio.run(session)
    assert "execute" in {tool.name for tool in tools.tools}
    assert not version.is_error, version.content[0].text
    assert '"daemon": "%s"' % partcad_cli.__version__ in version.content[0].text
    assert "render.inline" in methods.content[0].text
    assert refused.is_error and "outside the folders" in refused.content[0].text
