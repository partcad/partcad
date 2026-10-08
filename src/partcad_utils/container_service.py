#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The service inside every container PartCAD starts: run a command, exchange files.

One implementation of one protocol, and it is the only way PartCAD talks to a
container. `partcad_utils.containers` copies this file into every container it
creates, before the container starts, and runs it as the container's command --
so whatever image a sandbox, a KiCad import, a plugin's `container:` or an
`open:` application runs in, the thing answering is this file, at the version of
the PartCAD that started it. An image that carries an older copy of its own
cannot answer in an older dialect: the copy it carries is not the one running.

That is also why it imports nothing but the standard library and keeps to the
syntax of old interpreters. It has to start on whatever `python3` an image
happens to have -- PartCAD's own images, KiCad's, and the community images the
`open:` applications run in -- and a dependency to install first is a dependency
an image without pip cannot satisfy. The web framework this used to be written
against was the whole of its requirements file.

The protocol is JSON-RPC 2.0 over HTTP, one method, `execute`::

    POST /jsonrpc
    {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {
        "command": ["kicad-cli", "pcb", "export", "step", "/w/board.kicad_pcb", "-o", "/w/board.step"],
        "stdin": "<base64>" | null,
        "cwd": "/w" | null,
        "input_files": {"/w/board.kicad_pcb": "<base64>"},
        "output_files": ["/w/board.step"],
        "input_dirs": {"/w/pkg": "<base64 tar.gz>"},
        "output_dirs": ["/w/pkg"]
    }}

Every path in a request is the *caller's*. When the caller and the container
share a filesystem -- the `mount` transfer mode -- none of the payloads are sent
and the paths simply exist in here. When they do not -- `upload` -- the payloads
carry the files, and every argument naming one is rewritten to where this
service put it before the command runs:

* ``input_files`` are written into a directory of this call's own, and an
  argument equal to one of the names is rewritten to it.
* ``input_dirs`` are extracted, and an argument *below* one of them -- matched by
  prefix, longest first, separator-agnostic -- is rewritten into the extraction.
  So is ``cwd``. A script imports its siblings, which is why a directory travels
  whole rather than as the one file a command names.
* ``output_files`` are names the command is expected to write. An argument equal
  to one is pointed into this call's directory, and whatever is there after the
  command ends is sent back under the caller's name. A name that is also an
  input is an *in-place edit* -- an application opening a file and saving it --
  and it comes back too.
* ``output_dirs`` are directories to send back whole after the command, packed
  the way ``input_dirs`` are. One that was also sent comes back with whatever
  the command changed in it; one that was not is created empty first, for a
  command that writes a directory of results.

What can be run is the allowlist: ``PC_CONTAINER_ALLOWED_COMMANDS``, a JSON object
mapping a name to an absolute path -- or to ``null``, meaning "whatever that name
resolves to on this container's PATH", for an application whose install
location is the image's business. Fixed when the container is created and read
once here, so that no request can widen it. The interpreter of an environment
under ``PC_CONTAINER_SANDBOX_ROOT`` may run too; see `_sandbox_interpreter`.

``PC_CONTAINER_TOKEN``, when set, is a bearer token every request must carry. A
container PartCAD starts for its own use on this machine listens on loopback and
has one anyway, since it costs nothing; one reached across a network needs it.

``GET /`` answers without authentication and without running anything, so that
whoever started the container can tell when it is ready: Docker reports a
container running some time before the process inside it is listening.
"""

import base64
import contextlib
import gzip
import hmac
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# What `GET /` reports, and what a client may ask of a server before relying on
# one of the additions below. 1 is the service as it was before them; 2 sends
# in-place edits back, sends `output_dirs`, resolves a null allowlist entry on
# PATH and rewrites `cwd`; 3 holds a `lock` around a command.
PROTOCOL = 3

# Where the service listens unless told otherwise. Not a request parameter: what
# answers inside a container is part of the container's identity, and a request
# naming a port would be a request choosing what to talk to.
DEFAULT_PORT = 5000

log = logging.getLogger("partcad.container_service")


class ExecuteError(Exception):
    """A request this service refuses, as the JSON-RPC error it becomes."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


