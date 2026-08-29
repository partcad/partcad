#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'software' a package ships beside its parts and assemblies.

A product is rarely hardware alone: the board in it runs a firmware image, the
controller boots a disk image, the host tool that talks to it is a binary. None
of that is geometry, so 'Software' is deliberately **not** a 'Shape': there is
nothing to tessellate, render, export or measure, and nothing here inherits the
machinery that exists for those. What software is, always, is a *file* -- and
the digital thread PartCAD maintains is only whole if that file is identified as
precisely as the parts around it are.

That is what this module is for. A 'Software' object knows where its file is
(the 'path' in the package, or what 'fileFrom' pulls it from), what it is for,
and -- for a file that is not kept in the package's own repository -- the hash
that says it is the right one. The bill of materials of an assembly lists it
beside the parts, with the revision of the package it came from, so that
"which firmware went into this unit" has the same kind of answer as "which
bracket went into this unit".
"""

import asyncio
import hashlib
import os
import typing

import aiofiles

from . import logging as pc_logging
from . import telemetry
from .utils import normalize_resource_path, resolve_resource_path

# The kind of a software object. 'raw' is a file PartCAD hands over as it is:
# it is neither parsed nor transformed, and what to do with it is the reader's
# business. It is the default because it is the only thing that can be said
# about an arbitrary file without knowing the device it belongs to.
#
# Every type is a file, and that is not going to change: the types that come
# after 'raw' name the *procedure* the file goes through rather than a different
# kind of object. A 'uf2', a 'hex' or a 'dfu' image is still one file; what it
# adds is a specific firmware flashing procedure (which tool, which bootloader,
# which reset dance) that PartCAD can then carry out or at least describe. So a
# new type belongs beside this one, with the same 'path'/'fileFrom' plumbing
# underneath it, and never as a second way of pointing at a file.
DEFAULT_TYPE = "raw"

# The hash algorithms a 'hash' may name, mapped to the length of their hex
# digest. The length is what identifies the algorithm when the declaration does
# not name one, which is the form people paste from a vendor's download page.
HASH_ALGORITHMS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

# How much of the file is read at a time while hashing it. A firmware image is
# small, a disk image is not, and neither should be held in memory whole.
HASH_CHUNK_SIZE = 1024 * 1024

# The 'fileFrom' sources that are the package itself rather than somewhere else.
# A package with no source tree serves its own files through its repository
# plugin - PartCAD writes 'fileFrom: plugin' onto every file-backed object of
# such a package itself (see 'ProjectExternalRepository._augment') - so a file
# behind it is package content exactly as a 'path' is, and the package's
# revision identifies it. Treating it as a foreign file would demand a hash of
# every object of every repository-backed package, for a file the package is
# already the authority on.
PACKAGE_FILE_SOURCES = frozenset({"plugin"})


def is_package_file(config) -> bool:
    """Whether the package itself is where this software's file comes from.

    Reads a declaration rather than a 'Software', because the same question is
    asked of a configuration nothing has been built from yet - that is what the
    'Software' lint check has in front of it.
    """
    file_from = config.get("fileFrom") if isinstance(config, dict) else None
    return file_from is None or file_from in PACKAGE_FILE_SOURCES


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
                "unknown hash algorithm '%s' (expected one of %s)"
                % (
                    algorithm,
                    ", ".join(sorted(HASH_ALGORITHMS)),
                ),
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


@telemetry.instrument()
class Software:
    """One software object of a package.

    'path' is the absolute path of the file on disk, whether the package keeps
    the file itself or 'fileFrom' pulls it in; it is where the file *will* be in
    the latter case, and it may not exist until the file is fetched.
    """

    name: str
    project_name: str
    desc: str
    kind: str = "software"
    config: dict[str, typing.Any]
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None
    errors: list[str]

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        self.project_name = project_name
        self.config = config
        self.name = config["name"]
        # Stripped the way 'Shape' strips its own: a folded YAML scalar ends
        # with a newline, and that newline reaches a generated README as a
        # trailing line break inside a table cell.
        desc = config.get("desc", "")
        self.desc = desc.strip() if isinstance(desc, str) else desc
        self.url = config.get("url", None)
        self.version = config.get("version", None)
        self.errors = []

        # Both filled in by the factory: the absolute path of the file, and the
        # coroutine that puts it there when 'fileFrom' has to fetch it. See
        # 'SoftwareFactory._create_software'.
        self.path = None
        self.prepare_async = None

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        pc_logging.error("%s: %s: %s" % (self.project_name, self.name, msg))

    @property
    def type(self) -> str:
        return self.config.get("type", DEFAULT_TYPE)

    @property
    def is_fetched(self) -> bool:
        """Whether the file this object stands for is on disk right now."""
        return bool(self.path) and os.path.exists(self.path)

    def declared_hash(self) -> typing.Optional[str]:
        """The hash the declaration pins the file to, or None.

        A file the package does not carry (see 'fileFrom') is whatever the
        remote serves at the moment it is fetched, so a declaration that names
        no hash pins nothing at all. That is what 'lint/software.py' checks; this
        is where the value it checks is read from, so that the check and every
        consumer read the same field the same way.
        """
        value = self.config.get("hash")
        if value is None:
            return None
        return str(value).strip() or None

    def is_local_file(self) -> bool:
        """Whether the file is content of the package it is declared in.

        True for a declaration that only points at a 'path', and for one the
        package serves itself (see 'PACKAGE_FILE_SOURCES'). False as soon as the
        file comes from somewhere else, which is when the package's revision
        stops identifying it and a hash has to.
        """
        return is_package_file(self.config)

    async def verify_async(self) -> typing.Optional[str]:
        """Why this software cannot be relied on, or None if it can.

        What "relied on" means is the question the bill of materials leaves
        hanging: it names a file, and this is what says the file is really
        there and really the one that was meant. Three things have to hold, and
        they are the same three wherever the question is asked:

          * The package is specific about *which* file. Either it carries the
            file, so the package's revision identifies it, or it pins what it
            fetches with a 'hash'. This is the rule the 'Software' lint check
            enforces on the declaration; here it is enforced on the object,
            because a part that cannot say which firmware it runs cannot be
            manufactured (see 'test/cam.py').
          * The file can actually be had - it is in the package, or fetching it
            works.
          * It matches the hash, when one is declared.

        A reason, not a boolean, so that whoever asked can say what is wrong
        rather than only that something is.
        """
        declared = self.declared_hash()

        if not self.is_local_file() and declared is None:
            return (
                "it is pulled in with 'fileFrom: %s' and declares no 'hash', so nothing says which file it is"
                % self.config.get("fileFrom")
            )

        algorithm = digest = None
        if declared is not None:
            algorithm, digest, error = parse_hash(declared)
            if error is not None:
                return "its 'hash' is unusable: %s" % error

        if not self.is_fetched:
            if self.prepare_async is None:
                return "the file is missing: %s" % self.path
            try:
                await self.prepare_async()
            except Exception as e:  # pylint: disable=broad-except
                return "the file could not be fetched: %s" % e
        if not self.is_fetched:
            return "the file is missing: %s" % self.path

        if digest is None:
            return None

        actual = await file_digest_async(self.path, algorithm)
        if actual != digest:
            return "the file does not match its 'hash': %s:%s was declared, %s:%s is on disk (%s)" % (
                algorithm,
                digest,
                algorithm,
                actual,
                self.path,
            )
        return None

    def verify(self) -> typing.Optional[str]:
        return asyncio.run(self.verify_async())

    def software_info(self) -> dict:
        """What this object is, as the '<label>: <value>' pairs 'pc info' prints.

        Named the way 'Shape.shape_info()' is, and for the same reason: the
        factory owns the 'info' attribute (it is what adds the package's URLs to
        this), so the object's own half of the answer needs a name of its own.
        """
        info = {
            "Path": self.project_name,
            "Type": self.type,
        }
        if self.desc:
            info["Desc"] = self.desc
        if self.version is not None:
            info["Version"] = str(self.version)
        if self.path is not None:
            info["File"] = self.path
        if self.url is not None:
            info["Url"] = self.url
        if self.config.get("fileFrom") is not None:
            info["FileFrom"] = self.config["fileFrom"]
        if self.config.get("fileUrl") is not None:
            info["FileUrl"] = self.config["fileUrl"]
        declared_hash = self.declared_hash()
        if declared_hash is not None:
            info["Hash"] = declared_hash
        if self.errors:
            info["Errors"] = list(self.errors)
        return info

    def info(self) -> dict:
        """The default, replaced by the factory that created this object."""
        return self.software_info()

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in self.name.lower() or keyword in str(self.config).lower()


# The key a resolved list of software references is stored under, beside the
# 'software' the package author wrote. Resolved once, by the factory that first
# sees the declaration, because that is the only place that knows which package
# authored it: an alias or an enrich hands its source's configuration on, and a
# reference in it means what it meant where it was written, not where it ended
# up being read.
RESOLVED_KEY = "software_resolved"


def declared_software_refs(project_name: str, config) -> list[str]:
    """The software an object declares, as fully qualified '<package>:<name>'.

    Accepts the one-entry short form ('software: firmware') as well as a list.
    Order is the author's, duplicates are dropped: the list says what the object
    ships with, and saying it twice does not make it two things.
    """
    if not isinstance(config, dict):
        return []
    refs = config.get("software")
    if not refs:
        return []
    if isinstance(refs, str):
        refs = [refs]
    resolved: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        normalized = normalize_resource_path(project_name, ref.strip())
        if normalized not in resolved:
            resolved.append(normalized)
    return resolved


def resolved_software_refs(project_name: str, config) -> list[str]:
    """What an object ships with, preferring what its factory already resolved.

    The fallback covers the objects no factory produced - an assembly built in
    Python with 'add()' - and costs nothing for the rest.
    """
    if isinstance(config, dict):
        resolved = config.get(RESOLVED_KEY)
        if resolved:
            return list(resolved)
    return declared_software_refs(project_name, config)


def lookup(ctx, ref: str, quiet: bool = False):
    """The (package, software) a fully qualified reference points at.

    Both are None when the reference resolves to nothing. Reported here, once,
    rather than by each caller: a bill of materials and a generated README ask
    the same question and a reference that does not resolve is the same mistake
    either way.

    'quiet' is for the callers that are not the ones to report it - deciding
    what a cached test result is keyed on, say ('CamTest.cache_key_suffix'),
    which asks the same question moments before the caller that *will* report
    it and would otherwise say it twice.
    """
    package_name, name = resolve_resource_path("", ref)
    project = ctx.get_project(package_name) if ctx is not None else None
    if project is None:
        if not quiet:
            pc_logging.error("The software '%s' is not found: no such package" % ref)
        return None, None
    software = project.get_software(name, quiet=quiet)
    if software is None:
        # 'get_software' has already said why, unless it was asked not to.
        return project, None
    return project, software
