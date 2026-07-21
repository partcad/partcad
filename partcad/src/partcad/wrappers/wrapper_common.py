#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-01
#
# Licensed under Apache License, Version 2.0.
#

# This script contains code shared by all wrapper scripts.

# import fcntl  # TODO(clairbee): replace it with whatever works on Windows if needed
import locale
import os
import sys

import ocp_wire


def handle_input():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: %s <path>\n" % sys.argv[0])
        sys.exit(1)

    locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

    # Handle the input
    # - Comand line parameters
    path = os.path.normpath(sys.argv[1])
    if len(sys.argv) > 2:
        os.chdir(os.path.normpath(sys.argv[2]))
    # - Content passed via stdin
    # #   - Make stdin blocking so that we can read until EOF
    # flag = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
    # fcntl.fcntl(sys.stdin, fcntl.F_SETFL, flag & ~os.O_NONBLOCK)
    #   - Read until EOF
    input_str = sys.stdin.read()
    #   - Unpack the content received via stdin
    request = ocp_wire.deserialize(input_str)
    return path, request


def handle_output(model):
    # Serialize the output
    sys.stdout.write(ocp_wire.serialize(model))
    sys.stdout.flush()


def exception_to_str(exc):
    """Normalize an exception for the response envelope.

    The wire format carries plain data only, so an exception travels as its
    message. 'None' is preserved as 'None': several consumers distinguish
    "no exception" from "an exception whose message happens to be empty".
    """
    if exc is None:
        return None
    return str(exc)


def handle_exception(exc, cqscript=None):
    sys.stderr.write("Error: [")
    sys.stderr.write(str(exc).strip())
    sys.stderr.write("] on the line: [")

    tb = exc.__traceback__
    if tb is None:
        sys.stderr.write("No traceback available")
    else:
        # Try to move one level down if available
        if tb.tb_next is not None:
            tb = tb.tb_next
        # Check if tb is still valid
        try:
            fname = tb.tb_frame.f_code.co_filename
            if cqscript is not None and fname == "<cqscript>":
                fname = cqscript

            # Attempt to read the file and print the specific line
            try:
                with open(fname, "r") as fp:
                    lines = fp.read().split("\n")
                    if tb.tb_lineno - 1 < len(lines):
                        line = lines[tb.tb_lineno - 1]
                        sys.stderr.write(line.strip())
                    else:
                        sys.stderr.write("Line number out of range")
            except Exception as read_err:
                sys.stderr.write(f"Failed to read file {fname}: {read_err}")
        except AttributeError:
            sys.stderr.write("No traceback details available")
    sys.stderr.write("]\n")
    sys.stderr.flush()
