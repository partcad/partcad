#
# PartCAD, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-12-28
#
# Licensed under Apache License, Version 2.0.
#

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Utility functions and classes for use with running tools over LSP."""
from __future__ import annotations

import contextlib
import io
import os
import os.path
import re
import runpy
import site
import subprocess
import string
import sys
import threading
from typing import Any, Callable, List, Sequence, Tuple, Union

# Save the working directory used when loading this module
SERVER_CWD = os.getcwd()
CWD_LOCK = threading.Lock()


def as_list(content: Union[Any, List[Any], Tuple[Any]]) -> Union[List[Any], Tuple[Any]]:
    """Ensures we always get a list"""
    if isinstance(content, (list, tuple)):
        return content
    return [content]


# pylint: disable-next=consider-using-generator
_site_paths = tuple(
    [
        os.path.normcase(os.path.normpath(p))
        for p in (as_list(site.getsitepackages()) + as_list(site.getusersitepackages()))
    ]
)


def is_same_path(file_path1, file_path2) -> bool:
    """Returns true if two paths are the same."""
    return os.path.normcase(os.path.normpath(file_path1)) == os.path.normcase(os.path.normpath(file_path2))


def is_current_interpreter(executable) -> bool:
    """Returns true if the executable path is same as the current interpreter."""
    return is_same_path(executable, sys.executable)


def is_stdlib_file(file_path) -> bool:
    """Return True if the file belongs to standard library."""
    return os.path.normcase(os.path.normpath(file_path)).startswith(_site_paths)


# pylint: disable-next=too-few-public-methods
class RunResult:
    """Object to hold result from running tool."""

    def __init__(self, stdout: str, stderr: str):
        self.stdout: str = stdout
        self.stderr: str = stderr


COLOR_INFO = "\033[92m\033[1m"
COLOR_ERROR = "\033[91m"
COLOR_NONE = "\033[0m"


class CustomIO(io.TextIOWrapper):
    """Custom stream object to replace stdio."""

    name = None

    def __init__(self, name, encoding="utf-8", newline=None, mirror=None, is_errors=False):
        self._buffer = io.BytesIO()
        self._buffer.name = name
        self._mirror = mirror
        self._is_errors = is_errors
        super().__init__(self._buffer, encoding=encoding, newline=newline)

    def write(self, s):
        """Write to the buffer."""

        # Mirror the output to the terminal
        if self._mirror is not None:
            # Drop all non-printable characters to keep the terminal state
            sanitized = "".join(filter(lambda x: x in string.printable, s))
            # Fix newlines to CRLF to be consistent
            sanitized = re.sub(r"([^\r])\n", r"\1\r\n", sanitized)
            # The below two are 'string.printable' characters, but we don't want them just in case
            sanitized = re.sub(r"\v", "", sanitized)
            sanitized = re.sub(r"\f", "", sanitized)

            if self._is_errors:
                self._mirror.write(COLOR_ERROR + sanitized + COLOR_NONE)
            else:
                self._mirror.write(COLOR_INFO + sanitized + COLOR_NONE)
            self._mirror.flush()

        return super().write(s)

    def close(self):
        """Provide this close method which is used by some tools."""
        # This is intentionally empty.

    def get_value(self) -> str:
        """Returns value from the buffer as string."""
        self.seek(0)
        return self.read()


@contextlib.contextmanager
def substitute_attr(obj: Any, attribute: str, new_value: Any):
    """Manage object attributes context when using runpy.run_module()."""
    old_value = getattr(obj, attribute)
    setattr(obj, attribute, new_value)
    yield
    setattr(obj, attribute, old_value)


@contextlib.contextmanager
def redirect_io(stream: str, new_stream):
    """Redirect stdio streams to a custom stream."""
    old_stream = getattr(sys, stream)
    setattr(sys, stream, new_stream)
    yield
    setattr(sys, stream, old_stream)


@contextlib.contextmanager
def change_cwd(new_cwd):
    """Change working directory before running code."""
    os.chdir(new_cwd)
    yield
    os.chdir(SERVER_CWD)


def _run_module(
    module: str,
    argv: Sequence[str],
    use_stdin: bool,
    source: str = None,
    add_stdout=None,
    add_stderr=None,
) -> RunResult:
    """Runs as a module."""
    str_output = CustomIO("<stdout>", encoding="utf-8", mirror=add_stdout)
    str_error = CustomIO("<stderr>", encoding="utf-8", mirror=add_stderr, is_errors=True)

    try:
        with substitute_attr(sys, "argv", argv):
            with redirect_io("stdout", str_output):
                with redirect_io("stderr", str_error):
                    if use_stdin and source is not None:
                        str_input = CustomIO("<stdin>", encoding="utf-8", newline="\n")
                        with redirect_io("stdin", str_input):
                            str_input.write(source)
                            str_input.seek(0)
                            runpy.run_module(module, run_name="__main__")
                    else:
                        runpy.run_module(module, run_name="__main__")
    except SystemExit:
        pass

    return RunResult(str_output.get_value(), str_error.get_value())


def run_module(
    module: str,
    argv: Sequence[str],
    use_stdin: bool,
    cwd: str,
    source: str = None,
    add_stdout=None,
    add_stderr=None,
) -> RunResult:
    """Runs as a module."""
    with CWD_LOCK:
        if is_same_path(os.getcwd(), cwd):
            return _run_module(
                module,
                argv,
                use_stdin,
                source,
                add_stdout=add_stdout,
                add_stderr=add_stderr,
            )
        with change_cwd(cwd):
            return _run_module(
                module,
                argv,
                use_stdin,
                source,
                add_stdout=add_stdout,
                add_stderr=add_stderr,
            )


def run_path(argv: Sequence[str], use_stdin: bool, cwd: str, source: str = None) -> RunResult:
    """Runs as an executable."""
    if use_stdin:
        with subprocess.Popen(
            argv,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            cwd=cwd,
        ) as process:
            return RunResult(*process.communicate(input=source))
    else:
        result = subprocess.run(
            argv,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            cwd=cwd,
        )
        return RunResult(result.stdout, result.stderr)


def run_api(
    callback: Callable[[Sequence[str], CustomIO, CustomIO, CustomIO | None], None],
    argv: Sequence[str],
    use_stdin: bool,
    cwd: str,
    source: str = None,
) -> RunResult:
    """Run a API."""
    with CWD_LOCK:
        if is_same_path(os.getcwd(), cwd):
            return _run_api(callback, argv, use_stdin, source)
        with change_cwd(cwd):
            return _run_api(callback, argv, use_stdin, source)


def _run_api(
    callback: Callable[[Sequence[str], CustomIO, CustomIO, CustomIO | None], None],
    argv: Sequence[str],
    use_stdin: bool,
    source: str = None,
) -> RunResult:
    str_output = CustomIO("<stdout>", encoding="utf-8")
    str_error = CustomIO("<stderr>", encoding="utf-8")

    try:
        with substitute_attr(sys, "argv", argv):
            with redirect_io("stdout", str_output):
                with redirect_io("stderr", str_error):
                    if use_stdin and source is not None:
                        str_input = CustomIO("<stdin>", encoding="utf-8", newline="\n")
                        with redirect_io("stdin", str_input):
                            str_input.write(source)
                            str_input.seek(0)
                            callback(argv, str_output, str_error, str_input)
                    else:
                        callback(argv, str_output, str_error)
    except SystemExit:
        pass

    return RunResult(str_output.get_value(), str_error.get_value())
