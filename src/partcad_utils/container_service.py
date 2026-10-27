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

The protocol is JSON-RPC 2.0 over HTTP, in two dialects that say the same
things. The JSON one is what anybody can type, and carries every payload as
base64 -- which is how it began, and what an older client of
`partcad-service-remote-docker` still speaks, so it stays. One method,
`execute`, does the work::

    POST /jsonrpc
    Content-Type: application/json

    {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {
        "command": ["kicad-cli", "pcb", "export", "step", "/w/board.kicad_pcb", "-o", "/w/board.step"],
        "stdin": "<base64>" | null,
        "cwd": "/w" | null,
        "input_files": {"/w/board.kicad_pcb": "<base64>"},
        "output_files": ["/w/board.step"],
        "input_dirs": {"/w/pkg": "<base64 tar.gz>"},
        "output_dirs": ["/w/pkg"]
    }}

The **frame** dialect (`FRAME_TYPE`) is what PartCAD itself speaks. A body is a
JSON header followed by raw blobs, each one length-prefixed (see
`encode_frame`), and every bytes value of the message -- standard input, a
file, what a command printed -- is a blob rather than a string, so nothing is
base64 in either direction. A wrapper's request is already base64 inside, and
carried as base64 again it was 1.78 times the geometry it described, encoded
and decoded once per hop. Directories travel by **content**, not as archives::

    "input_trees": {"/w/pkg": {"files": [["solve.py", "<sha256>", 420], ...], "dirs": ["sub"]}},
    "blobs": {"<sha256>": <blob> | {"zlib": <blob>}, ...}

A tree names each file by the digest of what is in it, and the service keeps
what it has been sent in a store of its own (`Store`), so a directory that has
not changed costs its manifest and nothing else: the wrappers every sandbox
command imports are sent once per container, not once per command. A caller
asks `missing` (``{"digests": [...]}``, answered with the ones the store
lacks) and sends those as ``blobs``; a request naming content the store no
longer has -- it is bounded, and evicts what was used least recently -- is
refused with `MISSING`, naming it, and the caller sends it and asks again.

Every path in a request is the *caller's*. When the caller and the container
share a filesystem -- the `mount` transfer mode -- none of the payloads are sent
and the paths simply exist in here. When they do not -- `upload` -- the payloads
carry the files, and every argument naming one is rewritten to where this
service put it before the command runs:

* ``input_files`` are written into a directory of this call's own, and an
  argument equal to one of the names is rewritten to it.
* ``input_dirs`` (JSON) are extracted and ``input_trees`` (frames) built from
  the store, and an argument *below* one of them -- matched by prefix, longest
  first, separator-agnostic -- is rewritten into it. So is ``cwd``. A script
  imports its siblings, which is why a directory travels whole rather than as
  the one file a command names.
* ``output_files`` are names the command is expected to write. An argument equal
  to one is pointed into this call's directory, and whatever is there after the
  command ends is sent back under the caller's name. A name that is also an
  input is an *in-place edit* -- an application opening a file and saving it --
  and it comes back too.
* ``output_dirs`` are directories to send back whole after the command: packed
  the way ``input_dirs`` are in JSON, and in frames as a tree whose files are
  blobs -- leaving out every file that is exactly what the caller sent, since
  the caller has it. One that was also sent comes back with whatever the
  command changed in it; one that was not is created empty first, for a
  command that writes a directory of results.
* ``env`` sets variables for this one command, over the container's own. Only
  the names in `ENV_ALLOWED` -- the display an application opens a window on,
  and the like; anything else is refused.

The other, `which`, runs nothing: ``{"names": ["freecad", "FreeCAD"]}`` answers
with where each allowed name resolves in this container, or null -- so a caller
looking for an application under one of several names can find out which this
image has, on a daemon it cannot ``docker exec`` into.

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