# The commands a container may run unless it is told otherwise. Kept because a
# KiCad image started by hand, without PartCAD setting the allowlist, has always
# been able to run `kicad-cli`; everything PartCAD starts says what it needs.
DEFAULT_COMMANDS = {
    "kicad-cli": "/usr/bin/kicad-cli",
    "cat": "/usr/bin/cat",
    "ls": "/usr/bin/ls",
}


def load_allowlist(environ=None):
    """The commands this container may run, by name: a path, or None for "look it up on PATH"."""
    environ = os.environ if environ is None else environ
    allowed = dict(DEFAULT_COMMANDS)
    raw = environ.get("PC_CONTAINER_ALLOWED_COMMANDS", "")
    if raw.strip():
        for name, path in json.loads(raw).items():
            allowed[str(name)] = None if path is None else str(path)
    return allowed


ALLOWED_COMMANDS = load_allowlist()

# Where the environments of a sandbox that lives *in* the container are kept.
# Told to the container by whoever started it, because where they live is that
# party's decision rather than the image's; the default is the same path, for a
# container somebody started by hand.
SANDBOX_ROOT = os.environ.get("PC_CONTAINER_SANDBOX_ROOT", "/pc-sandbox")


def _sandbox_interpreter(name):
    """`name`, if it is the interpreter of an environment under the sandbox root.

    The allowlist names what an image was *built* to run, and an environment
    built at run time cannot be in it: its path carries a Python version nobody
    told the image about. So this is the second way in, and a narrow one -- the
    file has to be called `python` or `python3`, sit in a `bin` directory under
    the sandbox root, and already exist.

    Not a widening of what a caller can do: an image whose allowlist already
    holds an interpreter lets a caller run whatever Python it likes through
    that, and everything under the sandbox root was put there by that
    interpreter.
    """
    # `os.path.isabs` rather than a leading "/": this runs inside a Linux image,
    # but the test suite runs it in process on whatever machine the suite is on,
    # and on Windows every path it builds begins with a drive letter.
    if not isinstance(name, str) or not os.path.isabs(name):
        return None
    root = os.path.normpath(SANDBOX_ROOT)
    path = os.path.normpath(name)
    if not path.startswith(root + os.sep):
        return None
    if os.path.basename(path) not in ("python", "python3"):
        return None
    if os.path.basename(os.path.dirname(path)) != "bin":
        return None
    # The shape is not enough: a path that looks right and is not there would be
    # reported as a command that failed rather than as one that never ran.
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        return None
    return path


def resolve_command(name, allowed=None):
    """The executable `name` may run as here, or None if it may not run at all."""
    allowed = ALLOWED_COMMANDS if allowed is None else allowed
    if name in allowed:
        path = allowed[name]
        if path is None:
            # The image decides where its application is installed; the
            # container was told only that this name may run.
            return shutil.which(name)
        return path
    return _sandbox_interpreter(name)


def _within(path, prefix):
    """The parts of `path` below `prefix`, or None if it is not below it.

    Separator-agnostic in both directions, and that is the whole point of it.
    The paths a caller sends are the caller's: a Windows client names `D:\\pkg`
    and `D:\\pkg\\solve.py`, and this server runs inside a Linux image where
    `os.sep` is `/`. Matching on `os.sep` alone left every one of those
    unsubstituted, so the command kept naming a directory on another machine.

    Returns `()` for the prefix itself, so "it is the directory" and "it is not
    below it" stay distinguishable.
    """
    if path == prefix:
        return ()
    for separator in ("/", "\\"):
        if path.startswith(prefix + separator):
            tail = path[len(prefix) + 1 :]
            return tuple(part for part in tail.replace("\\", "/").split("/") if part)
    return None


