#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An interpreter that has imported the CAD stack once, and forks every wrapper off itself.

A wrapper is a short script in a long-starting interpreter. Measured in a
provisioned sandbox: a bare ``python -sOOu`` is 28 ms, ``wrapper_common`` brings
it to 62 ms, OCP to 1.45 s and build123d to between 4.6 and 5.7 s -- against
13 ms for the request and the answer of a 2.3 MB part. Every call into a sandbox
started all of that afresh, so a package of small parts was mostly imports.

This is the other way to start one. The runtime starts this script once per
sandbox environment, with the interpreter, the flags and the environment a
wrapper would get (see ``partcad.sandbox_zygote``, the other end). It imports
the stack (`PRELOAD`), starts no thread, and then waits. For each request it
forks: the child takes the request's standard streams -- the very pipes the
runtime reads, handed over as descriptors -- its argv and its directory, and
runs the wrapper as ``__main__``, the way ``python <script>`` would have. So
the wrapper protocol is unchanged and the wrapper cannot tell, except that its
imports are already done.

Forking per request rather than serving requests in one long-lived interpreter
is what answers the two questions that kind of reuse raises:

* **Crash isolation.** A wrapper that segfaults takes its own process with it,
  as it always did. This one is the parent of every child and never runs a
  wrapper, so nothing a request does reaches it.
* **State bleed.** Every child is a copy of this process as it was before any
  request, so whatever a wrapper leaves behind -- a module global, an
  ``os.chdir``, a monkeypatch, a half-built OCCT cache -- dies with it. A
  request answers the same alone as after a thousand others.

What a child is not is a *fresh* interpreter, and the differences are the ones
listed here. Its imports were made before it existed, so anything they printed
went to this process's log, once, rather than into every wrapper's standard
error; and they were made in `PRELOAD` order, which for a wrapper that would not
have imported them is modules it never asked for (none of them looks at what
else is loaded). ``random`` reseeds itself in a forked child and numpy's global
generator is reseeded here, so neither hands every child the same stream.
``sys.orig_argv`` is the wrapper's command line; the kernel's (``ps``,
``/proc/<pid>/cmdline``) is this script's.

**No thread may exist when this forks**, because a fork copies only the thread
that calls it, and any lock another thread held is held for good in the child.
So this starts none, and checks before every fork (`_threads`). OCCT's and
TBB's pools start on first use, which only a request reaches; OpenBLAS starts
one as it loads, and stops it at a fork (`_settle`). If anything else it
imported did start one, it says so and stops, and the runtime goes back to a
fresh interpreter per call.

The protocol is JSON over the ``AF_UNIX``/``SOCK_SEQPACKET`` socket the runtime
hands this process -- its descriptor is the first argument, and it is the only
thing this process inherits -- with descriptors passed as ``SCM_RIGHTS``:

* ``{"ready": true, ...}`` is the first message this sends, once it has
  imported what it could: what it preloaded, what was not installed, and the
  files whose change means it is out of date (`_watch_list`). Or ``{"ready":
  false, "reason": ...}``, and it exits.
* A request is ``{"argv": [...], "script": <index>, "cwd": ..., "session":
  bool}`` with four descriptors: the child's standard input, output and error,
  and a socket of the request's own that every answer about it goes to.
* On that socket: ``{"pid": n}`` once the child exists, with a pidfd for it
  where the kernel has them, or ``{"error": ...}`` when no child was started --
  which is the only case in which the runtime may start the command some other
  way. Then ``{"exit": status}`` when the child has been reaped: the exit code,
  or minus the signal that killed it, as ``Popen.returncode`` reads.
* Closing that socket from the other end kills the child (its group, when it
  leads one), whatever it is doing: it is how a cancelled call, and a runtime
  that is itself gone, reach a child they did not start.
* Closing the control socket retires this process: it takes no more requests,
  and exits once the children it has are gone. So does an idle period with no
  request and no child (the second argument, in seconds).