A request is answered in the dialect it was asked in, and over a connection
that stays open for the next one (HTTP/1.1 keep-alive), which is what a caller
sending a command per part reuses.
"""

import base64
import contextlib
import errno
import gzip
import hashlib
import hmac
import io
import json
import logging
import os
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# What `GET /` reports, and what a client may ask of a server before relying on
# one of the additions below. 1 is the service as it was before them; 2 sends
# in-place edits back, sends `output_dirs`, resolves a null allowlist entry on
# PATH and rewrites `cwd`; 3 holds a `lock` around a command; 4 takes `env` and
# answers `which`; 5 speaks frames, keeps a store, and answers `missing`.
#
# A container always runs the release of the PartCAD that started it, so
# nothing PartCAD starts needs to ask. `partcad-service-remote-docker` reports
# the same number on its own `GET /`, and it is a service on another machine,
# installed on its own -- so that is where a client does ask.
PROTOCOL = 5

# The protocol frames arrived in: what a client asks a service for before it
# sends one, whatever the protocol has grown to since.
FRAME_PROTOCOL = 5

# The body of a request or an answer in the frame dialect: `encode_frame`.
FRAME_TYPE = "application/x-partcad-frame"
FRAME_MAGIC = b"PCF1"

# The JSON-RPC error a request naming content the store does not have is
# answered with. Its `data` is ``{"missing": [digests]}``; nothing has run.
MISSING = -32010

# The variables a request may set for its command, and no others. An application
# opened for editing needs the display the user is sitting at *now* -- which is
# not something fixed when the container was created, weeks ago, on another
# display -- and that is what this is for. Not a free-for-all: the allowlist is
# the whole of what a caller may run, and LD_PRELOAD or PYTHONPATH in a request
# would be a way round it.
ENV_ALLOWED = frozenset(
    {
        "DISPLAY",
        "XAUTHORITY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "QT_X11_NO_MITSHM",
        "LIBGL_ALWAYS_SOFTWARE",
        "HOME",
        "LANG",
        "LC_ALL",
        "TZ",
    }
)

# Where the service listens unless told otherwise. Not a request parameter: what
# answers inside a container is part of the container's identity, and a request
# naming a port would be a request choosing what to talk to.
DEFAULT_PORT = 5000

# How long a command that has exited may go on holding its output open, in
# seconds, before the wait for it ends anyway (see `communicate`). What it wrote
# before it exited is in the pipe already and reads in milliseconds; anything
# that keeps the pipe open past this is something the command started and left
# behind, not the command.
EXIT_GRACE = 2.0

# How often a command that is still being waited for is looked at, in seconds.
# Only how late a death is noticed, not how long anything waits.
WATCH_INTERVAL = 0.25

log = logging.getLogger("partcad.container_service")


class ExecuteError(Exception):
    """A request this service refuses, as the JSON-RPC error it becomes."""

    def __init__(self, code, message, data=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.data = data

    def error(self):
        """The JSON-RPC error object."""
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


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


# Never sent, at the top of a directory: what a package carries that no command
# run on it reads, and that can be most of what it weighs.
SKIPPED_NAMES = (".git", "__pycache__", ".venv")


def walk(path, skipped):
    """Everything under ``path`` that is sent, as ``(kind, name, real path)``, in a fixed order.

    ``kind`` is "dir" or "file", and ``name`` the path below ``path`` with "/"
    between its parts, whichever platform this is: it is read on the other
    side. Sorted, each directory before what is in it.

    Nothing is a link, because neither end writes one (a link is how content
    from elsewhere writes outside the directory it lands in). A symbolic link
    resolving inside the directory is sent as what it points at; one resolving
    outside it, or nowhere, is left out and its name appended to ``skipped`` --
    following it would send a file that is not part of what was asked for. So
    is a special file, and a link to a directory holding it, which never ends.

    One walk for both ends and both dialects: what `pack_directory` archives,
    what a caller sends as a tree and what this service sends back are the same
    set of files, decided once.
    """
    root = os.path.realpath(path)

    def visit(full, name, ancestors):
        real = os.path.realpath(full)
        if os.path.islink(full):
            if not _under(root, real) or not os.path.exists(real):
                skipped.append(name)
                return
        if os.path.isdir(real):
            if real in ancestors:
                skipped.append(name)
                return
            yield "dir", name, real
            for entry in sorted(os.listdir(real)):
                for item in visit(os.path.join(full, entry), name + "/" + entry, ancestors | {real}):
                    yield item
        elif os.path.isfile(real):
            yield "file", name, real
        else:
            skipped.append(name)

    for entry in sorted(os.listdir(path)):
        if entry in SKIPPED_NAMES:
            continue
        for item in visit(os.path.join(path, entry), entry, frozenset({root})):
            yield item


def warn_skipped(skipped, path):
    """Say what `walk` left out of ``path``, if anything."""
    if skipped:
        log.warning(
            "Not sent: %s -- %s to nothing inside %s.",
            ", ".join(skipped),
            "a link that points" if len(skipped) == 1 else "links, or special files, that point",
            path,
        )


def pack_directory(path):
    """A directory as a base64 gzipped tar, with nothing in it that varies between two packs.

    The JSON dialect's way of sending a directory (the frame dialect sends a
    tree, by content). The same packing the client uses for `input_dirs`, so
    that what goes out and what comes back are one format. Entries sorted,
    owners and times zeroed, and the gzip header's own time pinned -- otherwise
    two packs of one directory differ in bytes 4 to 8 and nowhere else. What is
    in it is what `walk` says, so `unpack_directory`, which refuses every link,
    never meets one.
    """
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

            for kind, name, real in walk(path, skipped):
                info = sanitize(tar.gettarinfo(real, arcname=name))
                if kind == "dir":
                    tar.addfile(info)
                else:
                    with open(real, "rb") as content:
                        tar.addfile(info, content)
    warn_skipped(skipped, path)
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


# --------------------------------------------------------------------------- #
# Frames                                                                       #
# --------------------------------------------------------------------------- #
#
# A body in the frame dialect:
#
#     b"PCF1"          4 bytes
#     header length    4 bytes, big-endian
#     header           that many bytes of UTF-8 JSON: the JSON-RPC message
#     then, once per blob:
#       blob length    8 bytes, big-endian
#       blob           that many bytes, as they are
#
# Every bytes value of the message is a blob, and stands in the header as
# {"$blob": <its index>}. A message has no other object of that one key.

_BLOB = "$blob"


def _nbytes(value):
    return memoryview(value).nbytes


def encode_frame(message):
    """``message`` as the buffers that make up its body, in order.

    Not joined: a payload of fifty megabytes goes onto the socket as the
    buffer it already is, and nothing here copies it.
    """
    blobs = []

    def strip(value):
        if isinstance(value, (bytes, bytearray, memoryview)):
            blobs.append(value)
            return {_BLOB: len(blobs) - 1}
        if isinstance(value, dict):
            return dict((key, strip(item)) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return [strip(item) for item in value]
        return value

    header = json.dumps(strip(message), separators=(",", ":")).encode("utf-8")
    parts = [FRAME_MAGIC, struct.pack(">I", len(header)), header]
    for blob in blobs:
        parts.append(struct.pack(">Q", _nbytes(blob)))
        parts.append(blob)
    return parts


def frame_length(parts):
    """How many bytes `encode_frame`'s buffers come to."""
    return sum(_nbytes(part) for part in parts)


