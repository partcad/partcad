#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-01
#
# Licensed under Apache License, Version 2.0.
#

# This script contains code shared by all wrapper scripts.

import base64

# import fcntl  # TODO(clairbee): replace it with whatever works on Windows if needed
import locale
import os
import pickle
import sys

from ocp_serialize import register as register_ocp_helper


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

    # TODO(clairbee): is .encode() needed here?
    request_bytes = base64.b64decode(input_str)

    register_ocp_helper()
    request = pickle.loads(request_bytes)
    return path, request


def handle_output(model):
    # Serialize the output
    register_ocp_helper()
    picklestring = pickle.dumps(model)
    response = base64.b64encode(picklestring)
    sys.stdout.write(response.decode())
    sys.stdout.flush()


def handle_exception(exc, cqscript=None):
    sys.stderr.write("Error: [")
    sys.stderr.write(str(exc).strip())
    sys.stderr.write("] on the line: [")
    tb = exc.__traceback__
    # Switch to the traceback object that contains the script line number
    tb = tb.tb_next
    # Get the filename
    fname = tb.tb_frame.f_code.co_filename
    if cqscript is not None and fname == "<cqscript>":
        fname = cqscript

    # Get the line contents
    with open(fname, "r") as fp:
        lines = fp.read().split("\n")
        if tb.tb_lineno - 1 < len(lines):
            line = lines[tb.tb_lineno - 1]
            sys.stderr.write(line.strip())
    sys.stderr.write("]\n")
    sys.stderr.flush()
