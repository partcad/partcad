#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a command sends a container, and what of its answer is written back here: the client's half.

`partcad_utils.container_service` is the far half, and its docstring is the
protocol. This is what every caller of it shares -- an `Endpoint` in
`partcad_utils.containers`, the `remote` sandbox and the ``docker`` sandbox in
``upload`` mode -- so that "what travels" is decided in one place:

* **Payloads are bytes.** Standard input, a file sent on its own, and what
  comes back of either, travel in the frame dialect as they are. The request a
  wrapper reads is base64 already; base64 again around it was a third of its
  size once more, and an encode and a decode of it on every hop.
* **Directories travel by content.** A directory is sent as a *tree*: each
  file's name, mode and SHA-256. The far end keeps what it has been sent, so
  `execute` sends only what it is told is missing, and a directory that has
  not changed -- the wrappers, which every sandbox command imports; a package
  between two renders -- costs its manifest. That is the whole of what used to
  be a gzipped tar of it on every command, built and unpacked again each time.
  What is sent is compressed where that pays (`container_service.pack_blob`),
  since it is sent once and usually to another machine.

Hashing would cost more than it saves if it were done every time, so a file's
digest is remembered against what `os.stat` says about it (`digest_of`), the
way git's index remembers a checkout -- and, like git, not for a file changed
within the last moment, whose timestamp cannot yet tell one write from the
next.
"""

import collections
import hashlib
import os
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import container_service
from . import logging as pc_logging

# How recently a file may have been written and still have its digest
# remembered by its `os.stat`. A filesystem whose timestamps are coarse -- one
# second, two on FAT -- gives two writes inside that window one timestamp, and
# a digest remembered after the first would be handed out for the second.
RACY_SECONDS = 2.0

# Bounds on what is remembered, so that a daemon running for weeks over many
# packages does not hold every file it ever sent.
DIGEST_CACHE_ENTRIES = 200_000
KNOWN_SERVERS = 64
KNOWN_DIGESTS = 200_000

# How many times `execute` sends content the far end said it was missing
# before it gives up: once for what `missing` did not know about, once for
# what was trimmed from its store in between.
SEND_ATTEMPTS = 3

_DIGESTS: Dict[str, Tuple[tuple, str]] = {}
_DIGESTS_GUARD = threading.Lock()


def _stat_key(status) -> tuple:
    return (status.st_size, status.st_mtime_ns, status.st_ino, status.st_dev)


def digest_of(path: str, status=None) -> str:
    """The SHA-256 of what is in ``path``, remembered for as long as `os.stat` says it has not changed."""
    status = status or os.stat(path)
    key = _stat_key(status)
    with _DIGESTS_GUARD:
        known = _DIGESTS.get(path)
    if known is not None and known[0] == key:
        return known[1]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    found = digest.hexdigest()
    if time.time() - status.st_mtime > RACY_SECONDS:
        with _DIGESTS_GUARD:
            if len(_DIGESTS) >= DIGEST_CACHE_ENTRIES:
                _DIGESTS.clear()
            _DIGESTS[path] = (key, found)
    return found


def forget_digest(path: str) -> None:
    """Hash ``path`` again next time, whatever `os.stat` says."""
    with _DIGESTS_GUARD:
        _DIGESTS.pop(path, None)


def tree(path: str) -> Tuple[dict, Dict[str, str]]:
    """``path`` as a tree to send, and where to read each digest's content: ``(tree, {digest: file})``.

    The files are the ones `container_service.walk` says, which is what the far
    end would have unpacked from an archive of the same directory.
    """
    skipped: List[str] = []
    files, dirs, sources = [], [], {}
    for kind, name, real in container_service.walk(path, skipped):
        if kind == "dir":
            dirs.append(name)
            continue
        status = os.stat(real)
        digest = digest_of(real, status)
        files.append([name, digest, status.st_mode & 0o777])
        sources.setdefault(digest, real)
    container_service.warn_skipped(skipped, path)
    return {"files": files, "dirs": dirs}, sources


class Changed(Exception):
    """A file changed between being hashed and being sent."""


class Request:
    """One command's parameters in the frame dialect, and where what they name by digest is.

    ``upload`` says whether files travel at all: in ``mount`` mode they are at
    the same paths over there, and only standard input, the working directory
    and the environment are sent.
    """

    def __init__(
        self,
        stdin: Optional[bytes] = None,
        cwd: Optional[str] = None,
        input_files: Iterable[str] = (),
        output_files: Iterable[str] = (),
        input_dirs: Iterable[str] = (),
        output_dirs: Iterable[str] = (),
        env: Optional[Dict[str, str]] = None,
        upload: bool = True,
    ):
        if isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        self.params = {"stdin": stdin or None, "cwd": cwd}
        if env:
            self.params["env"] = dict(env)
        self.input_dirs = list(input_dirs or ()) if upload else []
        self.sources: Dict[str, str] = {}
        if not upload:
            return
        files = {}
        for path in input_files or ():
            with open(path, "rb") as f:
                files[path] = f.read()
        self.params["input_files"] = files
        self.params["output_files"] = list(output_files or ())
        if output_dirs:
            # Only when asked for: a directory sent back is a directory walked
            # and read over there.
            self.params["output_dirs"] = list(output_dirs)
        self.refresh()

    def refresh(self) -> None:
        """Walk and hash the directories again, for a request whose files changed under it."""
        if not self.input_dirs:
            return
        trees, sources = {}, {}
        for path in self.input_dirs:
            trees[path], found = tree(path)
            for digest, source in found.items():
                sources.setdefault(digest, source)
        self.params["input_trees"] = trees
        self.sources = sources

    def digests(self) -> List[str]:
        """Every digest the request's trees name, each once."""
        seen = []
        known = set()
        for found in (self.params.get("input_trees") or {}).values():
            for _name, digest, _mode in found["files"]:
                if digest not in known:
                    known.add(digest)
                    seen.append(digest)
        return seen

    def content(self, digest: str) -> bytes:
        """What is under ``digest``, read now and checked to still be it."""
        source = self.sources[digest]
        with open(source, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != digest:
            forget_digest(source)
            raise Changed(source)
        return data


# --------------------------------------------------------------------------- #
# What a server is known to have                                               #
# --------------------------------------------------------------------------- #
#
# Remembered per server -- its address, its token and, for a service holding a
# container per image, the image -- so that the second command a process sends
# a container does not ask what the first one already established. Only a hint:
# a container replaced, or a store trimmed, answers `MISSING`, and the content
# is sent then.

_KNOWN: "collections.OrderedDict[tuple, set]" = collections.OrderedDict()
_KNOWN_GUARD = threading.Lock()


def _known(key) -> set:
    with _KNOWN_GUARD:
        found = _KNOWN.get(key)
        if found is None:
            found = _KNOWN[key] = set()
            while len(_KNOWN) > KNOWN_SERVERS:
                _KNOWN.popitem(last=False)
        else:
            _KNOWN.move_to_end(key)
        return found


def _remember(key, digests) -> None:
    found = _known(key)
    with _KNOWN_GUARD:
        if len(found) + len(digests) > KNOWN_DIGESTS:
            found.clear()
        found.update(digests)


def _forget(key, digests) -> None:
    found = _known(key)
    with _KNOWN_GUARD:
        found.difference_update(digests)


def _error(answer) -> Optional[dict]:
    error = answer.get("error") if isinstance(answer, dict) else None
    return error if isinstance(error, dict) else None


def execute(
    call: Callable[..., Optional[dict]],
    key,
    command: List[str],
    request: Request,
    timeout: Optional[float] = None,
    route: Optional[dict] = None,
) -> Optional[dict]:
    """Run ``command`` through ``call``, sending only the content the far end does not have.

    ``call(method, params, timeout)`` is one JSON-RPC call in the frame
    dialect, answering the response object or None. ``key`` names the far end
    for what it is remembered to have. ``route`` is what the far end needs
    besides the digests to answer `missing` -- the image, for a service holding
    a container per image.

    So a command whose directories it already has costs one call, one that
    sends them the first time costs a small call more, and one that finds them
    gone after all costs a retry with what it lacks.
    """
    for _ in range(SEND_ATTEMPTS):
        try:
            return _execute(call, key, command, request, timeout, route)
        except Changed as e:
            pc_logging.info("%s changed while it was being sent; sending it again" % e)
            request.refresh()
    return {"error": {"code": -32000, "message": "Files kept changing while they were being sent"}}


def _execute(call, key, command, request, timeout, route) -> Optional[dict]:
    digests = request.digests()
    blobs = {}
    if digests:
        known = _known(key)
        with _KNOWN_GUARD:
            unknown = [digest for digest in digests if digest not in known]
        if unknown:
            answer = call("missing", dict(route or {}, digests=unknown), timeout)
            if isinstance(answer, dict) and isinstance(answer.get("result"), dict):
                lacking = answer["result"].get("missing") or []
            else:
                # A far end that cannot say is sent everything it might lack.
                lacking = unknown
            blobs = dict(
                (digest, container_service.pack_blob(request.content(digest)))
                for digest in lacking
                if digest in request.sources
            )

    answer = None
    for _ in range(SEND_ATTEMPTS):
        params = dict(request.params, command=list(command))
        if blobs:
            params["blobs"] = blobs
        answer = call("execute", params, timeout)
        error = _error(answer)
        if error is None or error.get("code") != container_service.MISSING:
            break
        lacking = [digest for digest in ((error.get("data") or {}).get("missing") or []) if digest in request.sources]
        _forget(key, lacking)
        if not lacking or all(digest in blobs for digest in lacking):
            break
        blobs.update((digest, container_service.pack_blob(request.content(digest))) for digest in lacking)
    if digests and isinstance(answer, dict) and "result" in answer:
        _remember(key, digests)
    return answer


# --------------------------------------------------------------------------- #
# What comes back                                                              #
# --------------------------------------------------------------------------- #


def write_back(result: dict, output_files=None, output_dirs=None, who: str = "The container") -> None:
    """Write what a command produced where its caller asked for it, and only there.

    A server that sends back something nobody asked for does not get to write
    it anywhere. A directory is written over, not mirrored -- a file the command
    deleted is left in place here rather than deleted, because a command that
    misbehaves should cost a stale file and not somebody's work -- and a file in
    it that is what was sent is not sent back at all (see
    `container_service.tree_back`).
    """
    wanted = set(output_files or ())
    for name, payload in (result.get("output_files") or {}).items():
        if name in wanted:
            with open(name, "wb") as f:
                f.write(payload)
        else:
            pc_logging.error("%s sent a file nobody asked for: %s" % (who, name))
    wanted_dirs = set(output_dirs or ())
    for name, back in (result.get("output_dirs") or {}).items():
        if name in wanted_dirs:
            os.makedirs(name, exist_ok=True)
            _write_tree(back, name)
        else:
            pc_logging.error("%s sent a directory nobody asked for: %s" % (who, name))


def _write_tree(back: dict, target: str) -> None:
    """A `container_service.tree_back` tree, written over ``target``."""
    if not isinstance(back, dict):
        raise container_service.ExecuteError(-32602, "A directory came back as something other than a tree")
    for name in back.get("dirs") or ():
        os.makedirs(container_service.below(target, name), exist_ok=True)
    for entry in back.get("files") or ():
        name, mode, data = entry
        path = container_service.below(target, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(container_service.unpack_blob(data))
        # Whether it runs, both ways: a file written over keeps the mode it had,
        # and one that stopped being executable over there stops here too.
        if isinstance(mode, int) and os.name != "nt":
            current = os.stat(path).st_mode & 0o7777
            os.chmod(path, (current & ~0o111) | (mode & 0o111))


def text(data) -> str:
    """What a command printed, as text: UTF-8, marking anything that is not (see `partcad.process_output`)."""
    if not data:
        return ""
    return str(data, "utf-8", "replace")