def decode_frame(body):
    """The message an `encode_frame` body carries, each blob a `memoryview` of ``body``.

    Views rather than copies: what a request carries is written to a file or
    handed to a command, and either takes a view as it takes bytes. Raises
    ValueError for anything that is not a whole frame.
    """
    view = memoryview(body)
    if len(view) < 8 or view[:4].tobytes() != FRAME_MAGIC:
        raise ValueError("not a PartCAD frame")
    (length,) = struct.unpack_from(">I", view, 4)
    offset = 8 + length
    if offset > len(view):
        raise ValueError("the frame's header is cut short")
    header = json.loads(view[8:offset].tobytes().decode("utf-8"))
    blobs = []
    while offset < len(view):
        if offset + 8 > len(view):
            raise ValueError("the frame is cut short in a blob's length")
        (size,) = struct.unpack_from(">Q", view, offset)
        offset += 8
        if offset + size > len(view):
            raise ValueError("the frame is cut short in a blob")
        blobs.append(view[offset : offset + size])
        offset += size

    def fill(value):
        if isinstance(value, dict):
            if len(value) == 1 and _BLOB in value:
                index = value[_BLOB]
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(blobs):
                    raise ValueError("the frame names a blob it does not carry: %r" % (index,))
                return blobs[index]
            return dict((key, fill(item)) for key, item in value.items())
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value

    return fill(header)


# --------------------------------------------------------------------------- #
# The store                                                                    #
# --------------------------------------------------------------------------- #

# Where it is kept, and how big it may get. In the container's own filesystem by
# default, so that it goes when the container does: a container is replaced
# whenever anything that makes it what it is changes, this file included, and
# a store outliving it would be a store nothing bounds. The limit is for a
# container that is not replaced for a long time while the packages sent to it
# change; what it holds in the meantime is overwhelmingly the same few
# directories.
STORE_ROOT = os.environ.get("PC_CONTAINER_STORE") or os.path.join(tempfile.gettempdir(), "pc-store")
STORE_LIMIT = int(os.environ.get("PC_CONTAINER_STORE_LIMIT") or 256 * 1024 * 1024)

_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def content_digest(data):
    """What a file is called in the store: the SHA-256 of what is in it, in hex."""
    return hashlib.sha256(data).hexdigest()


def pack_blob(data):
    """A file's content as it travels in a tree: compressed when that saves a tenth of it, else as it is.

    A directory used to travel as a gzipped tar, and on the way to a container
    on another machine -- which is what `upload` mode and the `remote` sandbox
    are for -- a package's sources and STEP files are a third of their size
    compressed. What travels in a tree travels once per container now, so the
    compression is at the fastest level; a payload sent with every command
    (standard input, a file on its own) is not compressed at all, and a file
    that is compressed already comes out no smaller and is sent as it is.
    """
    size = _nbytes(data)
    if size < 512:
        return data
    packed = zlib.compress(data, 1)
    return {"zlib": packed} if len(packed) <= size * 9 // 10 else data


def unpack_blob(value):
    """What `pack_blob` made, as the bytes it was made from."""
    if isinstance(value, dict) and list(value) == ["zlib"]:
        if not isinstance(value["zlib"], (bytes, bytearray, memoryview)):
            raise ExecuteError(-32602, "Compressed content must be carried as a blob")
        try:
            return zlib.decompress(value["zlib"])
        except zlib.error as e:
            raise ExecuteError(-32602, "Compressed content that does not decompress: %s" % e)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return value
    raise ExecuteError(-32602, "Content must be carried as a blob")


