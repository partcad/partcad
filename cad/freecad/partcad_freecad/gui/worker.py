#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Running a PartCAD call without freezing FreeCAD.

Every service call is a round trip to another process that may clone a git
repository, provision a conda sandbox and run a CAD script -- seconds at best,
minutes the first time. Doing that on the Qt thread would freeze the whole
application, so it runs on a worker thread while a busy dialog keeps the UI
alive, and the result is handed back on the Qt thread where FreeCAD's document
API can be touched safely.
"""

from .qt import QtCore, QtWidgets, exec_loop


class _Worker(QtCore.QThread):
    """Runs one callable, capturing its result or its exception."""

    progress = QtCore.Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self._function = function
        self.result = None
        self.error = None

    def run(self):  # pragma: no cover - runs on a Qt thread
        try:
            self.result = self._function(self.progress.emit)
        except Exception as e:  # pylint: disable=broad-except
            # Re-raised on the calling thread by run_busy(); swallowing it here
            # would leave the caller looking at a silent None.
            self.error = e


def run_busy(parent, title: str, message: str, function):
    """Run ``function(progress)`` on a worker thread, showing a busy dialog.

    ``progress`` is a callable the work reports status text through. Returns the
    function's result, or re-raises whatever it raised.
    """
    dialog = QtWidgets.QProgressDialog(message, "", 0, 0, parent)
    dialog.setWindowTitle(title)
    dialog.setCancelButton(None)  # PartCAD operations are not interruptible
    dialog.setWindowModality(QtCore.Qt.ApplicationModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    loop = QtCore.QEventLoop()
    worker = _Worker(function, parent)
    worker.progress.connect(dialog.setLabelText)
    worker.finished.connect(loop.quit)
    # The thread can finish before the loop is entered -- a fast call, or a
    # failure raised immediately -- and that 'finished' would be delivered to a
    # loop that is not running yet, leaving it spinning forever. The poll closes
    # that window; it is cheap because it only runs while the dialog is up.
    poll = QtCore.QTimer()
    poll.setInterval(50)
    poll.timeout.connect(lambda: worker.isFinished() and loop.quit())

    worker.start()
    dialog.show()
    poll.start()
    exec_loop(loop)
    poll.stop()
    worker.wait()
    dialog.close()

    if worker.error is not None:
        raise worker.error
    return worker.result
