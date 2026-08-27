#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Locate, and if necessary download, the standalone ``partcad-json-rpc``.

FreeCAD's interpreter has no PartCAD in it and cannot be asked to grow one, so
the addon drives the *frozen* service instead -- the PyInstaller bundle built by
``.github/workflows/build-standalone.yml`` and installed by ``install.sh``. The
same release-archive naming and unpack layout is reused, so an existing
standalone installation (or the one the VS Code extension downloaded) is picked
up rather than downloaded again.

Which bundle to download is not a question about this machine alone: a bundle is
named after the OS version it was frozen on (``ubuntu-24.04-x86_64``, not
``linux-x86_64``), because it links against that machine's C library and runs
there and on nothing older. Which of those a release carries is a property of
the release, so the release says: ``platforms.json`` beside the archives lists
them, best first, and :func:`select_platforms` narrows the list to the builds
this host can run. A ``devel`` build has no manifest; the artifact names of the
run stand in for one.

Two sources, in this order:

* the **latest GitHub release** that actually carries a bundle for this platform;
* the **latest ``devel`` bundle artifact**, when no such release exists or when
  ``PC_CAD_DEVEL`` is set in the environment.

The artifact path talks to the GitHub Actions API, which requires a token even
for a public repository (unlike release downloads, which are anonymous). It is
read from ``PC_CAD_GITHUB_TOKEN``, ``GITHUB_TOKEN`` or ``GH_TOKEN``; without one
:func:`ensure_service` raises with that instruction rather than failing obscurely.
"""

import hashlib
import json
import os
import platform as _platform
import shutil
import sys
import tarfile
import tempfile
import zipfile
from typing import Callable, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_REPOSITORY = "partcad/partcad"
DEFAULT_BRANCH = "devel"
STANDALONE_WORKFLOW = "build-standalone.yml"
USER_AGENT = "partcad-freecad"

# What a release says it carries, published beside the archives by
# "dev-tools/release/platforms-manifest.sh".
MANIFEST_NAME = "platforms.json"

# What "build-standalone.yml" names its artifacts; the platform id follows.
ARTIFACT_PREFIX = "partcad-standalone-"

EXE = "partcad-json-rpc.exe" if os.name == "nt" else "partcad-json-rpc"

# Reported to the caller so a UI can say what is happening; the download is
# ~60MB compressed, which is not something to do behind the user's back.
Progress = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


# ---- platform --------------------------------------------------------------


def host_platform(system: Optional[str] = None, machine: Optional[str] = None):
    """Return ``(os, arch)`` for this host in the manifest's names, or None."""
    system = (system or _platform.system()).lower()
    machine = (machine or _platform.machine()).lower()
    os_name = {"linux": "linux", "darwin": "macos", "windows": "windows"}.get(system)
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if os_name is None or arch is None:
        return None
    return os_name, arch


def archive_extension(os_name: str) -> str:
    """The extension ``dev-tools/pyinstaller/build.sh`` packs the bundle with.

    xz everywhere but Windows: the bundle is native code and an unpacked
    OpenSCAD, on which xz is worth about a quarter of the download over gzip.
    ``extract`` reads the compression out of the archive, so this only names the
    file to fetch.
    """
    return "zip" if os_name == "windows" else "tar.xz"


def host_release(system: Optional[str] = None) -> Optional[str]:
    """This host's OS release as ``"<name>-<version>"``, or None when unknown.

    The same two answers ``install.sh`` can give: an Ubuntu version out of
    ``/etc/os-release``, or a macOS major version. Everything else is
    deliberately unknown -- a non-Ubuntu Linux cannot be lined up against a
    build named after an Ubuntu release, and the Windows builds are named after
    the runner image, which is not a version this machine has.
    """
    system = (system or _platform.system()).lower()
    if system == "linux":
        return _linux_release()
    if system == "darwin":
        # The major version is the compatibility boundary; the point release is
        # not, which is why the builds are "macos-15" and not "macos-15.3".
        major = (_platform.mac_ver()[0] or "").split(".")[0]
        return "macos-%s" % major if major else None
    return None