def _relocate(path, directories):
    """`path` rewritten into whichever of `directories` holds it, longest first; None if none does."""
    for host_path in sorted(directories, key=len, reverse=True):
        inside = _within(path, host_path)
        if inside is not None:
            return os.path.join(directories[host_path], *inside) if inside else directories[host_path]
    return None


def _under(root, path):
    """Whether ``path`` is ``root`` or under it -- False, not an exception, for two paths on two drives."""
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def pack_directory(path):
    """A directory as a base64 gzipped tar, with nothing in it that varies between two packs.

    The same packing the client uses for `input_dirs`, so that what goes out and
    what comes back are one format. Entries sorted, owners and times zeroed, and
    the gzip header's own time pinned -- otherwise two packs of one directory
    differ in bytes 4 to 8 and nowhere else.

    No member is a link, because `unpack_directory` refuses every one (a link is
    how an archive from elsewhere writes outside the directory it lands in). A
    symbolic link resolving inside the directory is sent as what it points at; one
    resolving outside it, or nowhere, is left out with a warning -- following it
    would send a file that is not part of what was asked for.
    """
    root = os.path.realpath(path)
    skipped = []
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as compressed:
        # `dereference`: or a second name for a hard-linked file is archived as a
        # link to the first.
        with tarfile.open(fileobj=compressed, mode="w", dereference=True) as tar:

            def sanitize(info):
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                return info

            def add(full, arcname, ancestors):
                real = os.path.realpath(full)
                if os.path.islink(full):
                    inside = _under(root, real)
                    if not inside or not os.path.exists(real):
                        skipped.append(arcname)
                        return
                if os.path.isdir(real):
                    if real in ancestors:
                        # A link to a directory holding it: following it never ends.
                        skipped.append(arcname)
                        return
                    tar.addfile(sanitize(tar.gettarinfo(real, arcname=arcname)))
                    for entry in sorted(os.listdir(real)):
                        add(os.path.join(full, entry), arcname + "/" + entry, ancestors | {real})
                elif os.path.isfile(real):
                    info = sanitize(tar.gettarinfo(real, arcname=arcname))
                    with open(real, "rb") as content:
                        tar.addfile(info, content)
                else:
                    skipped.append(arcname)

            for entry in sorted(os.listdir(path)):
                if entry in (".git", "__pycache__", ".venv"):
                    continue
                add(os.path.join(path, entry), entry, frozenset({root}))
    if skipped:
        log.warning(
            "Not sent: %s -- %s to nothing inside %s.",
            ", ".join(skipped),
            "a link that points" if len(skipped) == 1 else "links, or special files, that point",
            path,
        )
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def unpack_directory(archive, target):
    """Extract a `pack_directory` archive into `target`, refusing anything that would land outside it."""
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(archive)), mode="r:gz") as tar:
        root = os.path.realpath(target)
        for member in tar.getmembers():
            # A member escaping the directory it is extracted into is how an
            # archive from elsewhere becomes a write to /usr/bin.
            resolved = os.path.realpath(os.path.join(target, member.name))
            if not _under(root, resolved):
                raise ExecuteError(-32602, "Archive member escapes its directory: %s" % member.name)
            if member.issym() or member.islnk():
                raise ExecuteError(-32602, "Archive member is a link: %s" % member.name)
            if not (member.isfile() or member.isdir()):
                raise ExecuteError(-32602, "Archive member is not a file or a directory: %s" % member.name)
        tar.extractall(target)


def _lock_path(lock):
    """Where a request's ``lock`` is kept, refused unless it is a file under the sandbox root."""
    if not isinstance(lock, dict) or not isinstance(lock.get("path"), str) or not lock["path"]:
        raise ExecuteError(-32602, "'lock' must be an object with a 'path'")
    root = os.path.normpath(SANDBOX_ROOT)
    path = os.path.normpath(lock["path"])
    # The lock file is created if it is not there, so a path anywhere would be
    # a request creating files anywhere.
    if not (os.path.isabs(path) and path != root and _under(root, path)):
        raise ExecuteError(-32602, "A lock has to be a file under %s: %s" % (SANDBOX_ROOT, lock["path"]))
    return path


