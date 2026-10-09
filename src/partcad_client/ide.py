#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The editor on this machine: putting the PartCAD extension into it, and opening a workspace in it.

`pc ide install` and `pc ide open <directory>` end here. Both act on **this
machine** -- an editor installed here, a folder on this disk, a window on this
screen -- which is why they are in `partcad_client` and why there is no RPC
method for either: a daemon can be remote, where "install the extension" would
install it into somebody else's editor. Same rule as `selfupdate` and
`external`.

**Which editor** is a name or a path given by the caller, or else the first of
``EDITORS`` on the ``PATH``. Every one of them is VS Code underneath and takes
the same command line (``--install-extension``, a folder to open,
``--user-data-dir``, ``--extensions-dir``), which is the whole reason one table
serves them all. The PartCAD IDE comes first because it is the one built for
this; it already carries the extension, and installing a release into it puts
that release beside the bundled one, which is what the editor then runs.

**The extension** is the ``.vsix`` published on the GitHub release
(``partcad-<version>.vsix``), which is what `deploy.yml` uploads -- the same
package the marketplace serves, from where PartCAD's own releases come from, and
reachable from a machine that has GitHub but no marketplace. A local ``.vsix``
works too, which is how a build of this tree is tried out.

**Opening a workspace in the PartCAD workbench** takes two things, because the
editor's command line can open a folder but cannot run a command in the window
it opens. So a request is written first -- one file under
``~/.partcad/ide/requests/``, naming the folder -- and the folder is opened
after it. The extension reads the requests as it activates and whenever its
window gains focus (which is what opening a folder that already has a window
does), shows the PartCAD view container in a window whose workspace is that
folder, and deletes the request. The other half is `ide/vscode/src/workbenchRequest.ts`;
the layout of the file is the contract between the two, and is written down in
both. A request nobody took is ignored once it is ``REQUEST_TTL`` old, so a
folder opened with the extension not installed does not jump to the workbench
the next time it is opened by hand.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Callable, List, Optional, Sequence

from . import selfupdate

# The extension, as the editor knows it: publisher and name. See the root
# AGENTS.md for why the name is not `partcad`.
EXTENSION_ID = "PartCAD.partcad-official"

# The editors looked for when none is named, best first. Each is the launcher an
# installer puts on the PATH, not the application binary behind it.
EDITORS = ("partcad-ide", "codium", "code")

# What the published package is called on a release.
VSIX_ASSET = "partcad-%s.vsix"

# How long an unread workspace request is honoured. Long enough for an editor
# that is not running yet to start, install nothing and activate the extension on
# a slow machine; short enough that a request the extension never read does not
# take over a window opened later by hand.
REQUEST_TTL = 300.0

# How long to wait for a launcher to hand the folder over. A VS Code launcher
# passes it to the running instance, or starts one, and exits; an application
# binary named directly does not exit at all, and is left running.
LAUNCH_SETTLE = 15.0


class IdeError(RuntimeError):
    """The editor could not be found, or did not do what was asked, with a message saying why."""


def _noop(_message: str) -> None:
    pass


# ---------------------------------------------------------------------------
# The editor
# ---------------------------------------------------------------------------


def find_editor(editor: Optional[str] = None) -> str:
    """The editor's launcher: ``editor`` when given (a name on the PATH or a path), else the first of ``EDITORS``."""
    if editor:
        if os.path.sep in editor or (os.path.altsep and os.path.altsep in editor):
            if os.path.isfile(editor) and os.access(editor, os.X_OK):
                return os.path.abspath(editor)
            raise IdeError("%s is not an executable file" % editor)
        found = shutil.which(editor)
        if found is None:
            raise IdeError("'%s' is not on the PATH. Name the editor by its path instead." % editor)
        return found
    for name in EDITORS:
        found = shutil.which(name)
        if found is not None:
            return found
    raise IdeError(
        "No editor found: none of %s is on the PATH. Install the PartCAD IDE (install.sh --ide), "
        "VSCodium or Visual Studio Code, or name one with --with." % ", ".join(EDITORS)
    )


