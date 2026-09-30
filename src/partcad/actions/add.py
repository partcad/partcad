#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Adding an object whose file comes from a URL.

``pc add`` normally points a package at a file the package already has. Given a
URL instead, there is nothing on disk to point at, and the declaration has to
say three things rather than one: where to fetch the file, where to put it, and
**which bytes to expect**.

The last of those is what this module exists for. A URL serves whatever it
serves at the moment it is fetched, so a declaration that names one without a
``fileHash`` is not reproducible, and PartCAD will refuse to call the object
manufacturable (see ``file_factory.unreproducible_reason``). Asking the author
to go and compute a digest by hand would be asking them to do what the machine
is already doing: adding the object fetches the file once, so the hash is right
there. It is written into the declaration, and the author is left with an object
that is pinned from the moment it exists.

The fetched copy is *not* kept. The package deliberately does not carry the file
- that is what ``fileFrom`` means - and leaving one behind would put a file in
the author's package directory that they did not ask for. ``pc install`` fetches
it when it is first needed.
"""

import os
import tempfile

from .. import logging as pc_logging
from ..file_factory import file_digest_async
from ..file_factory_url import FileFactoryUrl

# Telling a URL from a path, and naming the file one would be saved as, live in
# 'partcad_utils': the thin CLI commands have to make the same judgement before
# handing an argument to the daemon, and they must not import 'partcad' to do it
# (see "Command boundary" in src/partcad_cli/AGENTS.md). Re-exported here so that
# everything about adding from a URL is still reachable from one module.
from ..utils import filename_from_url, looks_like_url, redacted_url  # noqa: F401

# The algorithm the generated 'fileHash' uses. One choice, not a setting: a
# package author reading a generated declaration should not have to wonder why
# this one says sha1.
HASH_ALGORITHM = "sha256"


def object_name_from_filename(filename: str, extension) -> str:
    """The object name a file of this name declares.

    'extension' is what the object's kind is written to, and only that one is
    stripped: 'bolt.step' declares 'bolt', while 'bolt.v2.step' declares
    'bolt.v2' rather than 'bolt'. 'None' strips whatever extension there is,
    which is what software does - PartCAD cannot predict a firmware image's.
    """
    if extension is None:
        return os.path.splitext(filename)[0] or filename
    suffix = ".%s" % extension
    if extension and filename.lower().endswith(suffix.lower()):
        return filename[: -len(suffix)]
    return filename


async def fetched_file_config_async(ctx, project, url: str, filename: str) -> dict:
    """Fetch 'url' once and describe it as a declaration would.

    Returns the ``path``/``fileFrom``/``fileUrl``/``fileHash`` an object needs to
    fetch that file again and know it got the right one. Raises if the fetch
    fails: without the bytes there is no hash, and a declaration written without
    one is exactly the unpinned declaration this exists to avoid.
    """
    factory = FileFactoryUrl(ctx, project, project, {"name": filename, "fileUrl": url})

    with tempfile.TemporaryDirectory() as directory:
        # Into a temporary directory, not into the package: what is wanted here
        # is the digest, and the package is not meant to carry the file.
        downloaded = os.path.join(directory, "download")
        await factory.download(downloaded)
        digest = await file_digest_async(downloaded, HASH_ALGORITHM)

    # Logged without its userinfo or its query string. A URL a package is given
    # can be a pre-signed one, and its signature is a credential; the
    # declaration below keeps the URL whole because fetching it again needs the
    # whole of it, but a log line has no such need and travels much further.
    pc_logging.info("Fetched %s: %s:%s" % (redacted_url(url), HASH_ALGORITHM, digest))
    return {
        "path": filename,
        "fileFrom": "url",
        "fileUrl": url,
        "fileHash": "%s:%s" % (HASH_ALGORITHM, digest),
    }


async def add_object_from_url_async(ctx, project, section: str, url: str, kind=None, config=None) -> str:
    """Declare an object of 'section' whose file is fetched from 'url'.

    Returns the name it was added under. 'kind' is the object's ``type`` and is
    None for software, which has only one.
    """
    config = dict(config or {})
    extension = None if kind is None else project.extension_for(section, kind)
    filename = filename_from_url(url, fallback="download" if extension is None else "download.%s" % extension)
    name = object_name_from_filename(filename, extension)

    fetched = await fetched_file_config_async(ctx, project, url, filename)

    obj = {}
    if kind is not None:
        obj["type"] = kind
    obj.update(config)
    obj.update(fetched)

    with pc_logging.Process("AddUrl", project.name):
        pc_logging.info("Adding '%s' to '%s' from %s" % (name, section, redacted_url(url)))
        project.add_object_config(section, name, obj)
    return name