@contextlib.contextmanager
def _held(lock):
    """``lock`` held for as long as the block runs: exclusive, or shared with other shared holders.

    What lets processes that never heard of each other share one environment on
    a volume: whatever installs into it holds it exclusively, and whatever runs
    out of it holds it shared, so nothing imports a package while pip is halfway
    through replacing it. Taken here, by the service, because a request in
    'upload' mode cannot run 'flock' itself -- it is not on any allowlist -- and
    because a lock must live on the same disk as what it guards.
    """
    if lock is None:
        yield
        return
    import fcntl

    path = _lock_path(lock)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if lock.get("exclusive") else fcntl.LOCK_SH)
        yield
    finally:
        os.close(descriptor)


def handle_execute_command(
    command,
    stdin=None,
    cwd=None,
    input_files=None,
    output_files=None,
    input_dirs=None,
    output_dirs=None,
    allowed=None,
    lock=None,
):
    """Run one command, with whatever files the caller sent, and answer with what it produced.

    ``lock`` is ``{"path": ..., "exclusive": bool}``: a file under the sandbox
    root held around the command (see `_held`).
    """
    if lock is not None:
        _lock_path(lock)
    with _held(lock):
        return _execute(command, stdin, cwd, input_files, output_files, input_dirs, output_dirs, allowed)


def _execute(command, stdin, cwd, input_files, output_files, input_dirs, output_dirs, allowed):
    input_files = input_files or {}
    output_files = list(output_files or [])
    input_dirs = input_dirs or {}
    output_dirs = list(output_dirs or [])

    if not command or not isinstance(command, list):
        raise ExecuteError(-32602, "Command parameter is required")
    for i, argument in enumerate(command):
        if not isinstance(argument, str):
            raise ExecuteError(-32602, "Command parameter at index %d is not a string" % i)
    command = list(command)

    # Resolved before anything is unpacked: a refusal should cost nothing.
    executable = resolve_command(command[0], allowed)
    if executable is None:
        names = sorted((ALLOWED_COMMANDS if allowed is None else allowed).keys())
        raise ExecuteError(
            -32602,
            "Command '%s' is not allowed. Allowed commands: %s, and the interpreter of an environment under %s"
            % (command[0], ", ".join(names), SANDBOX_ROOT),
        )

    # Everything this call unpacks or exchanges, removed together at the end.
    # The service is long-lived -- one container serves every command a machine
    # sends it -- so a directory per call that is never removed is a disk that
    # fills up.
    scratch = []
    try:
        directories = {}
        for host_path, archive in input_dirs.items():
            target = tempfile.mkdtemp(prefix="pc-in-")
            scratch.append(target)
            unpack_directory(archive, target)
            directories[host_path] = target
        for host_path in output_dirs:
            if host_path not in directories:
                target = tempfile.mkdtemp(prefix="pc-out-")
                scratch.append(target)
                directories[host_path] = target

        exchange = tempfile.mkdtemp(prefix="pc-x-")
        scratch.append(exchange)

        def exchanged(index, name):
            """A path in the exchange directory, keeping the extension a tool may read the type from."""
            return os.path.join(exchange, "%d%s" % (index, os.path.splitext(name)[1]))

        produced = {}
        for i in range(1, len(command)):
            original = command[i]
            # An exact file match wins over a directory prefix: a file sent on
            # its own is the file the caller meant, even inside a directory it
            # also sent.
            if original in input_files:
                path = exchanged(i, original)
                with open(path, "wb") as f:
                    f.write(base64.b64decode(input_files[original]))
                command[i] = path
                if original in output_files:
                    # Opened and saved: an in-place edit, which the caller wants back.
                    produced[original] = path
            elif original in output_files:
                path = exchanged(i, original)
                produced[original] = path
                command[i] = path
            else:
                relocated = _relocate(original, directories)
                if relocated is not None:
                    command[i] = relocated

        if cwd:
            relocated = _relocate(cwd, directories)
            if relocated is not None:
                cwd = relocated
            elif not os.path.isdir(cwd):
                # The caller's directory, on a machine this is not. Running
                # somewhere is better than refusing a command that names every
                # file it needs by path.
                log.info("cwd %s does not exist here; running in %s", cwd, exchange)
                cwd = exchange

        stdin_bytes = base64.b64decode(stdin) if stdin else None
        try:
            process = subprocess.Popen(
                [executable] + command[1:],
                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
            )
        except OSError as e:
            raise ExecuteError(-32000, "Execution error: %s" % e)
        stdout, stderr = process.communicate(input=stdin_bytes)

        files = {}
        for name, path in produced.items():
            # Only what exists: a command that failed has left nothing there,
            # and an empty file in its place would be a path to nothing rather
            # than a refusal.
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    files[name] = base64.b64encode(f.read()).decode("utf-8")
        dirs = {}
        for host_path in output_dirs:
            dirs[host_path] = pack_directory(directories[host_path])

        return {
            "exit_code": process.returncode,
            "stdout": base64.b64encode(stdout or b"").decode("utf-8"),
            "stderr": base64.b64encode(stderr or b"").decode("utf-8"),
            "output_files": files,
            "output_dirs": dirs,
        }
    finally:
        for directory in scratch:
            shutil.rmtree(directory, ignore_errors=True)


