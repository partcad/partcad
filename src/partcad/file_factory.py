#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-04-17
#
# Licensed under Apache License, Version 2.0.
#

import hashlib
import os
import typing

import aiofiles

from . import logging as pc_logging
from . import telemetry

# The hash algorithms a 'fileHash' may name, mapped to the length of their hex
# digest. The length is what identifies the algorithm when the declaration does
# not name one, which is the form people paste from a vendor's download page.
HASH_ALGORITHMS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

# How much of the file is read at a time while hashing it. A firmware image is
# small, a disk image is not, and neither should be held in memory whole.
HASH_CHUNK_SIZE = 1024 * 1024


# The 'fileFrom' sources that are the package itself rather than somewhere else.
# A package with no source tree serves its own files through its repository
# plugin - PartCAD writes 'fileFrom: plugin' onto every file-backed object of
# such a package itself (see 'ProjectExternalRepository._augment').
PACKAGE_FILE_SOURCES = frozenset({"plugin"})


class FileHashError(Exception):
    """A downloaded file is not the file that was asked for."""


def declared_hash(config) -> typing.Optional[str]:
    """The 'fileHash' a declaration pins its file to, or None.

    Named beside 'fileFrom' and 'fileUrl' because it belongs with them: it is a
    property of the *file*, and of nothing else. It has no relation to the
    hashes PartCAD computes for itself - the cache key of a shape
    ('CacheHash'), the digest a git revision is - and is never mixed into one:
    those identify something PartCAD built or fetched, while this states in
    advance which bytes were asked for.
    """
    if not isinstance(config, dict):
        return None
    value = config.get("fileHash")
    if value is None:
        return None
    return str(value).strip() or None


def is_package_file(config) -> bool:
    """Whether the package itself is where this declaration's file comes from.

    True when nothing is fetched at all ('path' alone), and for a file the
    package serves itself (see 'PACKAGE_FILE_SOURCES').

    Reads a declaration rather than any built object, because the same question
    is asked of a configuration nothing has been built from yet - that is what
    the 'Software' lint check has in front of it.
    """
    file_from = config.get("fileFrom") if isinstance(config, dict) else None
    return file_from is None or file_from in PACKAGE_FILE_SOURCES


def unreproducible_reason(config) -> typing.Optional[str]:
    """Why the file this declaration points at is not reproducible, or None.

    A file the package carries is identified by the package's revision: fetch
    the package again at that commit and the same bytes come back. A file it
    fetches from elsewhere is whatever the remote served at the time, and only
    'fileHash' says which bytes were meant. Without one there is no answer to
    "which file went into this", which is why the manufacturing test refuses
    such an object (see 'CamTest.reproducibility_failure') - you cannot make a
    thing again if you cannot say what it was made from.

    'fileHash' stays optional in the declaration all the same: a package that
    does not pin its download is not malformed, it has only said less about
    itself, and demanding one of every package that ever pulled a vendor file
    from a URL is not something a schema should do.

    A file served by a repository plugin is treated as reproducible here, and
    that is a gap rather than a conclusion: such a package has no revision of
    its own either, so strictly the same reasoning applies. A 'fileHash' given
    for one is verified like any other; it is simply not required yet, because
    nothing has been put in place for a plugin-backed package to pin what its
    plugin serves.
    """
    if is_package_file(config):
        return None
    if declared_hash(config) is not None:
        return None
    return (
        "it is fetched with 'fileFrom: %s' and declares no 'fileHash', so nothing says which bytes it is"
        % config.get("fileFrom")
    )


def parse_hash(value: str):
    """('<algorithm>', '<digest>', None), or (None, None, '<why not>').

    Accepts '<algorithm>:<digest>', which is the form the schema documents, and
    a bare digest whose length names the algorithm on its own.
    """
    value = str(value).strip()
    if ":" in value:
        algorithm, _, digest = value.partition(":")
        algorithm = algorithm.strip().lower().replace("-", "")
        digest = digest.strip().lower()
        if algorithm not in HASH_ALGORITHMS:
            return (
                None,
                None,
                "unknown hash algorithm '%s' (expected one of %s)" % (algorithm, ", ".join(sorted(HASH_ALGORITHMS))),
            )
    else:
        digest = value.lower()
        algorithm = next((name for name, length in HASH_ALGORITHMS.items() if length == len(digest)), None)
        if algorithm is None:
            return (
                None,
                None,
                "cannot tell which algorithm '%s' is a digest of; write it as '<algorithm>:<digest>'" % value,
            )

    if len(digest) != HASH_ALGORITHMS[algorithm] or any(c not in "0123456789abcdef" for c in digest):
        return None, None, "'%s' is not a %s digest" % (digest, algorithm)
    return algorithm, digest, None


async def file_digest_async(path: str, algorithm: str) -> str:
    """The hex digest of a file, read in chunks."""
    digest = hashlib.new(algorithm)
    async with aiofiles.open(path, "rb") as f:
        while True:
            chunk = await f.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


async def file_hash_failure(path: str, declared: typing.Optional[str]) -> typing.Optional[str]:
    """Why the file at 'path' is not what 'declared' says, or None.

    None when nothing was declared: a hash is optional, and a package that does
    not pin its download is not thereby wrong - it has only said less about it.
    """
    if declared is None:
        return None

    algorithm, digest, error = parse_hash(declared)
    if error is not None:
        return "the declared 'fileHash' is unusable: %s" % error

    if not os.path.exists(path):
        return "the file is missing: %s" % path

    actual = await file_digest_async(path, algorithm)
    if actual != digest:
        return "%s:%s was declared, %s:%s is what the file is (%s)" % (algorithm, digest, algorithm, actual, path)
    return None


@telemetry.instrument()
class FileFactory:
    """Where a file-backed object's file comes from when the package has none.

    Every source of a file goes through 'download()', which fetches it and then
    checks it against the 'fileHash' the declaration pinned it to, if it pinned
    one.
    That check belongs here rather than in any one kind of object: a part, a
    sketch, an assembly and a piece of software all declare their file the same
    way, and what "the right file arrived" means cannot sensibly differ between
    them.

    Subclasses implement '_download()' and nothing else. The verification is not
    theirs to remember, and a source that forgot it would silently be the one
    nobody could rely on.
    """

    path: typing.Optional[str] = None

    def __init__(self, ctx, source_project, target_project, config):
        self.config = config
        self.ctx = ctx
        self.project = source_project
        self.declared_hash = declared_hash(config)

    async def download(self, path):
        """Fetch the file, and refuse it if it is not the file that was pinned."""
        await self._download(path)

        failure = await file_hash_failure(path, self.declared_hash)
        if failure is None:
            return

        # Removed rather than left behind: the callers skip the download when
        # the file is already there, so keeping the wrong bytes would make every
        # later run reuse them and report the same failure without ever
        # refetching.
        try:
            os.remove(path)
        except OSError as e:
            pc_logging.debug("Failed to remove the file that did not match its hash: %s" % e)

        raise FileHashError("The downloaded file does not match the declared 'fileHash': %s" % failure)

    async def _download(self, path):
        raise NotImplementedError("FileFactory._download is implemented in child classes")
