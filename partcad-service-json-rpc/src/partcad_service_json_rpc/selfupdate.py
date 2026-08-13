#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Updating the PartCAD installation itself.

PartCAD ships in two shapes and both of them have to be updatable by the same
gesture: the Python wheels on PyPI (`pip install -U partcad-cli`) and the
standalone PyInstaller bundle that carries its own interpreter (installed by
`install.sh`, or downloaded by the VS Code extension). This module is the one
place that knows the difference, so `pc update`, the `partcad-json-rpc`
executable and the VS Code extension all update the same way rather than three
slightly different ways.

Two rules shape everything here:

* **Stop the daemons first.** A running daemon holds a warm PartCAD context and
  the sandboxed runtimes, and it runs *from the files this module replaces*. It
  is asked to stop, and waited for, before anything is written -- and only once
  a newer version has actually been found, so a no-op `pc update` never costs
  anyone their warm context.
* **Never write over the running installation.** The standalone bundle is
  installed side by side, under ``<install-dir>/<version>/``, exactly the layout
  ``install.sh`` produces; the launcher symlinks are then repointed. Nothing
  deletes the directory the current process is executing from -- which is what
  makes the update safe on Windows, where that would fail outright, and what
  lets the frozen `pc` update itself.
"""

import contextlib
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from hashlib import sha256
from typing import Callable, List, Optional

from . import __version__, daemon

# How PartCAD was installed.
KIND_STANDALONE = "standalone"  # the frozen PyInstaller bundle
KIND_WHEEL = "wheel"  # `pip install partcad-cli`
KIND_SOURCE = "source"  # an editable install of a source checkout

DEFAULT_REPOSITORY = "partcad/partcad"

# The distributions that make up a wheel installation, most specific first. Only
# the ones actually installed are upgraded: `partcad-cli` pulls `partcad` in, but
# an environment provisioned for the VS Code extension has
# `partcad-service-json-rpc` and no CLI at all.
DISTRIBUTIONS = ("partcad-cli", "partcad-service-json-rpc", "partcad")

# The executables a standalone bundle contains, which is also what `install.sh`
# links into the bin directory.
BUNDLE_EXECUTABLES = ("pc", "partcad", "partcad-json-rpc")

USER_AGENT = "partcad-selfupdate"
NETWORK_TIMEOUT = 30.0


class SelfUpdateError(RuntimeError):
    """The installation cannot be updated, with a message saying what to do."""


def _noop(_message: str) -> None:
    pass


# ---------------------------------------------------------------------------
# What is installed, and where
# ---------------------------------------------------------------------------


def installation_kind() -> str:
    """Classify this installation as standalone, wheel, or source checkout."""
    if getattr(sys, "frozen", False):
        return KIND_STANDALONE
    module_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    # A wheel lands in site-packages/dist-packages; anything else (an editable
    # install, a repository checkout on PYTHONPATH) is a working copy that pip
    # must not overwrite.
    if any(part in ("site-packages", "dist-packages") for part in module_path.split(os.sep)):
        return KIND_WHEEL
    return KIND_SOURCE


def current_version() -> str:
    """The version of the running installation.

    Every component in the monorepo is released under one version, so the
    service's own is the installation's.
    """
    return __version__


def bundle_dir() -> str:
    """Directory of the running standalone bundle (its executables live in it).

    ``sys.executable`` may be reached through the ``~/.local/bin`` symlink that
    ``install.sh`` creates, so it is resolved: the update has to reason about
    where the bundle *is*, not about how it was invoked.
    """
    return os.path.dirname(os.path.realpath(sys.executable))


def install_dir() -> str:
    """Directory holding the versioned bundle directories."""
    return os.path.dirname(bundle_dir())


def repository() -> str:
    """The GitHub repository releases are downloaded from.

    ``PARTCAD_REPOSITORY`` overrides it, as it does for ``install.sh``, so a fork
    or a staging repository is exercised the same way everywhere.
    """
    return os.environ.get("PARTCAD_REPOSITORY") or DEFAULT_REPOSITORY


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def _parse_version(value: str):
    """A sortable version key. Falls back to a numeric split without packaging."""
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(value)
        except InvalidVersion:
            return None
    except ImportError:  # pragma: no cover - packaging is a hard dependency
        parts = re.findall(r"\d+", value)
        return tuple(int(p) for p in parts) if parts else None


def is_newer(candidate: str, than: str) -> bool:
    """True if ``candidate`` is a strictly newer version than ``than``.

    Unparseable versions compare as "different means newer": a user who pinned a
    version PartCAD cannot parse still gets to install it.
    """
    left, right = _parse_version(candidate), _parse_version(than)
    if left is None or right is None or type(left) is not type(right):
        return candidate != than
    return left > right


def latest_version(kind: Optional[str] = None, repo: Optional[str] = None) -> str:
    """The newest version published for this kind of installation."""
    kind = kind or installation_kind()
    if kind == KIND_STANDALONE:
        return _latest_release_tag(repo or repository())
    return _latest_pypi_version()


def _latest_release_tag(repo: str) -> str:
    """The tag of the latest GitHub release, which is also the bundle version."""
    body = _http_get(
        "https://api.github.com/repos/%s/releases/latest" % repo, {"Accept": "application/vnd.github+json"}
    )
    tag = json.loads(body.decode("utf-8")).get("tag_name")
    if not tag:
        raise SelfUpdateError("could not determine the latest release of %s" % repo)
    return tag


def _latest_pypi_version() -> str:
    """The newest version on PyPI of whichever distribution is installed."""
    for dist in _installed_distributions() or [DISTRIBUTIONS[0]]:
        body = _http_get("https://pypi.org/pypi/%s/json" % dist, {"Accept": "application/json"})
        version = json.loads(body.decode("utf-8")).get("info", {}).get("version")
        if version:
            return version
    raise SelfUpdateError("could not determine the latest PartCAD version on PyPI")


def _installed_distributions() -> List[str]:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    installed = []
    for dist in DISTRIBUTIONS:
        try:
            dist_version(dist)
        except PackageNotFoundError:
            continue
        installed.append(dist)
    return installed


def check(repo: Optional[str] = None, to_version: Optional[str] = None) -> dict:
    """Report what is installed and whether something newer is available.

    Never touches the installation and never stops a daemon: this is the half of
    the update a caller can run whenever it likes.

    ``to_version`` names a specific version instead of looking one up. It is an
    instruction, not a candidate: any version other than the installed one counts
    as "available", so pinning to an older one downgrades rather than silently
    doing nothing.
    """
    kind = installation_kind()
    current = current_version()
    if kind == KIND_SOURCE:
        return {
            "kind": kind,
            "current": current,
            "latest": None,
            "pinned": to_version,
            "update_available": False,
            "reason": (
                "PartCAD runs from a source checkout (an editable install); "
                "update it with git rather than with `pc update`"
            ),
        }
    latest = to_version or latest_version(kind, repo)
    available = latest != current if to_version else is_newer(latest, current)
    return {
        "kind": kind,
        "current": current,
        "latest": latest,
        "pinned": to_version,
        "update_available": available,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Updating
# ---------------------------------------------------------------------------


def update(
    repo: Optional[str] = None,
    to_version: Optional[str] = None,
    log: Callable[[str], None] = _noop,
    stop_timeout: float = daemon.STOP_TIMEOUT,
) -> dict:
    """Update the PartCAD installation in place. Returns the :func:`check` report.

    The report carries ``updated``: False means there was nothing newer to
    install (the common case), not that anything failed. Raises
    :class:`SelfUpdateError` when the installation cannot be updated at all.
    """
    status = check(repo, to_version)
    if status["reason"]:
        raise SelfUpdateError(status["reason"])
    if not status["update_available"]:
        log("PartCAD %s is up to date." % status["current"])
        return {**status, "updated": False}

    log("Updating PartCAD from %s to %s..." % (status["current"], status["latest"]))

    # Only now, with a newer version in hand, is it worth costing anyone their
    # warm context -- and it has to happen before a single file is written.
    _stop_daemons(log, stop_timeout)

    if status["kind"] == KIND_STANDALONE:
        location = _install_standalone(status["latest"], repo or repository(), log)
    else:
        location = _install_wheels(status["pinned"], log)

    log("PartCAD %s is installed in %s." % (status["latest"], location))
    return {**status, "updated": True, "location": location}


def _stop_daemons(log: Callable[[str], None], stop_timeout: float) -> None:
    """Stop every running daemon and wait for it, or explain why we go ahead."""
    running = daemon.live_daemon_dirs()
    if not running:
        return
    log("Stopping %d running PartCAD daemon(s) before installing..." % len(running))
    stopped = daemon.stop_all_daemons(timeout=stop_timeout)
    remaining = [wdir for wdir in running if wdir not in stopped]
    if remaining:
        # Installing side by side, never over the running files, is what makes
        # this survivable: the stale daemon keeps serving the old bundle until
        # it is restarted. Say so rather than fail the update.
        log(
            "Warning: %d PartCAD daemon(s) did not stop within %ds; they keep running the previous "
            "version until they are restarted." % (len(remaining), int(stop_timeout))
        )
    else:
        log("All PartCAD daemons stopped.")


# ---------------------------------------------------------------------------
# The standalone bundle
# ---------------------------------------------------------------------------


def platform_archive() -> tuple:
    """``(platform, extension)`` of the release archive for this machine.

    The names mirror ``install.sh`` and ``dev-tools/pyinstaller/build.sh``, which
    is what makes an installation from either updatable by the other.
    """
    os_names = {"linux": "linux", "darwin": "macos", "win32": "windows"}
    machine_names = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    os_name = os_names.get(sys.platform)
    arch = machine_names.get(platform.machine().lower())
    if not os_name or not arch:
        raise SelfUpdateError(
            "no standalone PartCAD bundle is published for %s/%s" % (sys.platform, platform.machine())
        )
    return "%s-%s" % (os_name, arch), ("zip" if os_name == "windows" else "tar.gz")


def _install_standalone(version: str, repo: str, log: Callable[[str], None]) -> str:
    """Download the release bundle and install it beside the running one."""
    platform_name, ext = platform_archive()
    archive = "partcad-%s-%s.%s" % (version, platform_name, ext)
    base_url = os.environ.get("PARTCAD_BASE_URL") or "https://github.com/%s/releases/download/%s" % (repo, version)
    url = "%s/%s" % (base_url, archive)

    root = install_dir()
    target = os.path.join(root, version)
    running = bundle_dir()
    if os.path.exists(target) and os.path.realpath(target) == os.path.realpath(running):
        # Only reachable if the running bundle sits in a directory named after a
        # version it is not -- a hand-assembled installation. Refuse: unpacking
        # into it would nest a bundle inside the one being executed.
        raise SelfUpdateError(
            "the running PartCAD bundle is installed at %s, which is where %s belongs; "
            "reinstall it with install.sh" % (running, version)
        )

    with tempfile.TemporaryDirectory(prefix="partcad-update-", dir=_staging_parent(root)) as staging:
        archive_path = os.path.join(staging, archive)
        log("Downloading %s..." % url)
        _download(url, archive_path)
        _verify_checksum(url, archive_path, log)

        log("Unpacking...")
        _extract(archive_path, staging, ext)
        unpacked = os.path.join(staging, "partcad")
        if not os.path.isdir(unpacked):
            raise SelfUpdateError("the archive does not look like a PartCAD bundle")

        os.makedirs(root, exist_ok=True)
        # Move an existing copy of the same version aside first, so a failure
        # here cannot leave a half-deleted installation behind (as install.sh
        # does). It is never the running bundle: that was refused above.
        if os.path.exists(target):
            shutil.rmtree(target + ".old", ignore_errors=True)
            os.replace(target, target + ".old")
        shutil.move(unpacked, target)
        shutil.rmtree(target + ".old", ignore_errors=True)

    _make_executable(target)
    _relink_launchers(target, root, log)
    _prune_old_versions(root, keep=(target, running), log=log)
    return target


def _staging_parent(root: str) -> Optional[str]:
    """Where to unpack before the move: the install directory when it is writable.

    ``shutil.move`` across filesystems degrades to a ~875MB copy, and the system
    temp directory is a separate (often much smaller) filesystem on exactly the
    machines this runs on. Falling back to the default keeps a read-only install
    directory failing on the move rather than on the staging.
    """
    with contextlib.suppress(OSError):
        os.makedirs(root, exist_ok=True)
        if os.access(root, os.W_OK):
            return root
    return None


def _make_executable(target: str) -> None:
    for name in BUNDLE_EXECUTABLES:
        path = os.path.join(target, name + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(path):
            with contextlib.suppress(OSError):
                os.chmod(path, 0o755)


def _relink_launchers(target: str, root: str, log: Callable[[str], None]) -> None:
    """Repoint the ``pc``/``partcad`` symlinks at the version just installed.

    Only links that already point into this installation directory are touched:
    anything else on PATH by that name -- a wheel's ``pc`` above all -- belongs
    to somebody else, the same rule ``install.sh --uninstall`` follows.
    """
    if os.name == "nt":  # pragma: no cover - install.sh does not run on Windows
        return
    relinked = []
    for bin_dir in _bin_dirs():
        for name in BUNDLE_EXECUTABLES:
            link = os.path.join(bin_dir, name)
            if not os.path.islink(link):
                continue
            if not os.path.realpath(link).startswith(os.path.realpath(root) + os.sep):
                continue
            new_target = os.path.join(target, name)
            if not os.path.isfile(new_target):
                continue
            with contextlib.suppress(OSError):
                os.remove(link)
                os.symlink(new_target, link)
                relinked.append(link)
    if relinked:
        log("Updated the launchers: %s" % ", ".join(sorted(relinked)))


def _bin_dirs() -> List[str]:
    """Directories that may hold the launcher symlinks, in install.sh's order."""
    dirs = []
    configured = os.environ.get("PARTCAD_BIN_DIR")
    if configured:
        dirs.append(configured)
    dirs.append(os.path.join(os.path.expanduser("~"), ".local", "bin"))
    dirs.extend(entry for entry in (os.environ.get("PATH") or "").split(os.pathsep) if entry)
    seen, unique = set(), []
    for entry in dirs:
        resolved = os.path.abspath(os.path.expanduser(entry))
        if resolved not in seen and os.path.isdir(resolved):
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _prune_old_versions(root: str, keep: tuple, log: Callable[[str], None]) -> None:
    """Delete superseded bundle directories. A bundle is ~875MB unpacked.

    The directory the current process runs from is always kept -- deleting it
    fails outright on Windows, and it is still being executed everywhere else.
    The next update collects it.
    """
    protect = {os.path.realpath(path) for path in keep}
    removed = []
    for entry in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(entry) or os.path.islink(entry):
            continue
        if os.path.realpath(entry) in protect:
            continue
        # Only directories that hold a bundle, so an unrelated neighbour of the
        # installation directory is never touched.
        if not os.path.isfile(os.path.join(entry, "pc" + (".exe" if os.name == "nt" else ""))):
            continue
        try:
            shutil.rmtree(entry)
            removed.append(os.path.basename(entry))
        except OSError as e:
            log("Warning: could not remove the previous bundle %s: %s" % (entry, e))
    if removed:
        log("Removed the previous bundle(s): %s" % ", ".join(removed))