Standard library only, and the syntax of every interpreter a sandbox may have:
it is run by path, out of PartCAD's own ``wrappers/``, in an interpreter that
has none of PartCAD installed. Linux only -- see ``partcad.sandbox_zygote`` for
why the runtime asks for one nowhere else.
"""

# What the module's globals held before anything here ran: the names a fresh
# interpreter's '__main__' starts out with, which a wrapper's '__main__' is
# given in turn.
_FRESH_MAIN_NAMES = tuple(sorted(globals()))

import gc
import importlib
import json
import os
import selectors
import signal
import socket
import sys
import time

PROTOCOL = 1

# What every wrapper call paid for in a fresh interpreter, in the order it has
# to be imported in. 'pyexpat' comes before anything that can load OCP: VTK,
# which the OCP build links against, bundles an older expat under the same
# 'XML_*' names, and whichever loads first wins for the process (see
# 'ocp_serialize'). The two of PartCAD's own are imported by every wrapper; the
# rest is the CAD stack, and a name that is not installed in this environment
# is passed over -- a plugin's sandbox may hold no CAD stack at all.
#
# Anything else that fails to import stops this process instead of being
# skipped: a module that half-imported has left native libraries loaded and
# submodules registered, and a child of that is not what a fresh interpreter
# importing the same thing would be.
PRELOAD = (
    "pyexpat",
    "ocp_serialize",
    "wrapper_common",
    "OCP",
    "build123d",
    "cadquery",
    "ocp_tessellate.ocp_utils",
)

# Of those, the ones without which there is no point in being here.
REQUIRED = ("pyexpat", "ocp_serialize", "wrapper_common")

# What one message may be, and how many descriptors may come with one.
MAX_MESSAGE = 1 << 20
MAX_FDS = 8

# 'prctl(PR_SET_PDEATHSIG, ...)', so that a child dies with this process rather
# than running on with nobody left to say how it ended.
_PR_SET_PDEATHSIG = 1

WRAPPERS = os.path.dirname(os.path.abspath(__file__))


def _send(sock, message, fds=()):
    data = json.dumps(message).encode("utf-8")
    if fds:
        socket.send_fds(sock, [data], list(fds))
    else:
        sock.send(data)


def _receive(sock):
    """One message and the descriptors that came with it; ``(None, [])`` at the end of the stream."""
    data, fds, flags, _ = socket.recv_fds(sock, MAX_MESSAGE, MAX_FDS)
    if flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0)):
        for fd in fds:
            _close(fd)
        raise ValueError("a message too long, or with too many descriptors")
    if not data:
        for fd in fds:
            _close(fd)
        return None, []
    return json.loads(data.decode("utf-8")), fds


def _close(fd):
    try:
        os.close(fd)
    except OSError:
        pass


def _threads():
    """How many threads this process has, as the kernel counts them -- native ones included."""
    try:
        return len(os.listdir("/proc/self/task"))
    except OSError:
        import threading

        return threading.active_count()


def _top(name):
    return name.split(".", 1)[0]


def _preload(names):
    """Import ``names``; return what was imported and what is not installed here.

    The wrappers' own directory is on 'sys.path' only for as long as this
    takes: a wrapper appends it itself (``sys.path.append(os.path.dirname(
    __file__))``), and a child's path has to be the one a fresh interpreter
    hands it.
    """
    added = WRAPPERS not in sys.path
    if added:
        sys.path.append(WRAPPERS)
    loaded, absent = [], []
    try:
        for name in names:
            try:
                importlib.import_module(name)
            except ModuleNotFoundError as e:
                # Only the module itself missing is "not installed". One of
                # its own dependencies missing is a broken install, and that
                # has imported half of it.
                if name in REQUIRED or e.name not in (name, _top(name)):
                    raise
                absent.append(name)
                continue
            loaded.append(name)
        if "OCP" in loaded:
            # The table 'ocp_serialize' builds on first use, and the
            # submodules it imports: the same in every child, so built once.
            sys.modules["ocp_serialize"]._ensure_ocp()
    finally:
        if added:
            try:
                sys.path.remove(WRAPPERS)
            except ValueError:
                pass
    return loaded, absent


def _watch_list():
    """The files and directories whose change means this process is out of date.

    What it imported came from these: every directory on 'sys.path' (pip and
    conda add and remove entries there whenever they install anything, which
    moves the directory's modification time), the interpreter itself, and every
    module it loaded out of PartCAD's own 'wrappers/' -- an edited
    'ocp_serialize.py' is read afresh by a fresh interpreter, and has to be here
    too. The runtime stats these before every request, which is how an install
    by *another* process retires this one.
    """
    paths = [os.path.realpath(sys.executable)]
    for entry in sys.path:
        if entry and os.path.isdir(entry) and entry not in paths:
            paths.append(entry)
    wrappers = os.path.realpath(WRAPPERS)
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and os.path.realpath(os.path.dirname(path)) == wrappers and path not in paths:
            paths.append(os.path.abspath(path))
    return paths


def _settle():
    """Fork once, to nothing, so that the threads a library keeps only until a fork are gone.

    OpenBLAS -- numpy's, and scipy's own copy, both of which build123d imports
    -- starts a pool of worker threads as it loads, one fewer than the cores, and
    hands them to 'pthread_atfork': it stops and joins them just before a fork,
    and starts them again on its next use, in the parent and in the child alike.
    This process never uses it, so one fork is all it takes for it to have no
    thread but its own. A child starts the pool afresh on its first matrix
    product, at the size a fresh interpreter would have given it -- unlike the
    other way to get rid of it, 'OPENBLAS_NUM_THREADS=1', which every child
    would have inherited.

    What `_threads` counts after this is what is really running, and anything
    still there is a reason not to fork at all.
    """
    if _threads() == 1:
        return
    try:
        pid = os.fork()
    except OSError:
        return
    if pid == 0:
        os._exit(0)
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass


def _libc_prctl():
    try:
        import ctypes

        return ctypes.CDLL(None, use_errno=True).prctl
    except Exception:
        return None


class _Zygote:
    def __init__(self, control, idle):
        self.control = control
        self.idle = idle
        self.pid = os.getpid()
        self.prctl = _libc_prctl()
        self.selector = selectors.DefaultSelector()
        self.wake_r, self.wake_w = os.pipe()
        os.set_blocking(self.wake_r, False)
        os.set_blocking(self.wake_w, False)
        # pid -> the request's socket, for as long as the child is not reaped.
        self.children = {}
        # Cleared when retired: no more requests, and an exit once the children
        # are gone.
        self.accepting = True

    # ----------------------------------------------------------- the loop --

    def serve(self):
        """Answer requests until retired. Returns only in a forked child, with what it is to run."""
        signal.set_wakeup_fd(self.wake_w)
        signal.signal(signal.SIGCHLD, lambda *_: None)
        # Ctrl-C at a terminal is the foreground group's, and that is PartCAD's
        # own and this process's: a child keeps the interpreter's own handler
        # and is interrupted, as a wrapper always was, while this one stays to
        # say how the child ended.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.selector.register(self.control, selectors.EVENT_READ, "control")
        self.selector.register(self.wake_r, selectors.EVENT_READ, "wake")
        last = time.monotonic()
        while self.accepting or self.children:
            timeout = None
            if self.accepting and not self.children and self.idle > 0:
                timeout = max(0.0, last + self.idle - time.monotonic())
            events = self.selector.select(timeout)
            if not events and timeout is not None and not self.children and time.monotonic() >= last + self.idle:
                return None
            for key, _ in events:
                if key.data == "control":
                    child = self._request()
                    last = time.monotonic()
                    if child is not None:
                        return child
                elif key.data == "wake":
                    self._drain_wake()
                    self._reap()
                else:
                    self._caller_gone(key.data)
            # A SIGCHLD that arrived while the loop was busy elsewhere has
            # written to the wake pipe and will be seen; reaping here too keeps
            # a child's exit from waiting for the next event.
            self._reap()
        return None

    def _drain_wake(self):
        try:
            while os.read(self.wake_r, 4096):
                pass
        except (BlockingIOError, InterruptedError):
            pass

    def _reap(self):
        while self.children:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return
            reply = self.children.pop(pid, None)
            if reply is None:
                continue
            try:
                self.selector.unregister(reply)
            except (KeyError, ValueError):
                pass
            try:
                _send(reply, {"exit": os.waitstatus_to_exitcode(status)})
            except OSError:
                pass
            reply.close()

    def _caller_gone(self, pid):
        """The caller closed its end of a request's socket, or wrote to it: stop the child."""
        reply = self.children.get(pid)
        if reply is None:
            return
        try:
            self.selector.unregister(reply)
        except (KeyError, ValueError):
            pass
        # Not reaped yet, so 'pid' is still this child, and so is the group it
        # leads: a group id is not handed out while its leader's process
        # exists, zombie or not.
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    def _request(self):
        try:
            message, fds = _receive(self.control)
        except (OSError, ValueError):
            return None
        if message is None:
            # Retired, or the runtime is gone. Children still running finish
            # (or are stopped by their own sockets closing) and are reaped.
            self.accepting = False
            self.selector.unregister(self.control)
            return None
        if len(fds) != 4:
            for fd in fds:
                _close(fd)
            return None
        stdio, reply_fd = fds[:3], fds[3]
        reply = socket.socket(fileno=reply_fd)
        problem = self._refusal(message, reply)
        if problem is not None:
            for fd in stdio:
                _close(fd)
            try:
                _send(reply, {"error": problem})
            except OSError:
                pass
            reply.close()
            return None
        try:
            pid = os.fork()
        except OSError as e:
            for fd in stdio:
                _close(fd)
            try:
                _send(reply, {"error": "fork failed: %s" % e})
            except OSError:
                pass
            reply.close()
            return None
        if pid == 0:
            self._become(message, stdio, reply)
            return message
        for fd in stdio:
            _close(fd)
        pidfd = None
        try:
            pidfd = os.pidfd_open(pid)
        except (AttributeError, OSError):
            pass
        try:
            _send(reply, {"pid": pid}, [pidfd] if pidfd is not None else ())
        except OSError:
            # Nobody to answer to: the caller gave up between asking and now.
            pass
        if pidfd is not None:
            _close(pidfd)
        self.children[pid] = reply
        self.selector.register(reply, selectors.EVENT_READ, pid)
        return None

    def _refusal(self, message, reply):
        """Why this request is not forked, or None. A refused one is started some other way, and fails there."""
        if _threads() != 1:
            # Nothing can be forked from here any more; say so and stop.
            self.accepting = False
            return "this process has %d threads, and forking it would copy one" % _threads()
        try:
            argv = message["argv"]
            script = argv[message["script"]]
            cwd = message["cwd"]
        except (KeyError, IndexError, TypeError):
            return "not a request"
        # Refused rather than failed in the child: what a fresh interpreter
        # does with a missing script or directory is the error the caller has
        # to see, so the caller starts one and sees it.
        if not os.path.isfile(script) or not os.access(script, os.R_OK):
            return "no script at %s" % script
        if not os.path.isdir(cwd):
            return "no directory at %s" % cwd
        # The caller may have given up already, in which case nothing is
        # waiting for this child and it must not run.
        try:
            if reply.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b"":
                return "the caller has gone"
        except BlockingIOError:
            pass
        except OSError:
            return "the caller has gone"
        return None

    # ------------------------------------------------------- in the child --

    def _become(self, message, stdio, reply):
        """Turn this fork into the process a fresh interpreter would have been, up to running the script."""
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        # Everything this process holds for its own use, so that nothing in a
        # child keeps a request of somebody else's open, or the control socket.
        self.selector.close()
        for sock in [self.control, reply, *self.children.values()]:
            try:
                sock.close()
            except OSError:
                pass
        self.children = {}
        _close(self.wake_r)
        _close(self.wake_w)
        if message.get("session"):
            # What 'start_new_session' does for a bounded run: the bound kills
            # a group, and this child is to lead it.
            os.setsid()
        if self.prctl is not None:
            self.prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)
            if os.getppid() != self.pid:
                # Gone between the fork and the call: nobody would hear of us.
                os._exit(1)
        for target, fd in enumerate(stdio):
            os.dup2(fd, target)
        for fd in stdio:
            if fd > 2:
                _close(fd)
        os.chdir(message["cwd"])


