#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Find cadmpeg, or fetch it: the converter the 'fcstd' partType reads with.

cadmpeg (https://github.com/cadmpeg/cadmpeg, Apache-2.0) converts native CAD
files to STEP. It is a native program rather than a Python package, so pip
cannot install it into a sandbox. In order of preference, the copy used is:

  1. one already on the PATH -- a machine that installed it, or the image the
     'docker' sandbox was built from, when that image carries it;
  2. the release this module pins, downloaded once into the package's cache
     directory and verified against the checksum below before it is unpacked.

Runs inside the sandbox, so it may use nothing but the standard library.
"""

import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

NAME = "cadmpeg"
VERSION = "0.6.1"
RELEASE_URL = "https://github.com/cadmpeg/cadmpeg/releases/download/v%s/" % VERSION

# (operating system, machine) -> (asset, SHA-256), from the release's
# 'sha256.sum'. A platform missing here has no build to download.
ASSETS = {
    ("linux", "x86_64"): (
        "cadmpeg-x86_64-unknown-linux-gnu.tar.xz",
        "435df8643728bb681765b42b77f653d80d58a2acf43ee69e63c7b5211d48565a",
    ),
    ("linux", "aarch64"): (
        "cadmpeg-aarch64-unknown-linux-gnu.tar.xz",
        "550a8fa7fb80a4d6b14f0a88dca971ac731b5131cf70814bdc69b16b39a208a9",
    ),
    ("darwin", "x86_64"): (
        "cadmpeg-x86_64-apple-darwin.tar.xz",
        "6f5c195e33bc302ffcc016f89100930c5394e2dc407b002fb2766471fa04ad16",
    ),
    ("darwin", "aarch64"): (
        "cadmpeg-aarch64-apple-darwin.tar.xz",
        "932a5067d76617707366c7a913e92e2c48484ccacd4f1ceecb065bbeb97dad4b",
    ),
    ("windows", "x86_64"): (
        "cadmpeg-x86_64-pc-windows-msvc.zip",
        "2ad2cefabe6162d699753e5d86cadf300ca5bd7554970cf1a42b286d93b66b85",
    ),
}

MACHINES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}

# How many times a download is tried, waiting twice as long after each failure.
ATTEMPTS = 4
FIRST_WAIT = 2


def _transient(error):
    """Whether trying again could give a different answer: a server error or a dropped connection."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code == 429
    return isinstance(error, (urllib.error.URLError, ConnectionError, TimeoutError))


def fetch(url, path):
    """Download 'url' to 'path', trying again while the failure is one that passes."""
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=600) as response, open(path, "wb") as f:
                shutil.copyfileobj(response, f)
            return
        except Exception as e:
            if attempt == ATTEMPTS - 1 or not _transient(e):
                raise
            time.sleep(FIRST_WAIT * 2**attempt)


def host():
    """This machine as ASSETS spells it: ('linux', 'x86_64') and so on."""
    return platform.system().lower(), MACHINES.get(platform.machine().lower(), platform.machine().lower())


def executable(cache_dir):
    """The path of a cadmpeg to run, downloading the pinned release if need be."""
    found = shutil.which(NAME)
    if found:
        return found

    system, machine = host()
    if (system, machine) not in ASSETS:
        raise RuntimeError(
            "cadmpeg publishes no build for %s/%s; install it and put it on the PATH" % (system, machine)
        )
    asset, sha256 = ASSETS[(system, machine)]
    exe_name = NAME + (".exe" if system == "windows" else "")
    target = os.path.join(cache_dir, NAME, VERSION, "%s-%s" % (system, machine))
    exe = os.path.join(target, exe_name)
    if os.path.isfile(exe):
        return exe

    os.makedirs(os.path.dirname(target), exist_ok=True)
    # Unpacked beside the target and moved into place in one rename, so that
    # two parts converted at once never see half a download: the loser of the
    # race finds the winner's copy and uses that.
    staging = tempfile.mkdtemp(prefix=".download-", dir=os.path.dirname(target))
    try:
        archive = os.path.join(staging, asset)
        fetch(RELEASE_URL + asset, archive)
        digest = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != sha256:
            raise RuntimeError("%s does not match its published checksum; refusing to run it" % asset)

        unpacked = os.path.join(staging, "unpacked")
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(unpacked)
        else:
            with tarfile.open(archive) as t:
                if hasattr(tarfile, "data_filter"):
                    t.extractall(unpacked, filter="data")
                else:
                    t.extractall(unpacked)

        payload = os.path.join(staging, "payload")
        os.makedirs(payload)
        for root, _dirs, files in os.walk(unpacked):
            if exe_name in files:
                shutil.move(os.path.join(root, exe_name), os.path.join(payload, exe_name))
                break
        else:
            raise RuntimeError("%s holds no %s" % (asset, exe_name))
        os.chmod(os.path.join(payload, exe_name), 0o755)

        try:
            os.replace(payload, target)
        except OSError:
            if not os.path.isfile(exe):
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return exe
