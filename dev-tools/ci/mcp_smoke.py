#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Drive an MCP server over stdio as a client would, and check it answers.

    python3 dev-tools/ci/mcp_smoke.py --render cube -- docker run -i --rm ... ghcr.io/partcad/partcad mcp

What `dev-tools/ci/test-partcad-image.sh` runs against the PartCAD image: the
command after `--` is started exactly as an MCP client starts a server, and
spoken to in newline-delimited JSON-RPC on its standard input and output. It
initializes, lists the tools, and calls two of them -- `list_objects`, which
starts the daemon inside the container, and with `--render`, `render`, which
builds the object in a sandbox and must come back as a picture.

The standard library only, so it runs on a CI runner with nothing installed.
"""

import argparse
import json
import subprocess
import sys
import threading

# How long a reply may take. A render in a sandbox that the volume already
# holds is seconds; the first one builds the sandbox, which is minutes.
TIMEOUT = 1800


class Server:
    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.next_id = 0

    def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        return self._reply(self.next_id, method)

    def _reply(self, wanted, method):
        answer = {}

        def read():
            for line in self.process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    # Anything on stdout that is not the protocol breaks every
                    # real client, so it is a failure here too.
                    answer["error"] = "not JSON-RPC on stdout: %r" % line[:200]
                    return
                if message.get("id") == wanted:
                    answer["message"] = message
                    return

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(TIMEOUT)
        if "error" in answer:
            sys.exit("mcp: %s" % answer["error"])
        if "message" not in answer:
            sys.exit("mcp: no answer to %s within %ds (exit status %s)" % (method, TIMEOUT, self.process.poll()))
        message = answer["message"]
        if "error" in message:
            sys.exit("mcp: %s failed: %s" % (method, message["error"]))
        return message["result"]

    def close(self):
        self.process.stdin.close()
        try:
            return self.process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.process.kill()
            sys.exit("mcp: the server did not exit when its standard input closed")


def _text(result):
    return "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render", help="An object of the served package to render through the 'render' tool")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="The server's command line, after '--'")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no server command given")

    server = Server(command)
    initialized = server.request(
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "partcad-smoke", "version": "0"}},
    )
    print("mcp: initialized %s" % json.dumps(initialized.get("serverInfo")))
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    tools = sorted(tool["name"] for tool in server.request("tools/list").get("tools", []))
    print("mcp: %d tools: %s" % (len(tools), ", ".join(tools)))
    for needed in ("list_objects", "render", "export", "execute"):
        if needed not in tools:
            sys.exit("mcp: the server has no '%s' tool" % needed)

    listed = server.request("tools/call", {"name": "list_objects", "arguments": {}})
    if listed.get("isError"):
        sys.exit("mcp: list_objects failed:\n%s" % _text(listed))
    print("mcp: list_objects answered (%d characters)" % len(_text(listed)))

    if args.render:
        rendered = server.request("tools/call", {"name": "render", "arguments": {"object": args.render}})
        if rendered.get("isError"):
            sys.exit("mcp: render %s failed:\n%s" % (args.render, _text(rendered)))
        images = [item for item in rendered.get("content", []) if item.get("type") == "image"]
        if not images or images[0].get("mimeType") != "image/png" or not images[0].get("data"):
            sys.exit("mcp: render %s came back without a PNG: %s" % (args.render, json.dumps(rendered)[:500]))
        print("mcp: render %s came back as a PNG of %d base64 characters" % (args.render, len(images[0]["data"])))

    status = server.close()
    if status != 0:
        sys.exit("mcp: the server exited with status %s" % status)
    print("mcp: ok")


if __name__ == "__main__":
    main()