def _main_module(message):
    """The ``__main__`` a fresh ``python <script>`` would have run the script in, made current; and the script."""
    import importlib.machinery
    import types

    argv = message["argv"]
    index = message["script"]
    script = argv[index]
    path = os.path.abspath(script)
    sys.argv = list(argv[index:])
    if hasattr(sys, "orig_argv"):
        sys.orig_argv = list(argv)
    # Prepended by a fresh interpreter unless PYTHONSAFEPATH (or -P) says not
    # to -- and then it was prepended for this script too, so it is this
    # script's directory that is in its place.
    if not getattr(sys.flags, "safe_path", False) and sys.path:
        if os.path.realpath(sys.path[0]) == os.path.realpath(WRAPPERS):
            sys.path[0] = os.path.dirname(os.path.realpath(path))

    module = types.ModuleType("__main__")
    if "__annotations__" in _FRESH_MAIN_NAMES:
        # Which interpreters start '__main__' with one is theirs to say.
        module.__annotations__ = {}
    module.__file__ = path
    module.__cached__ = None
    module.__loader__ = importlib.machinery.SourceFileLoader("__main__", path)
    module.__spec__ = None
    module.__package__ = None
    module.__builtins__ = sys.modules["builtins"]
    sys.modules["__main__"] = module

    numpy_random = sys.modules.get("numpy.random")
    if numpy_random is not None:
        # The legacy global generator was seeded once, here, and every child
        # would otherwise draw the same numbers from it.
        numpy_random.seed()

    sys.excepthook = _without_this_frame(sys.excepthook)
    return module, path


