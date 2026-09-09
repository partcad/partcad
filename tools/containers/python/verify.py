#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this image keeps the base image contract.

Run at build time, and kept in the image afterwards so that an image built
`FROM` this one can run it too -- which is the point. A plugin author adds an
apt package, moves the interpreter, drops the RPC service or switches the
working directory, and finds out here rather than from a user whose analysis
fails inside a sandbox with a message about none of it.

    docker run --rm ghcr.io/you/your-image python3 /pc/verify.py

Every check states what breaks when it fails, because a conformance check that
only says "assertion failed" leaves the reader to guess what the contract was.
"""

import json
import os
import shutil
import sys


FAILURES = []


def check(what: str, condition: bool, consequence: str) -> None:
    print("%-44s %s" % (what, "ok" if condition else "FAILED"))
    if not condition:
        FAILURES.append("%s -- %s" % (what, consequence))


def main() -> int:
    check(
        "an interpreter is on PATH as python3",
        # Resolved on PATH, which is what the sentence below is about. The old
        # spelling fell back to 'sys.executable', which is set in every normal
        # CPython run -- so the check could not fail, and an image that had
        # moved 'python3' off PATH passed it.
        shutil.which("python3") is not None,
        "the 'docker' sandbox reaches the interpreter by name through 'docker exec', so a name it "
        "cannot resolve means no sandbox at all",
    )

    check(
        "the interpreter can build a virtual environment",
        _importable("venv") and _importable("ensurepip"),
        "PartCAD creates the sandbox as a venv inside a mounted directory; without ensurepip there "
        "is nothing to install into it",
    )

    allowed = os.environ.get("PC_CONTAINER_ALLOWED_COMMANDS", "")
    parsed = {}
    try:
        parsed = json.loads(allowed) if allowed else {}
        readable = True
    except ValueError:
        readable = False
    check(
        "PC_CONTAINER_ALLOWED_COMMANDS is JSON",
        readable,
        "the RPC service reads it at startup and an unreadable one leaves the image able to run "
        "nothing at all",
    )
    check(
        "the allowlist maps 'python'",
        "python" in parsed,
        "a caller names 'python' and the image decides what that is; without the entry the 'remote' "
        "sandbox cannot start an interpreter",
    )
    check(
        "what the allowlist maps 'python' to exists",
        bool(parsed.get("python")) and os.access(parsed.get("python", ""), os.X_OK),
        "the name resolves to a file that is not there, which fails at the first command rather "
        "than at build time",
    )

    check(
        "the RPC service is at /pc",
        os.path.isfile("/pc/pc-container-json-rpc.py"),
        "the image's entrypoint serves it from there, and the 'remote' sandbox has nothing to talk "
        "to without it",
    )
    check(
        "flask_jsonrpc is importable",
        _importable("flask_jsonrpc"),
        "the service imports it at startup, so the container would exit immediately instead of "
        "serving",
    )

    state = os.environ.get("PC_INTERNAL_STATE_DIR", "")
    check(
        "PC_INTERNAL_STATE_DIR is set and writable",
        bool(state) and os.path.isdir(state) and os.access(state, os.W_OK),
        "anything the image writes for itself goes there, and a read-only one fails at run time on "
        "a machine that mounts nothing over it",
    )

    if FAILURES:
        print("\nThis image does not keep the base image contract:")
        for failure in FAILURES:
            print("  * %s" % failure)
        print("\nSee tools/containers/README.md in partcad/partcad.")
        return 1

    print("\nContract kept.")
    return 0


def _importable(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


if __name__ == "__main__":
    sys.exit(main())