def _run(command: List[str], log: Callable[[str], None]) -> str:
    """Run an editor command line to completion and return what it printed."""
    try:
        completed = subprocess.run(  # nosec B603 - an editor the user named or that is on their PATH
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise IdeError("could not run %s: %s" % (command[0], e)) from e
    output = completed.stdout or ""
    for line in output.splitlines():
        if line.strip():
            log(line)
    if completed.returncode != 0:
        raise IdeError("%s exited with status %d" % (os.path.basename(command[0]), completed.returncode))
    return output


# ---------------------------------------------------------------------------
# Installing the extension
# ---------------------------------------------------------------------------


def vsix_url(version: str, repo: Optional[str] = None) -> str:
    """Where a release's extension package is published.

    ``PARTCAD_BASE_URL`` replaces the release's download directory, as it does for
    `pc upgrade` and ``install.sh``, so a mirror or the artifacts of a CI run are
    exercised the same way everywhere.
    """
    base = os.environ.get("PARTCAD_BASE_URL") or "https://github.com/%s/releases/download/%s" % (
        repo or selfupdate.repository(),
        version,
    )
    return "%s/%s" % (base.rstrip("/"), VSIX_ASSET % version)


def download_vsix(version: Optional[str], dest_dir: str, log: Callable[[str], None] = _noop) -> str:
    """Download a release's ``.vsix`` into ``dest_dir`` (the latest release when ``version`` is None)."""
    repo = selfupdate.repository()
    if version is None:
        try:
            version = selfupdate._latest_release_tag(repo)
        except selfupdate.SelfUpdateError as e:
            raise IdeError(str(e)) from e
    url = vsix_url(version, repo)
    dest = os.path.join(dest_dir, VSIX_ASSET % version)
    log("Downloading %s" % url)
    try:
        selfupdate._download(url, dest)
    except selfupdate.SelfUpdateError as e:
        raise IdeError("the PartCAD extension %s could not be downloaded: %s" % (version, e)) from e
    return dest


def install_extension(
    editor: Optional[str] = None,
    version: Optional[str] = None,
    vsix: Optional[str] = None,
    editor_args: Sequence[str] = (),
    log: Callable[[str], None] = _noop,
) -> dict:
    """Install the PartCAD extension into an editor on this machine.

    From ``vsix`` (a local file) when given, else from the GitHub release
    ``version`` (the latest one when None). ``editor_args`` go on the editor's
    command line before the install -- ``--extensions-dir`` and
    ``--user-data-dir``, for an editor profile of its own. ``--force`` is always
    passed, so that installing a release over a newer one, or the same one
    again, does what it says rather than nothing.
    """
    launcher = find_editor(editor)
    with tempfile.TemporaryDirectory(prefix="partcad-vsix-") as scratch:
        if vsix is not None:
            if not os.path.isfile(vsix):
                raise IdeError("there is no file %s" % vsix)
            package = os.path.abspath(vsix)
        else:
            package = download_vsix(version, scratch, log)
        log("Installing %s into %s" % (os.path.basename(package), launcher))
        _run([launcher, *editor_args, "--install-extension", package, "--force"], log)
    return {"ok": True, "editor": launcher, "extension": EXTENSION_ID, "vsix": vsix or os.path.basename(package)}


# ---------------------------------------------------------------------------
# Opening a workspace in the PartCAD workbench
# ---------------------------------------------------------------------------


def requests_dir(home: Optional[str] = None) -> str:
    """Where workspace requests wait for the extension: ``~/.partcad/ide/requests``.

    ``$HOME`` first, as the extension's ``partcadHome()`` reads it, so the two
    agree on a machine where ``HOME`` was pointed somewhere on purpose.
    """
    home = home or os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".partcad", "ide", "requests")


def write_request(folder: str, home: Optional[str] = None, now: Optional[float] = None) -> str:
    """Ask the extension to show the PartCAD workbench in the window that opens ``folder``.

    The file is ``{"folder": <absolute path>, "view": "workbench", "requested":
    <seconds since the epoch>}``, written under a name of its own and moved into
    place, so the extension never reads half of one.
    """
    directory = requests_dir(home)
    os.makedirs(directory, exist_ok=True)
    request = {
        "folder": os.path.abspath(folder),
        "view": "workbench",
        "requested": time.time() if now is None else now,
    }
    name = uuid.uuid4().hex
    partial = os.path.join(directory, "." + name + ".tmp")
    with open(partial, "w", encoding="utf-8") as f:
        json.dump(request, f)
    final = os.path.join(directory, name + ".json")
    os.replace(partial, final)
    return final


def _launch(command: List[str]) -> None:
    """Start an editor on a folder, and fail if the launcher says it could not."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(  # nosec B603 - an editor the user named or that is on their PATH
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **kwargs,
        )
    except OSError as e:
        raise IdeError("could not start %s: %s" % (command[0], e)) from e
    try:
        _, err = process.communicate(timeout=LAUNCH_SETTLE)
    except subprocess.TimeoutExpired:
        # Still running: the application itself rather than a launcher, and
        # running is what it was asked to do.
        return
    if process.returncode != 0:
        detail = (err or b"").decode("utf-8", "replace").strip()
        raise IdeError(
            "%s exited with status %d%s"
            % (os.path.basename(command[0]), process.returncode, (": " + detail) if detail else "")
        )


def open_workspace(
    folder: str,
    editor: Optional[str] = None,
    editor_args: Sequence[str] = (),
    workbench: bool = True,
    log: Callable[[str], None] = _noop,
) -> dict:
    """Open ``folder`` as the workspace of an editor on this machine, in the PartCAD workbench.

    ``editor_args`` go on the editor's command line before the folder. With
    ``workbench`` False the folder is only opened.
    """
    if not os.path.isdir(folder):
        raise IdeError("%s is not a directory" % folder)
    folder = os.path.abspath(folder)
    launcher = find_editor(editor)
    request = write_request(folder) if workbench else None
    log("Opening %s in %s" % (folder, launcher))
    try:
        _launch([launcher, *editor_args, folder])
    except IdeError:
        if request is not None:
            try:
                os.remove(request)
            except OSError:
                pass
        raise
    return {"ok": True, "editor": launcher, "path": folder, "workbench": workbench}