def _without_this_frame(hook):
    """``hook``, handed a traceback that starts in the script rather than in this file."""
    here = os.path.abspath(__file__)

    def excepthook(kind, value, tb):
        while tb is not None and os.path.abspath(tb.tb_frame.f_code.co_filename) == here:
            tb = tb.tb_next
        try:
            value = value.with_traceback(tb)
        except Exception:
            pass
        hook(kind, value, tb)

    return excepthook


def _stamps(paths):
    """What each of ``paths`` is on disk now, as the runtime compares it (``sandbox_zygote._stamp``)."""
    stamps = []
    for path in paths:
        try:
            status = os.stat(path)
            stamps.append([path, [status.st_mtime_ns, status.st_ino, status.st_size]])
        except OSError:
            stamps.append([path, None])
    return stamps


def main(argv):
    control = socket.socket(fileno=int(argv[1]))
    idle = float(argv[2]) if len(argv) > 2 else 0.0
    preload = [name for name in argv[3].split(",") if name] if len(argv) > 3 else list(PRELOAD)
    # Taken before anything is imported, so that the runtime can tell whether
    # what this imports from changed while it was importing it: an install by
    # another process, half done, is a mixture no fresh interpreter would be.
    before = _stamps([os.path.realpath(sys.executable)] + [e for e in sys.path if e and os.path.isdir(e)])
    try:
        loaded, absent = _preload(preload)
    except BaseException as e:  # whatever it was, the answer is "not ready"
        try:
            _send(control, {"ready": False, "reason": "preloading failed: %s: %s" % (type(e).__name__, e)})
        except OSError:
            pass
        return None
    # Objects made by the imports are never garbage, and a collection in a
    # child that walked them would write to every page they are on -- copying,
    # in each child, the pages a fork was meant to share.
    gc.collect()
    if hasattr(gc, "freeze"):
        gc.freeze()
    sys.stdout.flush()
    sys.stderr.flush()
    _settle()
    threads = _threads()
    if threads != 1:
        try:
            _send(
                control,
                {"ready": False, "reason": "%d threads after preloading %s" % (threads, ", ".join(loaded))},
            )
        except OSError:
            pass
        return None
    _send(
        control,
        {
            "ready": True,
            "protocol": PROTOCOL,
            "pid": os.getpid(),
            "preloaded": loaded,
            "absent": absent,
            "watch": _watch_list(),
            "before": before,
        },
    )
    return _Zygote(control, idle).serve()