def _download(url: str, dest: str) -> None:
    try:
        with _urlopen(url) as response, open(dest, "wb") as out:
            shutil.copyfileobj(response, out)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SelfUpdateError(
                "no build was published at %s. See the releases page for what is available." % url
            ) from e
        raise SelfUpdateError("download failed (HTTP %s): %s" % (e.code, url)) from e
    except (urllib.error.URLError, OSError) as e:
        raise SelfUpdateError("download failed: %s: %s" % (url, e)) from e


def _http_get(url: str, headers: Optional[dict] = None) -> bytes:
    try:
        with _urlopen(url, headers) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as e:
        raise SelfUpdateError("could not reach %s: %s" % (url, e)) from e


def _urlopen(url: str, headers: Optional[dict] = None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT)  # nosec B310 - https URLs built above


def _verify_checksum(url: str, archive_path: str, log: Callable[[str], None]) -> None:
    """Compare the archive against the published checksum.

    HTTPS already authenticates the transfer, so the checksum is here to catch a
    truncated or corrupted download: an *unavailable* checksum is a warning, a
    mismatching one is fatal -- a corrupted bundle must never be unpacked and
    executed.
    """
    try:
        expected = _http_get(url + ".sha256").decode("utf-8").strip().split()[0]
    except (SelfUpdateError, IndexError, UnicodeDecodeError) as e:
        log("Warning: no checksum published next to the archive, skipping verification (%s)" % e)
        return
    digest = sha256()
    with open(archive_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise SelfUpdateError("checksum mismatch, the download is corrupted")
    log("Checksum verified.")


def _extract(archive_path: str, dest: str, ext: str) -> None:
    if ext == "zip":
        with zipfile.ZipFile(archive_path) as zf:
            _reject_traversal(zf.namelist(), dest)
            zf.extractall(dest)  # nosec B202 - members validated above
        # ZIP carries no POSIX mode bits that Python restores, so the
        # executables come out unreadable as programs; _make_executable fixes
        # the launchers and the loader finds the rest through the bundle.
        return
    with tarfile.open(archive_path, "r:gz") as tf:
        members = tf.getmembers()
        _reject_traversal([m.name for m in members], dest)
        # `filter="data"` is the default from Python 3.14 and rejects unsafe
        # members outright; passing it explicitly keeps the newer 3.10-3.13
        # patch releases identical. The older ones have no such parameter at
        # all, and fall back to the path check made above.
        try:
            tf.extractall(dest, members=members, filter="data")  # nosec B202 - members validated above
        except TypeError:
            tf.extractall(dest, members=members)  # nosec B202 - members validated above


def _reject_traversal(names, dest: str) -> None:
    """Refuse an archive whose members would land outside ``dest``."""
    root = os.path.realpath(dest)
    for name in names:
        resolved = os.path.realpath(os.path.join(dest, name))
        if resolved != root and not resolved.startswith(root + os.sep):
            raise SelfUpdateError("the archive contains an unsafe path: %s" % name)


# ---------------------------------------------------------------------------
# The Python wheels
# ---------------------------------------------------------------------------


def _install_wheels(pin: Optional[str], log: Callable[[str], None]) -> str:
    """Upgrade the installed PartCAD distributions with pip.

    Unpinned, pip resolves each distribution's own newest release. Pinning every
    one to a single version is only correct when the user asked for that version:
    the components share a version number but not every one of them is published
    for every release, and an `==` on a version that was never uploaded fails the
    whole install.
    """
    distributions = _installed_distributions()
    if not distributions:
        raise SelfUpdateError("no PartCAD distribution is installed in %s" % sys.executable)

    requirements = ["%s==%s" % (dist, pin) if pin else dist for dist in distributions]
    argv = [sys.executable, "-m", "pip", "install", "--no-input", "--upgrade", *_pip_target_flags(), *requirements]
    log("Running: %s" % " ".join(argv))
    result = subprocess.run(argv, capture_output=True, text=True, check=False)  # nosec B603 - argv is built above
    if result.stdout:
        log(result.stdout.strip())
    if result.returncode != 0:
        raise SelfUpdateError("pip failed to install %s: %s" % (", ".join(requirements), (result.stderr or "").strip()))
    if result.stderr:
        log(result.stderr.strip())
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pip_target_flags() -> List[str]:
    """``--user``/``--break-system-packages``, when and only when they apply.

    ``--user`` is refused inside a virtual environment and pointless when the
    environment is writable; ``--break-system-packages`` only exists on the pip
    versions that enforce PEP 668, and passing it to an older one is an error.
    """
    flags = []
    if _pip_supports_break_system_packages():
        flags.append("--break-system-packages")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if not in_venv and not os.access(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.W_OK):
        flags.append("--user")
    return flags


def _pip_supports_break_system_packages() -> bool:
    try:
        import importlib

        cmdoptions = importlib.import_module("pip._internal.cli.cmdoptions")
    except ImportError:
        return False
    return hasattr(cmdoptions, "override_externally_managed")