def _linux_release() -> Optional[str]:
    try:
        fields = {}
        with open("/etc/os-release", "r", encoding="utf-8") as stream:
            for line in stream:
                key, separator, value = line.strip().partition("=")
                if separator:
                    fields[key] = value.strip().strip('"').strip("'")
    except OSError:
        return None
    if fields.get("ID") != "ubuntu":
        return None
    version = fields.get("VERSION_ID")
    return "ubuntu-%s" % version if version else None


def _version_tuple(value: str) -> tuple:
    """A comparable version. Non-digits are dropped, missing fields count as 0."""
    fields = []
    for field in value.split("."):
        digits = "".join(character for character in field if character.isdigit())
        fields.append(int(digits) if digits else 0)
    return tuple(fields)


def _version_le(left: tuple, right: tuple) -> bool:
    """True when ``left <= right``, padding the shorter one with zeroes."""
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) <= right + (0,) * (width - len(right))


def _split_release(value: str):
    """``("ubuntu", (24, 4))`` for ``"ubuntu-24.04"``; None without a version."""
    name, _, version = value.partition("-")
    if not name or not version:
        return None
    return name, _version_tuple(version)


def parse_platform(platform_id: str):
    """``(os, arch, release)`` for a platform id, or None when it is not one.

    ``"ubuntu-24.04-x86_64"`` is ``("linux", "x86_64", ("ubuntu", (24, 4)))``;
    ``"linux-x86_64"`` -- an IDE archive, built once per operating system rather
    than per OS version -- has no release and is ``("linux", "x86_64", None)``.
    """
    parts = platform_id.split("-")
    if len(parts) not in (2, 3):
        return None
    os_name = {"ubuntu": "linux", "linux": "linux", "macos": "macos", "windows": "windows"}.get(parts[0])
    arch = parts[-1]
    if os_name is None or arch not in ("x86_64", "arm64"):
        return None
    release = _split_release("%s-%s" % (parts[0], parts[1])) if len(parts) == 3 else None
    return os_name, arch, release


def group_platforms(platform_ids) -> dict:
    """``{os: {arch: [id, ...]}}`` with each list newest build first.

    The shape the release manifest publishes, built here from a list of names --
    the CI artifacts of a ``devel`` run, which no manifest describes.
    """
    grouped: dict = {}
    for platform_id in platform_ids:
        parsed = parse_platform(platform_id)
        if parsed is None:
            continue
        os_name, arch, _release = parsed
        grouped.setdefault(os_name, {}).setdefault(arch, []).append(platform_id)
    for by_arch in grouped.values():
        for ids in by_arch.values():
            ids.sort(key=lambda name: (parse_platform(name)[2] or ("", ()))[1], reverse=True)
    return grouped


def select_platforms(manifest: dict, kind: str, os_name: str, arch: str, release: Optional[str] = None) -> list:
    """The builds in ``manifest`` worth trying on this host, best first.

    ``manifest[kind][os][arch]`` is what the release published, newest build
    first. A frozen bundle needs the C library of the machine that froze it or
    newer, so a build newer than this host is dropped rather than offered and
    left to fail at first start; a host whose release cannot be established gets
    the list backwards, oldest and therefore most portable build first; and a
    host older than every build is still offered the oldest one, as the only
    candidate with a chance.

    Duplicated from ``partcad_client.selfupdate`` on purpose, for the reason
    given in ``framing.py``: FreeCAD's interpreter has no PartCAD in it, which
    is the whole point of downloading the frozen bundle.
    """
    published = (((manifest.get(kind) or {}).get(os_name) or {}).get(arch)) or []
    published = [entry for entry in published if isinstance(entry, str) and entry]
    if not published:
        return []
    host = _split_release(release) if release else None
    releases = [(entry, (parse_platform(entry) or (None, None, None))[2]) for entry in published]
    if host is None or not any(found and found[0] == host[0] for _, found in releases):
        return list(reversed(published))
    usable = [entry for entry, found in releases if found and found[0] == host[0] and _version_le(found[1], host[1])]
    return usable or [published[-1]]