def _run(module, path):
    """Run the script at ``path`` as ``module``; the status a fresh interpreter would have exited with.

    What the interpreter does with what escapes a script, done here because
    this process does not end the way a fresh one does (see `_finish`): a
    ``SystemExit`` is its code, or its message on standard error and 1; any
    other exception -- a ``SyntaxError`` in the script among them -- is handed
    to ``sys.excepthook`` and is 1; an interrupt is the interrupt, re-raised as
    the signal on the way out.
    """
    try:
        with open(path, "rb") as f:
            source = f.read()
        # Compiled as the interpreter compiles a script: its own optimization
        # level (-OO), and none of this file's future features.
        code = compile(source, path, "exec", dont_inherit=True)
        del source
        exec(code, module.__dict__)
    except SystemExit as e:
        if e.code is None:
            return 0
        if isinstance(e.code, int):
            return e.code
        try:
            sys.stderr.write("%s\n" % (e.code,))
        except Exception:
            pass
        return 1
    except BaseException:
        kind, value, tb = sys.exc_info()
        try:
            sys.excepthook(kind, value, tb)
        except Exception:
            pass
        return -int(signal.SIGINT) if issubclass(kind, KeyboardInterrupt) else 1
    return 0


def _finish(status, inherited):
    """End this child as interpreter shutdown would, short of tearing down what it was forked with.

    Shutdown is the one part of a fresh interpreter's life that a fork makes
    *dearer*. It frees every object of every module, and in a child each of
    those writes is a copy of a page it shares with this process: measured,
    0.4 s of a call whose work had taken 0.04 s. So a child does what shutdown
    does that anybody could see and skips what nobody can:

    * it waits for the threads it started, and runs every ``atexit`` handler,
      the ones its imports registered here included -- in the interpreter's
      own order, through the interpreter's own functions;
    * it writes out what every file it left open still buffers (`_flush_writers`);
    * it lets go of what *it* made: the script's ``__main__`` and every module
      it imported itself are released the way the interpreter releases them,
      so a file left open is closed, a temporary file is deleted, and a
      ``__del__`` runs, as it would have;
    * it flushes Python's standard streams and C's, which a native library may
      have printed into;

    and leaves the CAD stack it was forked with to the kernel, which takes a
    process's memory back in one piece.
    """
    try:
        threading = sys.modules.get("threading")
        if threading is not None:
            threading._shutdown()
    except BaseException:
        pass
    try:
        import atexit

        atexit._run_exitfuncs()
    except BaseException:
        pass
    try:
        _flush_writers()
        _release(inherited)
    except BaseException:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    try:
        import ctypes

        ctypes.CDLL(None).fflush(None)
    except Exception:
        pass
    if status == -int(signal.SIGINT):
        # How an interpreter ends on an interrupt nothing caught: by the
        # signal itself, so that whoever waits for it sees one.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGINT)
    os._exit(status & 0xFF)


