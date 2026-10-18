#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Find SolidCraft's command line tool, or fetch it.

SolidCraft (https://github.com/bherbruck/solidcraft, MIT or Apache-2.0) is a
native program rather than a Python package, so pip cannot install it into a
sandbox. In order of preference, the 'solidcraft-cli' used is:

  1. one already on the PATH -- a machine that installed SolidCraft, or this
     package's image ('Dockerfile'), which PartCAD runs the scripts in when its
     'docker' sandbox is in use and the image can be pulled;
  2. the release this module pins, downloaded once into the package's cache
     directory and verified against the checksum below before it is unpacked.

Runs inside the sandbox, so it uses nothing but the standard library.
"""

import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

CLI = "solidcraft-cli"
VERSION = "0.16.1"
RELEASE_URL = "https://github.com/bherbruck/solidcraft/releases/download/v%s/" % VERSION

# (operating system, machine) -> (asset, SHA-256), from the release's
# 'SHA256SUMS.txt'. Each holds the command line tool beside the application.
ASSETS = {
    ("linux", "x86_64"): (
        "solidcraft-%s-linux-x86_64.tar.gz" % VERSION,
        "b6dd545496a792897b87ba5679292db987853088d7cf13ccee64d94f0707f42b",
    ),
    ("linux", "aarch64"): (
        "solidcraft-%s-linux-aarch64.tar.gz" % VERSION,
        "639fea1b84b2b6e95b78203a044090450a539b3b341201eb2720d59329a71934",
    ),
    ("freebsd", "x86_64"): (
        "solidcraft-%s-freebsd-x86_64.tar.gz" % VERSION,
        "4a4aef999de830e7a89e531384d98704626f7cdaaf40bedd210fe561926a7b35",
    ),
    ("darwin", "x86_64"): (
        "solidcraft-cli-%s-macos-universal.zip" % VERSION,
        "3d3deffe7ac17d5e5f7ed467bbe117f5ff7ba1f8bebffff38f99f8ed6c311698",
    ),
    ("darwin", "aarch64"): (
        "solidcraft-cli-%s-macos-universal.zip" % VERSION,
        "3d3deffe7ac17d5e5f7ed467bbe117f5ff7ba1f8bebffff38f99f8ed6c311698",
    ),
    ("windows", "x86_64"): (
        "solidcraft-%s-windows-x64-portable.zip" % VERSION,
        "610a19eecafeae90e6f89645f62281430e9222c6e700e112e76c90b51d69986e",
    ),
    ("windows", "aarch64"): (
        "solidcraft-%s-windows-arm64-portable.zip" % VERSION,
        "abebfb8421b9b6b954ceaf55e63aa08902c0d74c29584156d6378a8d35ea0296",
    ),
}

MACHINES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


def host():
    """This machine as ASSETS spells it: ('linux', 'x86_64') and so on."""
    return platform.system().lower(), MACHINES.get(platform.machine().lower(), platform.machine().lower())


def default_cache_dir():
    """This package's own directory, for a PartCAD that hands scripts no 'cache_dir'."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def executable(cache_dir=None):
    """The path of a 'solidcraft-cli' to run, downloading the pinned release if need be."""
    found = shutil.which(CLI)
    if found:
        return found

    system, machine = host()
    if (system, machine) not in ASSETS:
        raise RuntimeError(
            "SolidCraft publishes no build for %s/%s; install it and put %s on the PATH" % (system, machine, CLI)
        )
    asset, sha256 = ASSETS[(system, machine)]
    exe_name = CLI + (".exe" if system == "windows" else "")
    target = os.path.join(cache_dir or default_cache_dir(), "solidcraft", VERSION, "%s-%s" % (system, machine))
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
        with urllib.request.urlopen(RELEASE_URL + asset, timeout=600) as response, open(archive, "wb") as f:
            shutil.copyfileobj(response, f)
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
