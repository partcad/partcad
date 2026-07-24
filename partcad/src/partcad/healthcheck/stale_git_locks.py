#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import glob
import os

from filelock import FileLock, Timeout

from .tests import HealthCheckReport, HealthCheckTest
from partcad.user_config import user_config


class StaleGitLocksCheck(HealthCheckTest):
    """Find git cache lock files that no running process holds.

    PartCAD guards each cached git repository with a file lock so that two
    processes never clone the same repository into the same directory at once.
    The operating system releases the lock when the process exits, but the lock
    file itself is left on disk. A lock file that no process holds is therefore
    only clutter; this check finds those and offers to remove them. A lock a
    running process still holds is left untouched.
    """

    def __init__(self):
        super().__init__(
            name="StaleGitLocks",
            tags=["git", "lock", "cache"],
            description="check for leftover git cache lock files that no running process holds",
        )
        self._git_dir = os.path.join(user_config.internal_state_dir, "git")
        self._stale: list[str] = []

    def auto_fixable(self) -> bool:
        return True

    def is_applicable(self) -> bool:
        return os.path.isdir(self._git_dir)

    def _is_unheld(self, lock_path: str) -> bool:
        """Whether 'lock_path' is a lock file no process currently holds."""
        lock = FileLock(lock_path, timeout=0)
        try:
            lock.acquire()
        except Timeout:
            # A running process holds it.
            return False
        lock.release()
        return True

    def test(self) -> HealthCheckReport:
        self._stale = []
        try:
            for lock_path in sorted(glob.glob(os.path.join(self._git_dir, "*.lock"))):
                if self._is_unheld(lock_path):
                    self._stale.append(lock_path)
                    self.findings.append(f"Stale git lock file: {lock_path}")
        except Exception as e:
            self.findings.append(f"Error checking git lock files: {e}")
        return HealthCheckReport(self.name, self.findings)

    def fix(self) -> bool:
        removed_all = True
        for lock_path in self._stale:
            # Re-check that it is still unheld: a clone may have started since
            # the test ran, and a live lock must never be removed.
            if not self._is_unheld(lock_path):
                removed_all = False
                continue
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                # Someone else already cleaned it up.
                pass
            except OSError:
                removed_all = False
        return removed_all
