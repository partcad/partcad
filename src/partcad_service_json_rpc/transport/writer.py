#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What one connection is sent, written by a thread of its own.

Responses and notifications used to be written by the thread serving the
request, while it held the dispatch lock -- so a client that stopped reading (an
extension host busy for a while, a terminal paused with Ctrl-S, a debugger
stopped on a breakpoint) filled its socket buffer, the next write blocked, and
the daemon stopped serving *everyone* until that one client read again.

So every frame for a connection goes into a queue here, and a thread of the
connection's own sends them in order. Serving a request only ever encodes and
queues: what the client does with its end is no longer anybody else's problem.

**A client that stops reading is dropped**, not waited for and not buffered for
without limit. Whichever comes first:

* :data:`WRITE_TIMEOUT` seconds with something to send and not one byte of it
  accepted. A client that is reading, however slowly, is never cut off by this;
  one that is not reading at all for a minute has stopped, or is stopped in a
  debugger, and what it is owed in the meantime only grows.
* More than :data:`MAX_BACKLOG` bytes queued behind the frame being written. The
  frame being written is not counted: it is the answer the client asked for, it
  exists in memory anyway, and a big one read at the client's pace is normal.
  What piles up *behind* it while the client does not read is what would grow
  without the client's say-so -- a recursive render logs for minutes.

Dropping is shutting the socket down. The client sees its connection close,
which every client of the daemon already handles -- the editor reconnects (it
does so for a restarting daemon), ``pc`` reports that the service went away --
and the connection's own requests are cancelled, since nothing they produce can
reach anyone. Waiting instead would hold the queue in memory for as long as the
client stayed stopped, and buffering without bound would let one stuck client
take the daemon's memory -- and every other client with it.