def _flush_writers():
    """Flush every file object this child opened and did not close.

    Before anything is released rather than by the releasing: a script's
    ``__main__`` is garbage in a cycle, and a collection finalizes the objects
    of a cycle in no particular order -- a text file's buffer can be closed
    before the text file, and what the text file still held is then lost. A
    fresh interpreter's shutdown happens to get the order right; this does not
    depend on it. Only what the child made is looked at: what this process
    imported was frozen out of the collector's reach before it forked.
    """
    import io

    writers = (io.TextIOWrapper, io.BufferedWriter, io.BufferedRandom)
    for obj in gc.get_objects():
        if isinstance(obj, writers):
            try:
                if not obj.closed:
                    obj.flush()
            except Exception:
                pass


def _release(inherited):
    """Let go of ``__main__`` and every module imported after the fork, the way interpreter shutdown does.

    Taken out of 'sys.modules' and collected, which frees whatever only they
    held; and whichever of them is still alive after that has its namespace
    cleared, latest import first, the way '_PyModule_ClearDict' clears one --
    the names with one leading underscore, then the rest but '__builtins__' --
    and is collected again.
    """
    import weakref

    alive = []
    for name in [n for n in reversed(list(sys.modules)) if n not in inherited or n == "__main__"]:
        module = sys.modules.pop(name, None)
        try:
            alive.append(weakref.ref(module))
        except TypeError:
            pass
    module = None
    gc.collect()
    for ref in alive:
        namespace = getattr(ref(), "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for name in [n for n in namespace if n.startswith("_") and not n.startswith("__")]:
            namespace[name] = None
        for name in [n for n in namespace if n != "__builtins__"]:
            namespace[name] = None
        namespace = None
    gc.collect()


if __name__ == "__main__":
    _request = main(sys.argv)
    if _request is None:
        sys.exit(0)
    _inherited = set(sys.modules)
    # Nothing here keeps a reference to the script's '__main__' past '_run':
    # '_finish' lets go of it the way shutdown would, and a name bound here
    # would keep it alive.
    _finish(_run(*_main_module(_request)), _inherited)