def release_manifest(repository: str, version: str) -> Optional[dict]:
    """The release's ``platforms.json``, or None when it does not publish one.

    Which builds a release carries is a property of the release: the bundles are
    named after the OS version they were frozen on, and that set changes as
    builders come and go, so the release says rather than a client guessing. A
    release made before the manifest existed returns None here and is treated
    like a release with no bundle for this host -- the development build is the
    fallback, as it already is for a release that predates the bundles.
    """
    try:
        body = http_get(release_archive_url(repository, version, MANIFEST_NAME), _headers(accept="*/*"))
        manifest = json.loads(body.decode("utf-8"))
    except (HTTPError, OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def archive_name(version: str, platform_name: str, ext: str) -> str:
    return "partcad-%s-%s.%s" % (version, platform_name, ext)


def artifact_name(platform_name: str) -> str:
    return "%s%s" % (ARTIFACT_PREFIX, platform_name)


# ---- locating an existing installation --------------------------------------


def _is_file(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(path)


def _which(exe: str) -> Optional[str]:
    return shutil.which(exe)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def bundle_root(cache_dir: str) -> str:
    """Where this addon unpacks a bundle it downloaded itself."""
    return os.path.join(cache_dir, "partcad-bundle")


def candidate_paths(cache_dir: str) -> list:
    """Every place a usable ``partcad-json-rpc`` may already be, in priority order."""
    home = os.path.expanduser("~")
    xdg_data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    candidates = [os.path.join(bundle_root(cache_dir), "partcad", EXE)]
    # install.sh unpacks to <install-dir>/<version>/ and links the commands into
    # ~/.local/bin; the VS Code extension unpacks to <storage>/partcad-bundle/partcad.
    # Ordered by install time, not by name: the directory names are versions, and
    # sorting those as strings puts 0.7.98 ahead of 0.7.158.
    install_dir = os.path.join(xdg_data, "partcad")
    if os.path.isdir(install_dir):
        entries = [os.path.join(install_dir, entry) for entry in os.listdir(install_dir)]
        entries.sort(key=lambda path: _mtime(path), reverse=True)
        candidates.extend(os.path.join(entry, EXE) for entry in entries)
    candidates.append(os.path.join(home, ".local", "bin", EXE))
    if sys.platform == "darwin":
        candidates.append(os.path.join(home, "Library", "Application Support", "partcad", EXE))
    return candidates


def resolve_service_path(cache_dir: str) -> Optional[str]:
    """Return the path to a usable ``partcad-json-rpc``, or None if there is none."""
    configured = os.environ.get("PC_CAD_SERVICE_PATH")
    if _is_file(configured):
        return configured
    for candidate in candidate_paths(cache_dir):
        if _is_file(candidate):
            return candidate
    return _which(EXE)


# ---- HTTP -------------------------------------------------------------------


def github_token() -> Optional[str]:
    for name in ("PC_CAD_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(name)
        if token:
            return token
    return None


def _headers(accept: str = "application/vnd.github+json", token: Optional[str] = None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if token:
        headers["Authorization"] = "Bearer %s" % token
    return headers


def http_get(url: str, headers: Optional[dict] = None, timeout: float = 60.0) -> bytes:
    request = Request(url, headers=headers or _headers())
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - https URLs only
        return response.read()


def http_get_json(url: str, token: Optional[str] = None, timeout: float = 60.0):
    return json.loads(http_get(url, _headers(token=token), timeout).decode("utf-8"))


def download_file(url: str, dest: str, headers: Optional[dict] = None, progress: Progress = _noop) -> None:
    """Stream ``url`` into ``dest``, reporting progress as a percentage."""
    request = Request(url, headers=headers or _headers(accept="*/*"))
    with urlopen(request, timeout=300.0) as response:  # nosec B310 - https URLs only
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_reported = -1
        with open(dest, "wb") as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    percent = int(done * 100 / total)
                    if percent != last_reported and percent % 5 == 0:
                        last_reported = percent
                        progress("downloading... %d%%" % percent)


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---- release and artifact discovery -----------------------------------------


def latest_release_tag(repository: str = DEFAULT_REPOSITORY) -> Optional[str]:
    """The tag of the latest GitHub release, or None when there is none."""
    try:
        return http_get_json("https://api.github.com/repos/%s/releases/latest" % repository).get("tag_name")
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def release_archive_url(repository: str, version: str, name: str) -> str:
    return "https://github.com/%s/releases/download/%s/%s" % (repository, version, name)


def url_exists(url: str) -> bool:
    """True when ``url`` can be fetched. Release assets are missing more often
    than not here: the wheels ship every release, the bundles only since the
    ``Standalone`` workflow started uploading them."""
    request = Request(url, headers=_headers(accept="*/*"), method="HEAD")
    try:
        with urlopen(request, timeout=30.0) as response:  # nosec B310 - https URLs only
            return 200 <= response.status < 300
    except HTTPError:
        return False
    except OSError:
        return False


def latest_devel_artifact(
    repository: str = DEFAULT_REPOSITORY,
    os_name: str = "linux",
    arch: str = "x86_64",
    release: Optional[str] = None,
    branch: str = DEFAULT_BRANCH,
    token: Optional[str] = None,
) -> Optional[tuple]:
    """The newest successful ``Standalone`` artifact this host can run.

    Returns ``(artifact, platform)`` -- the artifact's ``archive_download_url``
    is what the caller needs -- or None when no successful run has one. There is
    no manifest for a CI run, so the run's own artifact names are the inventory:
    which platforms a ``devel`` run built is a property of that run (a shallow
    run builds fewer than a deep one), exactly as it is of a release.

    Artifacts expire after the workflow's retention period, so a run may exist
    with nothing to download -- hence the walk over several runs rather than
    only the newest.
    """
    runs_url = (
        # No event filter: the bundles are built on a push to the branch, but a
        # workflow_dispatch run of the same workflow produces the same artifact
        # and is just as good a source.
        "https://api.github.com/repos/%s/actions/workflows/%s/runs"
        "?branch=%s&status=success&per_page=10" % (repository, STANDALONE_WORKFLOW, branch)
    )
    runs = http_get_json(runs_url, token=token).get("workflow_runs") or []
    for run in runs:
        artifacts_url = "https://api.github.com/repos/%s/actions/runs/%s/artifacts" % (repository, run["id"])
        artifacts = http_get_json(artifacts_url, token=token).get("artifacts") or []
        available = {}
        for artifact in artifacts:
            name = artifact.get("name") or ""
            if name.startswith(ARTIFACT_PREFIX) and not artifact.get("expired"):
                available[name[len(ARTIFACT_PREFIX) :]] = artifact
        built = {"bundle": group_platforms(available)}
        for platform_name in select_platforms(built, "bundle", os_name, arch, release):
            return available[platform_name], platform_name
    return None


# ---- unpacking ---------------------------------------------------------------


def _extract_zip(archive: str, dest: str) -> None:
    """Unpack a zip, restoring the Unix permission bits it recorded.

    ``ZipFile.extract`` drops them, which would leave the bundle's executables
    non-executable -- the failure only shows up when the service is launched.
    It does sanitize the member paths itself (leading separators and ``..``
    components are removed), so there is no traversal check to add here; the
    tar path needs one because ``extractall`` does not.
    """
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            path = zf.extract(info, dest)
            # A zip written on Windows records no Unix mode at all; leave those
            # entries with whatever the umask gave them.
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                os.chmod(path, mode)


def _safe_members(tf, dest: str):
    """The members of ``tf`` that may be written under ``dest``.

    The stand-in for ``filter="data"`` on interpreters that do not have it (it
    arrived in 3.12, and in the later patch releases of 3.10/3.11 -- FreeCAD
    embeds its own interpreter, so which one runs this is not ours to choose).
    Same policy: nothing may escape the destination, device and FIFO entries are
    dropped, and a link is kept only when it points back inside the archive.

    Links used to be dropped outright, which was safe and, since the bundle grew
    them, wrong: ``partcad`` and ``partcad-json-rpc`` are relative symlinks to
    ``pc`` (one ~38MB payload, three names), and ``EXE`` -- the very file this
    addon launches -- is one of them. Dropping it left an extracted bundle with
    no service to start, on old interpreters only.
    """
    root = os.path.realpath(dest)
    for member in tf:
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            continue
        target = os.path.realpath(os.path.join(root, member.name))
        if target != root and not target.startswith(root + os.sep):
            continue
        if member.issym() or member.islnk():
            link = member.linkname
            if os.path.isabs(link):
                continue
            # A symlink resolves against its own directory; a hard link name is
            # relative to the archive root.
            base = os.path.dirname(member.name) if member.issym() else ""
            resolved = os.path.normpath(os.path.join(root, base, link))
            if resolved != root and not resolved.startswith(root + os.sep):
                continue
        yield member


def _extract_tar(archive: str, dest: str) -> None:
    with tarfile.open(archive, "r:*") as tf:
        try:
            tf.extractall(dest, filter="data")  # nosec B202 - filtered by the stdlib data policy
        except TypeError:  # pragma: no cover - only on interpreters without 'filter'
            tf.extractall(dest, members=_safe_members(tf, dest))  # nosec B202 - filtered above


def extract(archive: str, dest: str) -> None:
    """Unpack a bundle archive (``.tar.xz`` or ``.zip``) into ``dest``."""
    if archive.endswith(".zip"):
        _extract_zip(archive, dest)
    else:
        _extract_tar(archive, dest)


def _verify(archive: str, expected: Optional[str]) -> None:
    """Fail on a checksum that is present and wrong; warn by silence when absent.

    The HTTPS transfer is already authenticated, so the checksum only guards
    against a corrupted download -- but a *mismatch* must be fatal, or a
    corrupted bundle would be unpacked and executed.
    """
    if not expected:
        return
    actual = sha256(archive)
    if actual != expected:
        os.remove(archive)
        raise RuntimeError("checksum mismatch, the download is corrupted")


def _checksum_from(text: str) -> Optional[str]:
    """The hash out of a ``sha256sum``-style line (``<hash>  <name>``)."""
    parts = text.strip().split()
    return parts[0] if parts else None


# ---- the download flows ------------------------------------------------------


def _install_from_archive(archive: str, root: str, progress: Progress) -> str:
    progress("extracting...")
    extract(archive, root)
    os.remove(archive)
    exe = os.path.join(root, "partcad", EXE)
    if not _is_file(exe):
        raise RuntimeError("the service executable was not found in the downloaded bundle")
    if os.name != "nt":
        os.chmod(exe, 0o755)
    return exe


def download_release(repository: str, version: str, platform_name: str, ext: str, root: str, progress: Progress) -> str:
    """Download and unpack the release bundle; return the executable's path."""
    name = archive_name(version, platform_name, ext)
    url = release_archive_url(repository, version, name)
    archive = os.path.join(root, name)

    progress("downloading %s..." % name)
    download_file(url, archive, progress=progress)

    expected = None
    try:
        expected = _checksum_from(http_get(url + ".sha256", _headers(accept="*/*")).decode("utf-8"))
    except OSError:
        pass  # no checksum published next to the archive
    _verify(archive, expected)

    return _install_from_archive(archive, root, progress)


def download_devel(
    repository: str,
    os_name: str,
    arch: str,
    release: Optional[str],
    branch: str,
    root: str,
    progress: Progress,
) -> str:
    """Download and unpack the latest ``devel`` CI bundle; return the executable's path.

    The artifact is a zip *around* the release archive (that is how
    ``actions/upload-artifact`` stores it), so this unwraps twice and verifies the
    inner archive against the ``.sha256`` shipped beside it.
    """
    token = github_token()
    if not token:
        raise RuntimeError(
            "downloading a development build needs a GitHub token: the Actions "
            "artifact API rejects anonymous requests even for a public repository. "
            "Set PC_CAD_GITHUB_TOKEN (or GITHUB_TOKEN / GH_TOKEN) to a token with "
            "public repository read access, or install a released bundle with "
            "install.sh."
        )

    progress("looking up the latest %s build..." % branch)
    found = latest_devel_artifact(repository, os_name, arch, release, branch, token)
    if found is None:
        raise RuntimeError(
            "no unexpired '%s' bundle for %s/%s was found in the last few "
            "'%s' runs of %s" % (branch, os_name, arch, branch, repository)
        )
    artifact, platform_name = found
    progress("using the %s build of %s..." % (branch, platform_name))

    wrapper = os.path.join(root, "artifact.zip")
    progress("downloading the %s bundle..." % branch)
    download_file(artifact["archive_download_url"], wrapper, _headers(accept="*/*", token=token), progress)

    inner_dir = os.path.join(root, "artifact")
    _extract_zip(wrapper, inner_dir)
    os.remove(wrapper)

    archive = next(
        (
            os.path.join(inner_dir, name)
            for name in sorted(os.listdir(inner_dir))
            if name.endswith(".tar.xz") or name.endswith(".tar.gz") or name.endswith(".zip")
        ),
        None,
    )
    if archive is None:
        raise RuntimeError("the downloaded artifact contains no bundle archive")

    expected = None
    checksum_file = archive + ".sha256"
    if os.path.isfile(checksum_file):
        with open(checksum_file, "r", encoding="utf-8") as stream:
            expected = _checksum_from(stream.read())
    _verify(archive, expected)

    moved = os.path.join(root, os.path.basename(archive))
    shutil.move(archive, moved)
    exe = _install_from_archive(moved, root, progress)
    shutil.rmtree(inner_dir, ignore_errors=True)
    return exe


def want_devel() -> bool:
    """True when ``PC_CAD_DEVEL`` asks for a development build."""
    value = os.environ.get("PC_CAD_DEVEL")
    return bool(value) and value.lower() not in ("0", "false", "no", "off")


def ensure_service(cache_dir: str, progress: Progress = _noop, repository: Optional[str] = None) -> str:
    """Return the path to ``partcad-json-rpc``, downloading a bundle if needed.

    Downloading is the last resort: an installation made by ``install.sh``, by
    the VS Code extension, or by an earlier run of this addon is used as it is.
    """
    existing = resolve_service_path(cache_dir)
    if existing:
        return existing

    repository = repository or os.environ.get("PC_CAD_REPOSITORY") or DEFAULT_REPOSITORY
    host = host_platform()
    if host is None:
        raise RuntimeError("unsupported platform %s/%s" % (_platform.system(), _platform.machine()))
    os_name, arch = host
    ext = archive_extension(os_name)
    release = host_release()

    root = bundle_root(cache_dir)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

    if not want_devel():
        progress("resolving the latest release...")
        version = latest_release_tag(repository)
        # A release with no bundle for this host is not a release we can use:
        # the standalone archives are a recent addition, the manifest that says
        # which of them a release carries is newer still, and the newest tag may
        # predate either. Fall through to the development build instead of
        # failing on a 404.
        manifest = release_manifest(repository, version) if version else None
        for platform_name in select_platforms(manifest or {}, "bundle", os_name, arch, release):
            archive = archive_name(version, platform_name, ext)
            # The manifest is written before the upload, so an archive it lists
            # can still be absent; every later candidate runs here too.
            if url_exists(release_archive_url(repository, version, archive)):
                return download_release(repository, version, platform_name, ext, root, progress)
        progress("no released bundle for %s/%s; falling back to the development build" % (os_name, arch))

    branch = os.environ.get("PC_CAD_BRANCH") or DEFAULT_BRANCH
    return download_devel(repository, os_name, arch, release, branch, root, progress)


def temporary_dir() -> str:
    """A directory for the STEP files handed to FreeCAD, cleaned up by the OS."""
    return tempfile.mkdtemp(prefix="partcad-freecad-")