# --------------------------------------------------------------------------- #
# HTTP                                                                          #
# --------------------------------------------------------------------------- #


def _authorized(header, token):
    """Whether an `Authorization` header carries `token`; true when there is no token to carry."""
    if not token:
        return True
    expected = "Bearer %s" % token
    return hmac.compare_digest((header or "").encode("utf-8"), expected.encode("utf-8"))


def dispatch(payload):
    """One JSON-RPC request object, answered as one JSON-RPC response object."""
    request_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("method") is None:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid request"}}
    if payload["method"] != "execute":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found: %s" % payload["method"]},
        }
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Params must be an object"}}
    known = ("command", "stdin", "cwd", "input_files", "output_files", "input_dirs", "output_dirs", "lock")
    try:
        result = handle_execute_command(**{key: params[key] for key in known if key in params})
    except ExecuteError as e:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": e.code, "message": e.message}}
    except Exception as e:  # pragma: no cover - reported, not crashed on
        log.exception("execute failed")
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": "Execution error: %s" % e}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


class _Handler(BaseHTTPRequestHandler):
    token = None
    protocol_version = "HTTP/1.1"

    def _reply(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        self._reply(200, {"ok": True, "protocol": PROTOCOL})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/jsonrpc":
            self._reply(404, {"error": "not found"})
            return
        if not _authorized(self.headers.get("Authorization"), self.token):
            self._reply(401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            self._reply(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return
        self._reply(200, dispatch(payload))

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)


class Server(ThreadingMixIn, HTTPServer):
    """One thread per request: a long command must not hold up the readiness probe."""

    daemon_threads = True
    allow_reuse_address = True


def serve(host="0.0.0.0", port=DEFAULT_PORT, token=None):
    """A server bound and ready to `serve_forever()`, for this process or a test."""
    handler = type("Handler", (_Handler,), {"token": token})
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_class = type("BoundServer", (Server,), {"address_family": family})
    return server_class((host, port), handler)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    port = int(os.environ.get("PC_CONTAINER_PORT") or DEFAULT_PORT)
    token = os.environ.get("PC_CONTAINER_TOKEN") or None
    server = serve("0.0.0.0", port, token)
    log.info(
        "PartCAD container service (protocol %d) on port %d; allowed: %s",
        PROTOCOL,
        port,
        ", ".join(sorted(ALLOWED_COMMANDS)),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
