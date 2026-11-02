#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Find cadmpeg, or fetch it: the converter the native CAD part and assembly types read with.

cadmpeg (https://github.com/cadmpeg/cadmpeg, Apache-2.0) converts native CAD
files to STEP. It is a native program rather than a Python package, so pip
cannot install it into a sandbox. In order of preference, the copy used is:

  1. one already on the PATH, *if* it is the release this module pins -- the
     image the 'docker' sandbox was built from carries that one (see
     'tools/containers/python/Dockerfile'), and so may a machine that installed
     it;
  2. the release this module pins, downloaded once into the package's cache
     directory and verified against the checksum below before it is unpacked.

The PATH copy is held to the pin because the pin is what the parts are keyed
by: the scripts that run cadmpeg raise their CACHE_VERSION with it, and another
release on the PATH would read the same file into other geometry under the
same key.

The same file, run as a program, puts the pinned release into a directory:

    python3 cadmpeg_tool.py /usr/local/bin

which is how an image comes to carry it. 'tools/containers/_common' holds a
byte-for-byte copy of this file for that, because a Docker build cannot reach
outside its context; a test fails when the two differ.

Runs inside the sandbox, so it may use nothing but the standard library.
"""

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

NAME = "cadmpeg"
VERSION = "0.6.7"
RELEASE_URL = "https://github.com/cadmpeg/cadmpeg/releases/download/v%s/" % VERSION

# (operating system, machine) -> (asset, SHA-256), from the release's
# 'sha256.sum'. A platform missing here has no build to download.
ASSETS = {
    ("linux", "x86_64"): (
        "cadmpeg-x86_64-unknown-linux-gnu.tar.xz",
        "27028aaee874674efc2913067f6084fd9c910acb0b21febb912363c2077d9506",
    ),
    ("linux", "aarch64"): (
        "cadmpeg-aarch64-unknown-linux-gnu.tar.xz",
        "5abe4627f26afd4bbe0cb14c5dee75784c4d837407fdf6a47fa7e45560b37074",
    ),
    ("darwin", "x86_64"): (
        "cadmpeg-x86_64-apple-darwin.tar.xz",
        "a91ec4f03c9f220783cc9c8dce651198e5730fab12308e82ecd8e309e3af32aa",
    ),
    ("darwin", "aarch64"): (
        "cadmpeg-aarch64-apple-darwin.tar.xz",
        "43ba0df7d023bffa204ed2338a11780cbe0567e1b816a3eec7cf02649af857f9",
    ),
    ("windows", "x86_64"): (
        "cadmpeg-x86_64-pc-windows-msvc.zip",
        "9891426730d6a0fad3240aeb49f42b071143aec4e78912edaffb757733a14227",
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


def version_of(path):
    """The release the cadmpeg at 'path' says it is ('0.6.7'), or None if it says nothing PartCAD reads."""
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    words = (result.stdout or "").split()
    return words[1] if result.returncode == 0 and len(words) >= 2 and words[0] == NAME else None


def executable(cache_dir):
    """The path of a cadmpeg to run, downloading the pinned release if need be."""
    found = shutil.which(NAME)
    if found and version_of(found) == VERSION:
        return found
    return download(cache_dir)


def install(directory):
    """Put the pinned release, verified, at '<directory>/cadmpeg', and return that path.

    Fetched whatever the PATH holds: what is wanted here is the pin, in a place
    of the caller's choosing.
    """
    with tempfile.TemporaryDirectory(prefix="cadmpeg-") as cache:
        exe = download(cache)
        os.makedirs(directory, exist_ok=True)
        target = os.path.join(directory, os.path.basename(exe))
        shutil.copyfile(exe, target)
    os.chmod(target, 0o755)
    return target


def download(cache_dir):
    """The pinned release, downloaded into 'cache_dir' once and verified, and the path of its program."""
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write("usage: %s <directory>\n" % sys.argv[0])
        sys.exit(2)
    print(install(sys.argv[1]))
