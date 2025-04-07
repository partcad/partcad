#
# PartCAD, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-12-28
#
# Licensed under Apache License, Version 2.0.
#

import os
import sys
import socket


def make_pipe():
    if sys.platform[:3] != "win":
        p = PosixPipe()
    else:
        p = WindowsPipe()
    return p


class PosixPipe(object):
    def __init__(self):
        self._rfd, self._wfd = os.pipe()
        self._rfd_file = os.fdopen(self._rfd, "r")

    def close(self):
        os.close(self._rfd)
        os.close(self._wfd)

    def fileno(self):
        return self._rfd

    def read(self, bufsize):
        return os.read(self._rfd, bufsize)

    def readline(self):
        return self._rfd_file.readline()

    # def write(self, data):
    #     os.write(self._wfd, data)

    def get_write_stream(self):
        return os.fdopen(self._wfd, "w")


class WindowsPipe(object):
    """
    On Windows, only an OS-level "WinSock" may be used in select(), but reads
    and writes must be to the actual socket object.
    """

    class Stream:
        def __init__(self, wsock):
            self._wsock = wsock

        # def read(self, size):
        #     return None

        # def readLine(self, size):
        #     return None

        def write(self, data: str):
            self._wsock.send(data.encode())

        def flush(self):
            pass

        def close(self):
            socket.close(self._wsock)

    def __init__(self):
        serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serv.bind(("127.0.0.1", 0))
        serv.listen(1)

        # need to save sockets in _rsock/_wsock so they don't get closed
        self._rsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._rsock.connect(("127.0.0.1", serv.getsockname()[1]))

        self._wsock, _ = serv.accept()
        serv.close()

    def close(self):
        self._rsock.close()
        self._wsock.close()

    def fileno(self):
        return self._rsock.fileno()

    def read(self, bufsize):
        return self._rsock.recv(bufsize)

    # def write(self, data):
    #     self._wsock.send(data)

    def get_write_stream(self):
        return WindowsPipe.Stream(self._wsock)