class Store(object):
    """What this service has been sent, by content, bounded in size.

    Read by digest and written by digest, and a digest is checked against what
    it names before anything is kept: a store a caller could write under a
    wrong name is a store that hands the next caller somebody else's file --
    and through `partcad-service-remote-docker`, the next caller is somebody
    else.

    A tree is built by *copying* out of the store, not by linking: a hard link
    is the store's own file, and a command that saves over an input -- KiCad
    saving a board beside the project it opened, a script rewriting a file next
    to it -- would change what every later command is handed under that name,
    with nothing to say so. A copy costs tens of microseconds a file.
    """

    def __init__(self, root, limit=None):
        self.root = root
        self.limit = STORE_LIMIT if limit is None else limit
        self._lock = threading.Lock()
        # digest -> size, for everything on disk; read from the disk once.
        self._sizes = None
        # digest -> when a command last used it, which is what goes first.
        self._used = {}
        self._total = 0

    def path(self, digest):
        """Where the content under ``digest`` is kept; refused for anything that is not a digest."""
        # Checked before it is a path: a digest comes from the caller, and
        # "../../bin/sh" is not one.
        if not isinstance(digest, str) or not _DIGEST.match(digest):
            raise ExecuteError(-32602, "Not a content digest: %r" % (digest,))
        return os.path.join(self.root, digest[:2], digest)

    def _loaded(self):
        """The index, read off the disk the first time it is needed. Called under the lock."""
        if self._sizes is None:
            self._sizes = {}
            self._total = 0
            try:
                shards = os.listdir(self.root)
            except OSError:
                shards = []
            for shard in shards:
                directory = os.path.join(self.root, shard)
                try:
                    entries = os.listdir(directory)
                except OSError:
                    continue
                for entry in entries:
                    full = os.path.join(directory, entry)
                    try:
                        status = os.stat(full)
                    except OSError:
                        continue
                    if _DIGEST.match(entry):
                        self._sizes[entry] = status.st_size
                        self._used[entry] = status.st_mtime
                        self._total += status.st_size
                    elif entry.startswith(".in-") and time.time() - status.st_mtime > 3600:
                        # Half-written by a service that died writing it.
                        with contextlib.suppress(OSError):
                            os.remove(full)
        return self._sizes

    def missing(self, digests):
        """Those of ``digests`` the store does not have, each once, in the order asked."""
        found, seen = [], set()
        for digest in digests or ():
            if digest in seen:
                continue
            seen.add(digest)
            if not os.path.isfile(self.path(digest)):
                found.append(digest)
        return found

    def add(self, digest, data):
        """Keep ``data`` under ``digest``, having checked that it is what ``digest`` names.

        A failure to write is not the request's failure -- the content is in
        the request, and the command can be given it from there; the store
        simply does not have it next time.
        """
        path = self.path(digest)
        if content_digest(data) != digest:
            raise ExecuteError(-32602, "Content sent as %s is not what that digest names" % digest)
        size = _nbytes(data)
        if os.path.isfile(path) or size > self.limit:
            return
        directory = os.path.dirname(path)
        temporary = None
        try:
            os.makedirs(directory, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".in-")
            with os.fdopen(descriptor, "wb") as f:
                f.write(data)
            # Whole or not at all: another request may be reading it already.
            os.replace(temporary, path)
            temporary = None
        except OSError as e:
            log.warning("Could not keep %s in %s: %s", digest, self.root, e)
            return
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    os.remove(temporary)
        with self._lock:
            sizes = self._loaded()
            if digest not in sizes:
                sizes[digest] = size
                self._total += size
            self._used[digest] = time.time()
        self._trim()

    def copy(self, digest, target):
        """Write what is under ``digest`` to ``target``; False when the store does not have it."""
        try:
            shutil.copyfile(self.path(digest), target)
        except (IOError, OSError) as e:
            if e.errno == errno.ENOENT and not os.path.exists(self.path(digest)):
                return False
            raise
        with self._lock:
            self._used[digest] = time.time()
        return True

    def _trim(self):
        """Remove what was used least recently until the store is well inside its limit.

        To three quarters of it, so that a store at its limit is not trimmed
        again by every file it is sent. A file a command is being built from
        right now may go too: what was copied out of it stays where it was
        copied, and a request that finds it gone is answered `MISSING` and
        sends it again.
        """
        with self._lock:
            sizes = self._loaded()
            if self._total <= self.limit:
                return
            for digest in sorted(sizes, key=lambda d: self._used.get(d, 0)):
                if self._total <= self.limit * 3 // 4:
                    break
                with contextlib.suppress(OSError):
                    os.remove(self.path(digest))
                self._total -= sizes.pop(digest)
                self._used.pop(digest, None)


_STORE = None
_STORE_GUARD = threading.Lock()


def default_store():
    """The store a request is served from unless the server was given another."""
    global _STORE
    with _STORE_GUARD:
        if _STORE is None or _STORE.root != STORE_ROOT:
            _STORE = Store(STORE_ROOT)
        return _STORE


def _tree_files(tree):
    """A tree's files as ``(name, digest, mode)``, each checked; refused when it is not a tree."""
    if not isinstance(tree, dict):
        raise ExecuteError(-32602, "A tree must be an object with 'files' and 'dirs'")
    files = []
    for entry in tree.get("files") or ():
        if not (isinstance(entry, list) and len(entry) == 3 and isinstance(entry[0], str)):
            raise ExecuteError(-32602, "A tree's file must be [name, digest, mode]: %r" % (entry,))
        name, digest, mode = entry
        if not isinstance(mode, int) or isinstance(mode, bool):
            raise ExecuteError(-32602, "A tree's file mode must be a number: %r" % (entry,))
        files.append((name, digest, mode))
    dirs = tree.get("dirs") or []
    if not isinstance(dirs, list) or not all(isinstance(name, str) for name in dirs):
        raise ExecuteError(-32602, "A tree's 'dirs' must be a list of names")
    return files, dirs


def below(root, name):
    """Where ``name`` -- "/"-separated, as `walk` writes it -- is under ``root``; refused if anywhere else.

    Resolved through whatever links are already there, the way
    `unpack_directory` checks an archive's members: a name that would land
    outside ``root`` is how content from elsewhere becomes a write to /usr/bin.
    """
    parts = name.split("/") if isinstance(name, str) else [""]
    if any(part in ("", ".", "..") or "\0" in part for part in parts):
        raise ExecuteError(-32602, "Not a name inside a directory: %r" % (name,))
    target = os.path.join(root, *parts)
    if not _under(os.path.realpath(root), os.path.realpath(target)):
        raise ExecuteError(-32602, "Escapes its directory: %s" % name)
    return target


