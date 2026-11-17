#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One read-edit-write of a package's 'partcad.yaml' at a time.

Every writer of 'partcad.yaml' reads the file, changes what it read and replaces
the file with that. Two at once -- the daemon serves HTTP requests on a pool of
threads, and a package can be loaded (which pins a tracked dependency into the
file) while another request edits it -- would both read the file as it was, and
the later replace would drop what the earlier one wrote with nothing said.

So each takes this lock for the whole of it. It is a file in PartCAD's own state
folder named after the file it guards, so it holds across threads and processes
and leaves nothing in the package; and a writer that another writer calls, in
the same thread, is part of that edit and does not take it again -- it would
otherwise wait for itself.
"""

import contextlib
import hashlib
import os
import threading

# How long an edit waits for another one of the same file to finish. Each holds
# it for one read and one write of the file.
TIMEOUT = 60

# The files each thread is in the middle of editing.
_HELD = threading.local()


@contextlib.contextmanager
def editing(config_path: str, state_dir: str):
    """Hold the lock on 'config_path' (kept under 'state_dir') for the body; ValueError when it is not had in time."""
    from filelock import FileLock, Timeout

    target = os.path.realpath(config_path)
    held = getattr(_HELD, "files", None)
    if held is None:
        held = _HELD.files = set()
    if target in held:
        yield
        return
    folder = os.path.join(state_dir, "locks", "edit")
    os.makedirs(folder, exist_ok=True)
    name = hashlib.sha256(target.encode("utf-8")).hexdigest()[:32] + ".lock"
    lock = FileLock(os.path.join(folder, name), mode=0o600)
    try:
        lock.acquire(timeout=TIMEOUT)
    except Timeout:
        raise ValueError(
            "'%s' is being changed by another edit, which has not finished in %d seconds: try again"
            % (config_path, TIMEOUT)
        ) from None
    held.add(target)
    try:
        yield
    finally:
        held.discard(target)
        lock.release()