A frame is queued whole: :func:`partcad_utils.framing.write_message` writes it a
piece at a time to this object and then flushes, and the flush is what queues
it. So the framing is called the same way as for any other stream, and two
threads writing at once each queue only frames of their own.
"""

import collections
import socket
import struct
import sys
import threading
from typing import Callable, Optional

# Seconds a client may accept nothing at all of what it is being sent before
# its connection is dropped. A minute, because a client that has not read a
# byte for that long has stopped reading rather than slowed down: the editor's
# extension host reads its socket on its event loop between everything else it
# does, and nothing it does legitimately holds that loop for a minute.
WRITE_TIMEOUT = 60.0

# Bytes that may be queued behind the frame being written before the connection
# is dropped. A connection's notifications are log lines, progress and short
# events, so this is never reached by a client that reads; it is a ceiling for
# one that does not, set where the daemon's memory, not the client, is at risk.
MAX_BACKLOG = 256 * 1024 * 1024

# Frames smaller than this are joined before they are sent, so a flood of log
# lines costs a system call per batch rather than two per line.
_JOIN_BELOW = 64 * 1024


def frame_size(frame) -> int:
    return sum(memoryview(chunk).nbytes for chunk in frame)


class SocketWriter:
    """The frames queued for one socket, and the thread that sends them.

    File-like enough for ``framing.write_message``: :meth:`write` collects the
    pieces of a frame, per thread, and :meth:`flush` queues it. ``on_drop`` is
    told why once, when the connection is dropped (see the module docstring).
    """

    def __init__(
        self,
        sock: socket.socket,
        on_drop: Optional[Callable[[str], None]] = None,
        timeout: float = WRITE_TIMEOUT,
        max_backlog: int = MAX_BACKLOG,
        name: str = "partcad-connection-writer",
    ):
        self._sock = sock
        self._on_drop = on_drop
        self._max_backlog = max_backlog
        self._cond = threading.Condition()
        self._frames: collections.deque = collections.deque()
        # Bytes queued and not yet being written.
        self._backlog = 0
        self._writing = False
        self._closing = False
        self._dropped: Optional[str] = None
        self._pieces = threading.local()
        self._timed = _send_timeout(sock, timeout)
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    # ---- the file-like half, for framing.write_message ----------------------

    def write(self, chunk) -> None:
        pieces = getattr(self._pieces, "frame", None)
        if pieces is None:
            pieces = self._pieces.frame = []
        pieces.append(chunk)

    def flush(self) -> None:
        pieces = getattr(self._pieces, "frame", None)
        if pieces:
            self._pieces.frame = []
            self.put(pieces)

    # ---- the queue ------------------------------------------------------------

    @property
    def dropped(self) -> Optional[str]:
        """Why the connection was dropped, or None while it is not."""
        return self._dropped

    def put(self, frame: list) -> None:
        """Queue one frame -- its pieces, in order. Never blocks, never raises."""
        size = frame_size(frame)
        with self._cond:
            if self._closing or self._dropped is not None:
                return
            behind = backlog_behind(self._frames, self._backlog, self._writing, size)
            # A frame on its own is never too big: the limit is on what piles
            # up behind the one being written.
            overflow = behind > self._max_backlog
            if not overflow:
                self._frames.append((frame, size))
                self._backlog += size
                self._cond.notify_all()
        if overflow:
            self._drop("it stopped reading, and %d MB were waiting for it" % (behind // (1024 * 1024)))

    def wait_sent(self, timeout: Optional[float] = None) -> bool:
        """Wait until everything queued has been sent (or dropped); False on timeout."""
        with self._cond:
            return self._cond.wait_for(
                lambda: self._dropped is not None or (not self._frames and not self._writing), timeout
            )

    def close(self, timeout: Optional[float] = None) -> None:
        """Send what is queued, then end the thread. Waits ``timeout`` at most for it."""
        with self._cond:
            self._closing = True
            self._cond.notify_all()
        self._thread.join(timeout)

    # ---- the thread -----------------------------------------------------------

    def _take(self) -> Optional[list]:
        """The next frames to send, several small ones joined; None when done."""
        with self._cond:
            while not self._frames and not self._closing and self._dropped is None:
                self._cond.wait()
            if self._dropped is not None or not self._frames:
                return None
            frame, size = self._frames.popleft()
            self._backlog -= size
            if size < _JOIN_BELOW:
                pieces = list(frame)
                total = size
                while self._frames and total < _JOIN_BELOW and self._frames[0][1] < _JOIN_BELOW:
                    more, more_size = self._frames.popleft()
                    self._backlog -= more_size
                    pieces.extend(more)
                    total += more_size
                frame = [b"".join(pieces)]
            self._writing = True
            return frame

    def _run(self) -> None:
        while True:
            frame = self._take()
            if frame is None:
                break
            try:
                for chunk in frame:
                    self._sock.sendall(chunk)
            except OSError as e:
                # With a send timeout, a client that accepted nothing for that
                # long comes back as EAGAIN; one that has gone, as EPIPE.
                if isinstance(e, (BlockingIOError, TimeoutError)) and self._timed:
                    self._drop("it accepted nothing it was sent for %gs" % self._timed)
                else:
                    self._drop("it went away (%s)" % (e.strerror or e))
                break
            finally:
                with self._cond:
                    self._writing = False
                    self._cond.notify_all()

    def _drop(self, why: str) -> None:
        with self._cond:
            if self._dropped is not None:
                return
            self._dropped = why
            self._frames.clear()
            self._backlog = 0
            self._cond.notify_all()
        try:
            # Wakes this connection's reader (it reads the end of the stream)
            # and a send blocked on it (it fails), which is what ends both.
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if self._on_drop is not None:
            try:
                self._on_drop(why)
            except Exception:  # pylint: disable=broad-except
                pass


def backlog_behind(frames, backlog: int, writing: bool, size: int) -> int:
    """Bytes that would be queued behind the frame being written, once ``size`` more is queued.

    ``frames`` are the queued frames as ``(frame, size)`` and ``backlog`` their
    total, which leaves out a frame being written. With none being written the
    next one counts as if it were -- whether the writer has picked it up yet is
    a race the client has no part in -- and with nothing queued either, the new
    frame is that one, and nothing is behind it.
    """
    if writing:
        return backlog + size
    if frames:
        return backlog - frames[0][1] + size
    return 0


def _send_timeout(sock: socket.socket, seconds: float) -> float:
    """Bound how long one send may wait for the client to read; the bound set, or 0.

    ``SO_SNDTIMEO`` rather than the socket's own timeout: that one is the
    socket's in both directions, and the reader of the same connection blocks
    in a read for as long as its client has nothing to say, which is meant to
    be forever. This option bounds sends only, in the kernel. A send that waits
    out the bound having sent nothing fails with EAGAIN; one that sent part of
    what it was given returns that much, so a client that is reading never
    reaches it.
    """
    if not seconds or seconds <= 0:
        return 0.0
    whole = int(seconds)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", whole, int((seconds - whole) * 1e6)))
    except (OSError, AttributeError, struct.error) as e:
        # Unbounded, then: the queue in front of it still keeps the daemon
        # serving, and MAX_BACKLOG still bounds what it holds.
        print("PartCAD daemon: cannot bound how long a client may not read: %s" % e, file=sys.stderr)
        return 0.0
    return seconds