def build_tree(tree, target, store, carried=None):
    """Make ``target`` hold what ``tree`` names: content from ``carried`` (digest -> bytes) or ``store``.

    Raises `MISSING` naming whatever neither has -- found by looking at each
    first, so that no file is written for a request that is refused.
    """
    carried = carried or {}
    files, dirs = _tree_files(tree)
    lacking = store.missing([digest for _, digest, _ in files if digest not in carried])
    if lacking:
        raise ExecuteError(MISSING, "Content this service does not have", {"missing": lacking})
    for name in dirs:
        os.makedirs(below(target, name), exist_ok=True)
    gone = []
    for name, digest, mode in files:
        path = below(target, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if digest in carried:
            with open(path, "wb") as f:
                f.write(carried[digest])
        elif not store.copy(digest, path):
            # Trimmed away since it was looked for (see `Store._trim`).
            gone.append(digest)
            continue
        # What matters of a mode on the far side is whether it runs.
        os.chmod(path, 0o755 if mode & 0o111 else 0o644)
    if gone:
        raise ExecuteError(MISSING, "Content this service no longer has", {"missing": sorted(set(gone))})


def tree_back(directory, sent=None):
    """``directory`` as a tree to send back: ``{"files": [[name, mode, content]], "dirs": [...]}``.

    Each file's content is a blob, or a compressed one (see `pack_blob`).

    Leaving out every file that is what the caller sent under that name
    (``sent``: name -> digest), which the caller has: a project directory KiCad
    saved one board in comes back as that board.
    """
    sent = sent or {}
    skipped, files, dirs = [], [], []
    for kind, name, real in walk(directory, skipped):
        if kind == "dir":
            dirs.append(name)
            continue
        with open(real, "rb") as f:
            data = f.read()
        if name in sent and sent[name] == content_digest(data):
            continue
        files.append([name, os.stat(real).st_mode & 0o777, pack_blob(data)])
    warn_skipped(skipped, directory)
    return {"files": files, "dirs": dirs}


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


# --------------------------------------------------------------------------- #
# Waiting for a command                                                        #
# --------------------------------------------------------------------------- #
#
# Here because this file has to stand alone -- it is copied into containers on
# its own -- and PartCAD's own sandboxes wait for their interpreters the same
# way, so `partcad.runtime` takes these from here rather than keeping a copy
# that could come to disagree.


def pipe_holders(files):
    """The processes that can still write into these pipes, by pid: never this one.

    What a process that has died leaves holding its output open. A child
    inherits its parent's standard output and standard error, so anything a
    sandbox interpreter started -- a helper of a user's script, a pool of
    workers, a simulator's server -- holds the very pipes PartCAD reads the
    interpreter's answer from, and the pipe does not reach its end until the
    last of them has gone.

    Found by the pipe itself rather than by ancestry: by the time anybody asks,
    the parent is dead and its children belong to whatever adopts orphans, so
    nothing leads back to it. Read off ``/proc`` on Linux and asked of ``lsof``
    on macOS (`_lsof_pipe_holders`); an empty list elsewhere, which leaves the
    caller closing its own end instead.
    """
    pipes = {}
    for f in files:
        if f is None:
            continue
        try:
            descriptor = f if isinstance(f, int) else f.fileno()
            status = os.fstat(descriptor)
        except (OSError, ValueError):
            continue
        if stat.S_ISFIFO(status.st_mode):
            pipes[descriptor] = "pipe:[%d]" % status.st_ino
    if not pipes:
        return []
    if not os.path.isdir("/proc/self/fd"):
        return _lsof_pipe_holders(pipes) if sys.platform == "darwin" else []
    wanted = set(pipes.values())
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        directory = "/proc/%s/fd" % entry
        try:
            descriptors = os.listdir(directory)
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                if os.readlink(os.path.join(directory, descriptor)) not in wanted:
                    continue
                # The writing end only. Something holding the reading end of
                # these is a copy of the reader, not a reason it waits.
                with open("/proc/%s/fdinfo/%s" % (entry, descriptor)) as info:
                    flags = next((line.split()[1] for line in info if line.startswith("flags:")), "0")
                if int(flags, 8) & os.O_ACCMODE == os.O_RDONLY:
                    continue
            except (OSError, ValueError, IndexError):
                continue
            found.append(int(entry))
            break
    return sorted(found)


def _lsof_pipe_holders(descriptors, run=subprocess.run):
    """`pipe_holders` where there is no ``/proc``: macOS, asked of ``lsof``.

    A pipe on macOS has no inode another process can be matched by, but each of
    its two ends has a kernel handle, and ``lsof`` names both: an end's own as
    its device, and the end it is joined to as its name (``->0x...``). So the
    handles of the ends these descriptors are joined to -- the writing ends,
    these being the reading ones -- are read off this process, and whatever else
    has a descriptor with one of them as its device holds a writing end. Only
    this user's processes are listed, which is all that can have inherited a
    pipe from this one, and which keeps the second call short.

    ``lsof`` exits non-zero when anything asked for is missing, so its output is
    read whatever its status; a machine without one, or one that does not
    answer in time, has no holders found -- the caller closes its own end then,
    as everywhere else.
    """

    def listed(*args):
        try:
            answer = run(["lsof", "-n", "-P", "-w", *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return []
        # One field a line, its kind first: 'p' starts a process and 'f' a
        # descriptor of it, and what follows belongs to that descriptor.
        records, pid = [], None
        for line in (answer.stdout or "").splitlines():
            kind, value = line[:1], line[1:]
            if kind == "p":
                pid = value
            elif kind == "f":
                records.append({"p": pid, "f": value})
            elif records and kind:
                records[-1][kind] = value
        return records

    me = str(os.getpid())
    ours = listed("-a", "-p", me, "-d", ",".join(str(d) for d in sorted(descriptors)), "-F", "fdn")
    joined = set()
    for record in ours:
        name = record.get("n", "")
        if record.get("p") == me and name.startswith("->"):
            joined.update(name[2:].split()[:1])
    joined.discard("0x0")
    if not joined:
        return []
    found = set()
    for record in listed("-u", str(os.getuid()), "-F", "pfad"):
        if record.get("p") in (None, me) or record.get("d") not in joined:
            continue
        # The writing end, as on Linux; this end is its own, so a reader is not
        # expected here at all, and is not a reason to wait if one is.
        if record.get("a") == "r":
            continue
        if record["p"].isdigit():
            found.add(int(record["p"]))
    return sorted(found)


def stop_holders(files):
    """Kill what can still write into these pipes, and return the pids it was.

    Killed without being asked first, like the interpreter that started them:
    their parent is dead, so there is nobody left to want what they are doing,
    and an orphan that never writes again would otherwise never notice that
    nobody is reading.
    """
    holders = pipe_holders(files)
    for pid in holders:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return holders


def communicate(process, input=None, grace=EXIT_GRACE, interval=WATCH_INTERVAL, wait_after_success=False):
    """``process.communicate(input)``, over when the process is over.

    Returns ``(stdout, stderr, left)``: what the process wrote, and -- when its
    output did not end by itself -- the pids of whatever it had started that
    was still holding that output open after it exited, which are killed.
    ``left`` is None when the output ended by itself, which is nearly always;
    an empty list means the output was cut off with nothing found to stop.

    ``communicate`` on its own waits for the end of both output pipes as well as
    for the process, and a pipe ends only when every process holding it has let
    go -- so once a command has started something that inherits its output, the
    wait is as long as that something lives, whatever became of the command. A
    sandbox interpreter killed by the out-of-memory killer while its helper
    slept on was a wait with no end, holding everything taken for it.

    So the process is watched as well as its pipes: once it has exited, its
    output is given `EXIT_GRACE` to drain, then what still holds it is stopped
    (`stop_holders`) and given as long again, and then the pipes are closed from
    this end whatever is left. What was read by then is what is returned.

    ``wait_after_success`` keeps the old wait for a command that exited 0: its
    output is read to the end however long that takes, and only a command that
    failed or was killed is cut off. That is for this service's own requests,
    which include an application opened for editing -- and an application's
    launcher may hand the window to a child and exit, leaving the child holding
    the output for as long as somebody is editing, which is the wait `pc ide
    open` is there to make. A sandbox interpreter has no such child: once it has
    exited it has answered, or never will.
    """
    exited = None
    pending = input
    stdout = stderr = None
    while True:
        try:
            out, err = process.communicate(input=pending, timeout=interval)
            return out, err, None
        except subprocess.TimeoutExpired as e:
            # Passed once: 'communicate' remembers it, and refuses to be handed
            # it again once it has started writing it.
            pending = None
            # What has been read so far, which a timeout carries on POSIX and a
            # retry does not lose. Windows reads on threads of its own and
            # reports nothing until they finish.
            stdout, stderr = e.output, e.stderr
        returncode = process.poll()
        if returncode is None:
            continue
        if returncode == 0 and wait_after_success:
            out, err = process.communicate()
            return out, err, None
        now = time.monotonic()
        if exited is None:
            exited = now
        elif now - exited >= grace:
            break
    left = stop_holders([process.stdout, process.stderr])
    try:
        out, err = process.communicate(timeout=grace)
        return out, err, left
    except subprocess.TimeoutExpired as e:
        # Still held -- by something this could not find or could not kill.
        # What has been read is all there is going to be.
        if e.output is not None:
            stdout = e.output
        if e.stderr is not None:
            stderr = e.stderr
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    return stdout, stderr, left


def _check_request(env, lock):
    """``env`` and ``lock`` refused before anything is done, if either is not one a request may send."""
    env = env or {}
    if not isinstance(env, dict):
        raise ExecuteError(-32602, "env must be an object")
    refused = sorted(key for key in env if key not in ENV_ALLOWED)
    if refused:
        raise ExecuteError(
            -32602, "env may not set %s; it may set: %s" % (", ".join(refused), ", ".join(sorted(ENV_ALLOWED)))
        )
    if lock is not None:
        _lock_path(lock)
    return env


class _Json(object):
    """What a request in the JSON dialect carries: base64 payloads, directories as gzipped tars."""

    def __init__(self, stdin, input_files, input_dirs):
        self._stdin = stdin
        self._files = input_files or {}
        self._dirs = input_dirs or {}

    def prepare(self):
        pass

    def stdin(self):
        return base64.b64decode(self._stdin) if self._stdin else None

    def file_names(self):
        return self._files

    def file(self, name):
        return base64.b64decode(self._files[name])

    def directories(self, scratch):
        directories = {}
        for host_path, archive in self._dirs.items():
            target = tempfile.mkdtemp(prefix="pc-in-")
            scratch.append(target)
            unpack_directory(archive, target)
            directories[host_path] = target
        return directories

    def back(self, host_path, directory):
        return pack_directory(directory)

    @staticmethod
    def answer(result):
        """The result in this dialect's encoding."""
        result["stdout"] = base64.b64encode(result["stdout"] or b"").decode("utf-8")
        result["stderr"] = base64.b64encode(result["stderr"] or b"").decode("utf-8")
        result["output_files"] = dict(
            (name, base64.b64encode(data).decode("utf-8")) for name, data in result["output_files"].items()
        )
        return result


class _Frames(object):
    """What a request in the frame dialect carries: bytes, and directories as trees of the store's content."""

    def __init__(self, stdin, input_files, input_trees, blobs, store):
        self._stdin = stdin
        self._files = input_files or {}
        self._trees = input_trees or {}
        self._store = store
        for name, value in self._files.items():
            if not isinstance(value, (bytes, bytearray, memoryview)):
                raise ExecuteError(-32602, "%s must be carried as a blob" % name)
        if not isinstance(self._trees, dict) or not isinstance(blobs or {}, dict):
            raise ExecuteError(-32602, "input_trees and blobs must be objects")
        # Each one as the bytes it names, whether it came compressed or not.
        self._blobs = dict((digest, unpack_blob(value)) for digest, value in (blobs or {}).items())

    def prepare(self):
        """Keep what came with the request, and refuse it -- running nothing -- if it names what did not."""
        for digest, data in self._blobs.items():
            self._store.add(digest, data)
        wanted = []
        for tree in self._trees.values():
            files, _ = _tree_files(tree)
            wanted.extend(digest for _, digest, _ in files if digest not in self._blobs)
        lacking = self._store.missing(wanted)
        if lacking:
            raise ExecuteError(MISSING, "Content this service does not have", {"missing": lacking})

    def stdin(self):
        if self._stdin is not None and not isinstance(self._stdin, (bytes, bytearray, memoryview)):
            raise ExecuteError(-32602, "stdin must be carried as a blob")
        return self._stdin if self._stdin is not None and _nbytes(self._stdin) else None

    def file_names(self):
        return self._files

    def file(self, name):
        return self._files[name]

    def directories(self, scratch):
        directories = {}
        for host_path, tree in self._trees.items():
            target = tempfile.mkdtemp(prefix="pc-in-")
            scratch.append(target)
            build_tree(tree, target, self._store, self._blobs)
            directories[host_path] = target
        return directories

    def back(self, host_path, directory):
        sent = {}
        if host_path in self._trees:
            sent = dict((name, digest) for name, digest, _ in _tree_files(self._trees[host_path])[0])
        return tree_back(directory, sent)

    @staticmethod
    def answer(result):
        return result


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
    env=None,
):
    """Run one command in the JSON dialect, and answer with what it produced: payloads base64.

    ``lock`` is ``{"path": ..., "exclusive": bool}``: a file under the sandbox
    root held around the command (see `_held`). ``env`` sets variables for this
    one command, from `ENV_ALLOWED` only.
    """
    env = _check_request(env, lock)
    with _held(lock):
        result = _execute(command, cwd, output_files, output_dirs, allowed, env, _Json(stdin, input_files, input_dirs))
    return _Json.answer(result)


def handle_execute_frames(
    command,
    stdin=None,
    cwd=None,
    input_files=None,
    output_files=None,
    input_trees=None,
    blobs=None,
    output_dirs=None,
    allowed=None,
    lock=None,
    env=None,
    store=None,
):
    """Run one command in the frame dialect: every payload bytes, directories as trees.

    ``blobs`` is what the caller sent of the content its trees name, kept in
    ``store`` (the default one unless told) for the next request; a tree
    naming content neither has is refused with `MISSING` before anything runs.
    The answer's ``stdout``, ``stderr`` and ``output_files`` are bytes, and its
    ``output_dirs`` trees (see `tree_back`).
    """
    env = _check_request(env, lock)
    carried = _Frames(stdin, input_files, input_trees, blobs, store or default_store())
    with _held(lock):
        return _execute(command, cwd, output_files, output_dirs, allowed, env, carried)


def handle_missing(digests, store=None):
    """Which of ``digests`` the store does not have, for a caller deciding what to send."""
    if not isinstance(digests, list):
        raise ExecuteError(-32602, "digests must be a list")
    return {"missing": (store or default_store()).missing(digests)}


def _execute(command, cwd, output_files, output_dirs, allowed, env, carried):
    output_files = list(output_files or [])
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
        table = ALLOWED_COMMANDS if allowed is None else allowed
        if command[0] in table:
            # Allowed, and left to PATH, and PATH has nothing by that name. Said
            # as such: "not allowed", followed by a list of the allowed that
            # holds it, sends whoever reads it after the wrong thing.
            raise ExecuteError(
                -32602,
                "Command '%s' is allowed, but this container has no '%s' on its PATH" % (command[0], command[0]),
            )
        raise ExecuteError(
            -32602,
            "Command '%s' is not allowed. Allowed commands: %s, and the interpreter of an environment under %s"
            % (command[0], ", ".join(sorted(table.keys())), SANDBOX_ROOT),
        )
    carried.prepare()
    input_files = carried.file_names()

    # Everything this call unpacks or exchanges, removed together at the end.
    # The service is long-lived -- one container serves every command a machine
    # sends it -- so a directory per call that is never removed is a disk that
    # fills up.
    scratch = []
    try:
        directories = carried.directories(scratch)
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
                    f.write(carried.file(original))
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

        stdin_bytes = carried.stdin()
        environment = None
        if env:
            environment = dict(os.environ)
            environment.update({str(key): str(value) for key, value in env.items()})
        try:
            process = subprocess.Popen(
                [executable] + command[1:],
                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=environment,
            )
        except OSError as e:
            raise ExecuteError(-32000, "Execution error: %s" % e)
        # Over when the command is, rather than when the last process holding
        # its output lets go: a command that died here left the request open
        # for good, and the lock on the environment with it (see `communicate`).
        # One that exited 0 is still read to the end, for an application whose
        # launcher handed the window on and left (see `wait_after_success`).
        stdout, stderr, left = communicate(process, stdin_bytes, wait_after_success=True)
        if left is not None:
            log.warning(
                "%s ended (exit code %s) with its output still held open; stopped %s",
                command[0],
                process.returncode,
                ", ".join(str(pid) for pid in left) or "nothing that could be found",
            )

        files = {}
        for name, path in produced.items():
            # Only what exists: a command that failed has left nothing there,
            # and an empty file in its place would be a path to nothing rather
            # than a refusal.
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    files[name] = f.read()
        dirs = {}
        for host_path in output_dirs:
            dirs[host_path] = carried.back(host_path, directories[host_path])

        return {
            "exit_code": process.returncode,
            "stdout": stdout or b"",
            "stderr": stderr or b"",
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


def handle_which(names, allowed=None):
    """Where each allowed name resolves here, or None: for a caller choosing between several."""
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ExecuteError(-32602, "names must be a list of strings")
    allowed = ALLOWED_COMMANDS if allowed is None else allowed
    return {name: (resolve_command(name, allowed) if name in allowed else None) for name in names}


_JSON_PARAMS = ("command", "stdin", "cwd", "input_files", "output_files", "input_dirs", "output_dirs", "lock", "env")
_FRAME_PARAMS = (
    "command",
    "stdin",
    "cwd",
    "input_files",
    "output_files",
    "input_trees",
    "blobs",
    "output_dirs",
    "lock",
    "env",
)


def dispatch(payload, frames=False, store=None):
    """One JSON-RPC request object, answered as one JSON-RPC response object.

    ``frames`` says which dialect the request came in, and so which one
    ``execute`` reads and answers in (see the module's docstring).
    """
    request_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("method") is None:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid request"}}
    if payload["method"] not in ("execute", "which", "missing"):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found: %s" % payload["method"]},
        }
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Params must be an object"}}
    try:
        if payload["method"] == "which":
            result = handle_which(params.get("names"))
        elif payload["method"] == "missing":
            result = handle_missing(params.get("digests"), store)
        elif frames:
            result = handle_execute_frames(
                store=store, **dict((key, params[key]) for key in _FRAME_PARAMS if key in params)
            )
        else:
            result = handle_execute_command(**dict((key, params[key]) for key in _JSON_PARAMS if key in params))
    except ExecuteError as e:
        return {"jsonrpc": "2.0", "id": request_id, "error": e.error()}
    except Exception as e:  # pragma: no cover - reported, not crashed on
        log.exception("execute failed")
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": "Execution error: %s" % e}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def is_frame(content_type):
    """Whether a `Content-Type` says the body is a frame."""
    return (content_type or "").split(";", 1)[0].strip().lower() == FRAME_TYPE


class _Handler(BaseHTTPRequestHandler):
    token = None
    store = None
    protocol_version = "HTTP/1.1"

    def _reply(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _reply_frame(self, status, body):
        # Buffer by buffer, as `encode_frame` made them: what a command wrote
        # goes to the socket from where it was read into.
        parts = encode_frame(body)
        self.send_response(status)
        self.send_header("Content-Type", FRAME_TYPE)
        self.send_header("Content-Length", str(frame_length(parts)))
        self.end_headers()
        for part in parts:
            self.wfile.write(part)

    def do_GET(self):  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        self._reply(200, {"ok": True, "protocol": PROTOCOL})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if self.path.rstrip("/") != "/jsonrpc":
            # Read even so: the connection is kept open, and a body left
            # unread would be read as the next request.
            self.rfile.read(length)
            self._reply(404, {"error": "not found"})
            return
        if not _authorized(self.headers.get("Authorization"), self.token):
            self.rfile.read(length)
            self._reply(401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}})
            return
        body = self.rfile.read(length)
        if is_frame(self.headers.get("Content-Type")):
            try:
                payload = decode_frame(body)
            except ValueError as e:
                self._reply_frame(
                    200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error: %s" % e}}
                )
                return
            self._reply_frame(200, dispatch(payload, frames=True, store=self.store))
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            self._reply(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return
        self._reply(200, dispatch(payload, store=self.store))

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)


class Server(ThreadingMixIn, HTTPServer):
    """One thread per request: a long command must not hold up the readiness probe."""

    daemon_threads = True
    allow_reuse_address = True


def serve(host="0.0.0.0", port=DEFAULT_PORT, token=None, store=None):
    """A server bound and ready to `serve_forever()`, for this process or a test.

    ``store`` is where content sent by digest is kept; the default store
    (`STORE_ROOT`) unless given.
    """
    handler = type("Handler", (_Handler,), {"token": token, "store": store})
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_class = type("BoundServer", (Server,), {"address_family": family})
    return server_class((host, port), handler)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    port = int(os.environ.get("PC_CONTAINER_PORT") or DEFAULT_PORT)
    token = os.environ.get("PC_CONTAINER_TOKEN") or None
    server = serve("0.0.0.0", port, token)
    log.info(
        "PartCAD container service (protocol %d) on port %d; allowed: %s; store: %s",
        PROTOCOL,
        port,
        ", ".join(sorted(ALLOWED_COMMANDS)),
        STORE_ROOT,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
