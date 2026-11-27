#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Who the user is to git, on *this* machine: the author of a revision a client asks a daemon to make.

A daemon can be on somebody else's machine, and its git configuration names
whoever runs it there; so the client asks its own git -- in the package's
directory, where a repository-local identity applies -- and sends what it says
with the request, as a comment is signed (see 'partcad_utils.comments.author').
"""

import os
import subprocess
import typing


def _config(key: str, directory: typing.Optional[str]) -> typing.Optional[str]:
    cwd = directory if directory and os.path.isdir(directory) else None
    try:
        found = subprocess.run(
            ["git", "config", key],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = found.stdout.strip() if found.returncode == 0 else ""
    return value or None


def identity(directory: typing.Optional[str] = None) -> dict:
    """{'name', 'email'} as 'git config user.name' and 'user.email' say them; a value git does not know is left out."""
    found = {}
    for key, setting in (("name", "user.name"), ("email", "user.email")):
        value = _config(setting, directory)
        if value:
            found[key] = value
    return found
