#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a sandbox produced from a shape, kept so one question is answered once.

A solver or a simulator is the most expensive thing PartCAD runs - minutes
where a part takes seconds - and a route implementation is not far behind;
what each produces depends on nothing but what it was asked. So the answer is
cached the way a shape is: under a key that describes the question, in the
same tiers ('Cache', 'ctx.cache_artifacts'), with the same switches
('cacheFiles', 'cacheRemote', 'cacheS3', '--cache-bypass'). A second
`pc cae fea` of an unchanged part, the IDE's FEA tab opened again, a `pc cam`
of an unchanged part, a `pc sim` of an unchanged assembly: each is a read.

So is everything else a sandbox makes out of a shape that is already built: a
file `pc export` or `pc render` writes (see 'Shape._render_one_async'), the
tessellation the IDE draws a shape with ('shape_gltf'), the PDF an instruction
book is printed as ('document_pdf') and a length a connection is measured by
('measure'). None of them is minutes, but each is an interpreter started and
a CAD kernel imported, which is seconds, and `pc render -r` over a tree of
packages asks for hundreds of them.

**The key is the question, and the question is the subject plus the run.**
'question_hash()' starts from the subject's own cache key
('Shape.get_cache_key_async()'), which already covers its configuration, the
files it is built from, the keys of what it is built out of and the sandbox it
was built in; and adds what the run adds - the boundary conditions, a route's
job and machine, the implementation's resolved options, the sandbox it runs in,
the *content* of its script and of the PartCAD wrapper that runs it, and every
Python module either can import from where it lives -- the implementing
package's sources (with the commit it is at, when it was fetched), and PartCAD's
own wrappers (see 'partcad.source_key') -- and the version the script and the
wrapper report, the 'CACHE_VERSION' each states (see 'code_version'). A
subject with no key ('cache: false', or made of something that says so) has no
question to key on, and its runs are never cached.

**PartCAD's own wrappers are keyed on what they are handed** ('wrapper_hash').
A tessellation, a PDF or a measurement is not a run of somebody's
implementation over an object: it is one of PartCAD's wrappers over bytes the
core already holds - a tree with the sketches of its ports attached, a book
whose pictures were drawn a moment ago in a temporary directory - and those
bytes are the question, exactly. So the subject is their digest
('content_key'), and the rest is the wrapper, the sandbox it runs in and the
code of every wrapper there is. `cache: false` still means what it says: the
caller passes whether the object it is asking about may be cached.

**A wrapper handed many subjects at once can store an answer per subject**
('wrapper_entries_hash', 'store_entries_async'). The IDE's tessellation is
handed the distinct shapes of a tree and answers with the glTF of each, and the
tree is mostly the same shapes the last time it was shown: one part edited is one
part to tessellate again, not the whole tree. So the run is keyed as above minus
the subject, and each answer is stored under that key with its subject's name -
a digest of exactly the bytes it is about - in its own entry, read back many to a
call. An entry holds the caller's bytes as they are, neither packed nor
compressed here: what they are is the caller's to say, and the one caller's are
compressed already.

**What is stored is the result and the files it wrote, as one entry.** One,
because a hit has to be a hit: a result whose model went missing is worse than
running again. The files go in by *role* rather than by path, since a path is
where this run put them and the next one may ask for them somewhere else; and
a run that writes a directory of artifacts (a simulation: the scene, its
meshes, a trajectory, a video) has the whole directory taken, with every
mention of that directory in the result replaced by a placeholder, so that a
hit read on another machine - through a shared tier - points at where the files
are there.

**An exported file is asked for by name, and comes back under the next one.**
An exporter writes into a directory it shares with every other object's output,
so it says what it wrote ('output.FILES_KEY') - and the names it chose share a
prefix with the path it was asked for: 'logo.urdf' writes 'logo_meshes/bolt.stl',
'cube.gltf' writes 'cube.bin'. What is remembered is each file's *suffix* beyond
that prefix ('files_layout'), so the next caller's path, ending in the same
suffix (in any case), gives the prefix every file is put back under
('placed_files'): 'xyz.urdf' gets 'xyz_meshes/bolt.stl'. A path that ends in
something else - 'xyz.JPEG' for an answer cached as 'abc.jpg' with
'abc.colors.txt' beside it - leaves nothing to derive the other names from, and
so does a renamed set of files that name each other: the '.gltf' says 'cube.bin'
inside it, and would point at nothing beside an 'xyz.bin'. Either is found, and
dismissed - the run happens, as it would have without a cache.

**Only an answer is stored.** A run that failed raised before anything here was
asked, so the cache never holds "no solver on this machine"; installing one
changes no key, and a remembered failure would outlive its reason. That is the
same rule `pc test` has for its CAE verdict ('Test.NOT_CACHEABLE').

A tier's size window applies to an entry from above and never from below (see
'cache_backend.MAX_ONLY_KEYS'): no answer from a solver is too small to keep,
but one can be too big for memcached. An entry no tier would take is not even
packed.

**An entry is a tar, uncompressed, in one zstd frame**, and is read back in one
pass in the order it was written, each file streamed to disk as it comes
('_Staging'). It used to be a gzipped tar at gzip's level 9
(tarfile's default), read by listing its members first and extracting them
after; since every backward seek in a gzip stream decompresses it again from
the start, an entry was decompressed at least twice to be put back. Over ASCII
mesh data, zstd at its default level packs in a tenth of the time or less and
reads back in a third to a half, for an entry about 5% larger: a 5 MB file
went from about a second to pack to a tenth of one. An entry is told apart by
its first bytes ('_ZSTD_MAGIC', '_GZIP_MAGIC') rather than by its key, so that a
gzipped one an earlier release wrote into a shared tier is still read: nothing
in the key says which release wrote an entry. See '_MAX_EXPANSION' for what
reading one from a shared tier is allowed to cost.
"""

import gzip
import hashlib
import io
import json
import os
import secrets
import shutil
import tarfile
from typing import Iterable, Optional

try:
    # As in 'shape_envelope': the standard library from 3.14, its backport
    # below, which PartCAD depends on there.
    from compression.zstd import ZstdFile as _ZstdFile
except ImportError:  # pragma: no cover - exercised on the other interpreter
    try:
        from backports.zstd import ZstdFile as _ZstdFile
    except ImportError:
        _ZstdFile = None

from . import code_version
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, source_key, wrapper
from .cache_backend import ARTIFACT_KEY
from .cache_hash import CacheHash

# Bumped whenever what is stored under 'ARTIFACT_KEY' changes meaning: a stale
# entry is then never looked up again rather than read back under new rules.
VERSION = 1

# Stands for the directory a run wrote into, inside a stored result.
DIRECTORY_PLACEHOLDER = "@@partcad-artifact-directory@@"

_RESULT_MEMBER = "result.json"
_FILES_PREFIX = "files/"
_DIRECTORY_PREFIX = "directory/"

# The first bytes of an entry, which say how it is compressed: a zstd frame
# (what is written), or gzip (what releases before wrote).
_ZSTD_MAGIC = shape_envelope.ZSTD_MAGIC
_GZIP_MAGIC = b"\x1f\x8b"
# zstd's own default: most of what level 9 of gzip saved, at a fraction of the
# time. A higher level buys a few per cent of a tier's space for a pack that is
# several times slower, on every answer stored.
_ZSTD_LEVEL = 3

# How far an entry may expand as it is read, as a multiple of its stored size
# and never less than the floor. An entry can come from a shared tier
# ('memcache', 's3') that this machine did not write, and a few kilobytes of
# zstd can expand to hundreds of megabytes; deflate cannot expand by much more
# than a thousand to one, which is what reading a gzipped entry was always
# bounded by, so that is the bound - zstd does not widen what an entry from
# somebody else can make this process write. Nothing PartCAD stores comes near
# it: what compresses best is a tar's own padding, and the floor covers an
# entry that is mostly that.
_MAX_EXPANSION = 1032
_MAX_EXPANSION_FLOOR = 16 << 20

# How much of a member is held in memory at once as it is put back: it is
# copied from the entry to a staged file this many bytes at a time (see
# '_Staging').
_COPY_CHUNK = 1 << 20
# What a staged file's name ends in, until it is renamed into place.
_STAGING_SUFFIX = ".partcad-staging"

# What a wrapper answered, as the one line it wrote: the result of a run keyed
# by 'wrapper_hash'. Kept as the line rather than as what it decodes to, because
# what it decodes to carries bytes - a tessellation is glTF - and a result is
# stored as JSON.
_RESPONSE = "response"


class _TooLarge(Exception):
    """The packed entry outgrew every tier that could have taken it."""


class _BoundedBuffer(io.BytesIO):
    """A buffer that refuses to grow past what any tier would accept.

    Checked as the compressed bytes arrive, so a directory holding a video is
    abandoned as soon as it is known to be too big rather than after all of it
    has been compressed into memory.
    """

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data) -> int:
        if self.limit and self.tell() + len(data) > self.limit:
            raise _TooLarge()
        return super().write(data)


class _BoundedReader:
    """What an entry decompresses into, refused past 'limit' bytes (see '_MAX_EXPANSION')."""

    def __init__(self, stream, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.read_so_far = 0

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.read_so_far += len(data)
        if self.read_so_far > self.limit:
            raise ValueError("this entry expands past %d bytes" % self.limit)
        return data


def question_hash(name: str, subject_key: Optional[str], question: dict, files=()) -> Optional[CacheHash]:
    """The key one run's answer is stored under, or None when it has none.

    'subject_key' is the cache key of the shape the run is about, 'question'
    everything the run adds to it, and 'files' the scripts that do the work -
    hashed by content, so a solver script that changed is a question asked
    again, and keyed on the version each reports ('code_version'). None when
    the subject has no key, which is what makes `cache: false` on an object mean
    what it says for everything derived from it.
    """
    if not subject_key:
        return None
    hash = CacheHash(name, cache=True)
    hash.add_string("artifact-v%d" % VERSION)
    hash.add_string(subject_key)
    hash.add_dict(question)
    for filename in files:
        hash.add_filename(filename)
    versions = code_version.scripts_key(files)
    if versions is not None:
        hash.add_string("code:" + versions)
    return hash


def content_key(*parts) -> str:
    """The digest of what a wrapper is handed, as the subject of its question.

    Each part is a string or bytes, framed with its length so that two parts
    cannot run together into the same digest as two others.
    """
    hasher = hashlib.sha256()
    for part in parts:
        data = part.encode("utf-8") if isinstance(part, str) else bytes(part)
        hasher.update(b"%d\0" % len(data))
        hasher.update(data)
    return "content:" + hasher.hexdigest()


def request_key(request) -> str:
    """'content_key()' of a request a wrapper is handed, envelopes and all.

    Canonical rather than as it is sent: the same tree read from the cache and
    built a moment ago is one question, whatever order its keys are in.
    """
    return content_key(json.dumps(shape_envelope.encode(request), sort_keys=True))


def wrapper_hash(
    name: str,
    wrapper_name: str,
    subject: Optional[str],
    requirements: Iterable[str] = (),
    python_version: str = sandbox_versions.DEFAULT_PYTHON_VERSION,
    question: Optional[dict] = None,
) -> Optional[CacheHash]:
    """The key of one run of PartCAD's own wrapper 'wrapper_name', or None.

    'subject' is what the wrapper is handed, as 'content_key()' digests it, or
    None for a run that must not be cached - an object with `cache: false`.
    'requirements' is what the caller installs into the sandbox before running
    it, on top of the stack every sandbox carries, and 'python_version' the
    interpreter it asks for: the environment as declared, never as found (see
    'sandbox_versions.environment_cache_key'). 'question' is anything else the
    answer depends on that is not in the bytes the wrapper is handed.

    The wrapper's own content and the version it reports are keyed through
    'question_hash'; every other wrapper's sources too, since they import each
    other ('source_key.wrappers_key').
    """
    if not subject:
        return None
    asked = dict(question or {})
    asked.update(
        {
            "wrapper": wrapper_name,
            "environment": sandbox_versions.environment_cache_key(
                "python", python_version, list(sandbox_versions.PINNED_REQUIREMENTS) + list(requirements)
            ),
            "wrappers": source_key.wrappers_key(),
        }
    )
    return question_hash(name, subject, asked, files=[wrapper.get(wrapper_name)])


async def restore_response_async(cache, hash: Optional[CacheHash]) -> Optional[str]:
    """What a wrapper answered to 'hash' the last time it was asked, or None."""
    result = await restore_async(cache, hash)
    if result is None:
        return None
    response = result.get(_RESPONSE)
    return response if isinstance(response, str) and response else None


async def store_response_async(cache, hash: Optional[CacheHash], response: str) -> bool:
    """Remember what a wrapper answered to 'hash', as the line it wrote.

    The last non-empty line, because that is the answer: whatever a wrapper
    wrote before it is progress (see 'shape_envelope.deserialize').
    """
    lines = [line for line in (response or "").strip().splitlines() if line.strip()]
    if not lines:
        return False
    return await store_async(cache, hash, {_RESPONSE: lines[-1].strip()})


# What one answer of many is stored under, beside the key of the run it came
# from (see 'store_entries_async'). Named after ARTIFACT_KEY so that every tier
# holds it to the same size window, from above only: each one is a piece of a
# run whose cost is starting a sandbox, however few bytes the piece is.
_ENTRY_KEY = ARTIFACT_KEY + "-%s"


def wrapper_entries_hash(
    name: str,
    wrapper_name: str,
    requirements: Iterable[str] = (),
    python_version: str = sandbox_versions.DEFAULT_PYTHON_VERSION,
    question: Optional[dict] = None,
) -> CacheHash:
    """The key of a run of 'wrapper_name' whose answers are stored one per subject.

    Everything 'wrapper_hash' keys on but the subject, which is in the name of
    each entry instead ('store_entries_async'): the wrapper and every other
    wrapper's code, the version it reports, the environment, and 'question' -
    whatever else every answer of the run depends on, which for a tessellation is
    the deflection. Worked out once for any number of subjects, and not
    conditional: a caller that must not cache simply does not ask for one.
    """
    return wrapper_hash(name, wrapper_name, "entries", requirements, python_version, question)


async def restore_entries_async(cache, hash: Optional[CacheHash], names) -> dict:
    """The entries stored under 'hash' for 'names', as the bytes they were stored as.

    A name nothing was stored for - or no tier could be read for - is absent:
    every entry is its own hit or miss. One read for all of them, which a tier
    that can answer many in one round trip (memcached) does.
    """
    if cache is None or hash is None or not cache.enabled or not names:
        return {}
    try:
        found = await cache.read_data_async(hash, [_ENTRY_KEY % name for name in names])
    except Exception as e:
        pc_logging.debug("Ignoring the cached results of %s: %s" % (hash.name, e))
        return {}
    entries = {}
    for name in names:
        data = found.get(_ENTRY_KEY % name)
        if data:
            entries[name] = bytes(data)
    if entries:
        pc_logging.debug("Using %d cached result(s) of %s" % (len(entries), hash.name))
    return entries


async def store_entries_async(cache, hash: Optional[CacheHash], entries: dict) -> int:
    """Store each of 'entries' (bytes by subject name) under 'hash'; how many some tier took.

    Never raises, for the reason 'store_async' gives. An entry no tier takes -
    one too big for every tier - is simply not there next time, and the others
    are.
    """
    if cache is None or hash is None or not cache.enabled or not entries:
        return 0
    try:
        saved = await cache.write_data_async(hash, {_ENTRY_KEY % name: data for name, data in entries.items()})
    except Exception as e:
        pc_logging.debug("Failed to store the results of %s: %s" % (hash.name, e))
        return 0
    return sum(1 for stored in saved.values() if stored)


def _relocate(value, old: str, new: str):
    """'value' with every string mentioning 'old' mentioning 'new' instead."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {key: _relocate(item, old, new) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_relocate(item, old, new) for item in value]
    return value


def _directory_files(directory: str) -> list:
    """Every regular file under 'directory', relative to it, in a stable order."""
    found = []
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for filename in sorted(files):
            path = os.path.join(root, filename)
            if os.path.isfile(path) and not os.path.islink(path):
                found.append(os.path.relpath(path, directory).replace(os.sep, "/"))
    return found


def _limit(cache) -> int:
    """The largest entry any tier of 'cache' would take, or 0 for no limit."""
    limits = [backend.max_entry_size for backend in cache.backends]
    if not limits or any(not limit for limit in limits):
        return 0
    return max(limits)


def _pack(result: dict, files: dict, directory: Optional[str], limit: int) -> bytes:
    if directory:
        result = _relocate(result, directory, DIRECTORY_PLACEHOLDER)
    buffer = _BoundedBuffer(limit)
    if _ZstdFile is None:  # pragma: no cover - PartCAD depends on zstd; see shape_envelope
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            _add_members(tar, result, files, directory)
        return buffer.getvalue()
    # Compressed as it is written, so that '_BoundedBuffer' sees the bytes that
    # will be stored as they are made.
    with _ZstdFile(buffer, mode="w", level=_ZSTD_LEVEL) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as tar:
            _add_members(tar, result, files, directory)
    return buffer.getvalue()


def _add_members(tar, result: dict, files: dict, directory: Optional[str]) -> None:
    """The members of an entry: the result, the files by role, then the directory's."""
    encoded = json.dumps(result).encode("utf-8")
    info = tarfile.TarInfo(_RESULT_MEMBER)
    info.size = len(encoded)
    tar.addfile(info, io.BytesIO(encoded))
    for role, path in sorted(files.items()):
        tar.add(path, arcname=_FILES_PREFIX + role, recursive=False)
    if directory:
        for relative in _directory_files(directory):
            tar.add(os.path.join(directory, relative), arcname=_DIRECTORY_PREFIX + relative, recursive=False)


def _open_entry(data: bytes):
    """What a stored entry decompresses into, as a stream, told apart by its first bytes."""
    if data[: len(_ZSTD_MAGIC)] == _ZSTD_MAGIC:
        if _ZstdFile is None:  # pragma: no cover - see _pack
            raise ValueError("this entry is zstd-compressed, and zstd is not available here")
        return _ZstdFile(io.BytesIO(data))
    if data[: len(_GZIP_MAGIC)] == _GZIP_MAGIC:
        return gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb")
    raise ValueError("this entry is neither zstd nor gzip")


def _safe_relative(name: str) -> Optional[str]:
    """'name' as a path inside the directory it is unpacked into, or None.

    An entry is read from tiers other people may write to, so a member that
    would land outside the directory - absolute, or climbing out with '..' - is
    refused rather than trusted.
    """
    if not name or name.startswith("/") or "\\" in name:
        return None
    normalized = os.path.normpath(name)
    if os.path.isabs(normalized) or normalized == ".." or normalized.startswith(".." + os.sep):
        return None
    return normalized


def _destination(directory: Optional[str], path: str) -> str:
    """Where 'path' is put back, checked before anything is created for it.

    Inside a run's directory ('directory'), a file has to stay inside it once
    links are followed. The member name was already checked by
    '_safe_relative', and that is a check of the name alone: a link already in
    the directory - left by something other than PartCAD, since nothing here
    writes one - would carry a write through it to wherever it points. So the
    directory the file lands in is resolved and held to the run directory, and
    a link where the file itself goes is refused rather than replaced. Raising
    is a miss (see 'restore_async').

    Anywhere else it is the caller's own output path, put back where the
    implementation would have written it: through a link, if one is there.

    Either way a directory where the file goes is refused here, while the entry
    is still being staged: found only once files are being put in place, it
    would leave the ones placed before it.
    """
    if not directory:
        destination = os.path.realpath(path)
    else:
        # Resolved before anything is created: 'realpath' follows the links in
        # the part of the path that exists, and creating the rest first would
        # create it wherever such a link points.
        root = os.path.realpath(directory)
        resolved = os.path.realpath(os.path.dirname(path))
        if os.path.commonpath([root, resolved]) != root:
            raise ValueError("%s leads outside %s" % (path, directory))
        destination = os.path.join(resolved, os.path.basename(path))
        if os.path.islink(destination):
            raise ValueError("%s is a link" % path)
    if os.path.isdir(destination):
        raise ValueError("%s is a directory" % path)
    return destination


class _Staging:
    """The files of one entry, each staged beside where it goes until all of the entry is read.

    An entry is read in one pass, and whether it is a hit is known only at the
    end of it - an entry missing the model is a miss, and nothing of it may be
    put back. Holding every member in memory until then made one entry cost as
    much memory as everything in it, decompressed; so each member is streamed
    to a file of its own instead, a hidden one in the directory it belongs in,
    and the lot are renamed into place once the entry has turned out complete.
    Beside rather than in one staging directory, so that the rename never
    crosses a file system. Whatever goes wrong first, 'discard' removes what
    was staged and every directory made for it.
    """

    def __init__(self) -> None:
        # (member name, staged path, destination), in the order they were read.
        self.staged = []
        self.created = []

    def stage(self, name: str, source, destination: str, mode: int) -> None:
        parent = os.path.dirname(destination)
        self._make_directories(parent)
        # Hidden, and named for what it is, so one left behind by a process
        # that died half way through says so. The name is not shortened from
        # the destination's, so a long one can fail here, which is a miss.
        staged = os.path.join(
            parent, ".%s.%s%s" % (os.path.basename(destination), secrets.token_hex(6), _STAGING_SUFFIX)
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(staged, flags, mode)
        self.staged.append((name, staged, destination))
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(source, f, _COPY_CHUNK)

    def _make_directories(self, parent: str) -> None:
        missing = []
        current = parent
        while current and not os.path.isdir(current):
            missing.append(current)
            above = os.path.dirname(current)
            if above == current:
                break
            current = above
        if missing:
            os.makedirs(parent, exist_ok=True)
            self.created.extend(missing)

    def place(self, first=()) -> None:
        """Rename everything staged into place: the members named in 'first' in that order, then the rest.

        Touched as it is placed, so the order is also the order of their
        modification times, as it is when a run writes them (see
        'restore_files_async'): a rename keeps the time the file was staged.
        """
        rank = {name: index for index, name in enumerate(first)}
        for _name, staged, destination in sorted(self.staged, key=lambda item: rank.get(item[0], len(rank))):
            os.replace(staged, destination)
            os.utime(destination)
        self.staged = []
        self.created = []

    def discard(self) -> None:
        for _name, staged, _destination in self.staged:
            try:
                os.unlink(staged)
            except OSError:
                pass
        # The deepest first, and only while empty: whatever else is in one now
        # is not ours.
        for directory in sorted(set(self.created), key=len, reverse=True):
            try:
                os.rmdir(directory)
            except OSError:
                pass
        self.staged = []
        self.created = []


def _unpack(data: bytes, files, directory: Optional[str]) -> Optional[dict]:
    stream = _open_entry(data)
    reader = _BoundedReader(stream, max(_MAX_EXPANSION_FLOOR, _MAX_EXPANSION * len(data)))
    staging = _Staging()
    try:
        with stream, tarfile.open(fileobj=reader, mode="r|") as tar:
            members = iter(tar)
            # The result says where everything after it goes, so it is what
            # '_pack' writes first, as every release has. An entry that starts
            # with anything else was written by something else, and is a miss.
            first = next(members, None)
            if first is None or first.name != _RESULT_MEMBER or not first.isfile():
                return None
            result = json.loads(tar.extractfile(first).read().decode("utf-8"))
            if callable(files):
                # Where the files go is decided by what was stored with them
                # (see 'restore_files_async'), and None is the caller
                # dismissing a hit it cannot put back.
                files = files(result)
                if files is None:
                    return None
            roles = {_FILES_PREFIX + role: path for role, path in files.items()}
            found = set()
            for member in members:
                if not member.isfile():
                    continue
                if member.name in roles:
                    # Named by what the entry says rather than by the caller
                    # alone when there is a directory, so held to it the way a
                    # directory's members are.
                    destination = _destination(directory, roles[member.name])
                    # The modes these were written with before there was any
                    # staging, umask applied: 0o644 in a run's directory, and
                    # what 'open()' gives anywhere else.
                    mode = 0o644 if directory else 0o666
                elif directory and member.name.startswith(_DIRECTORY_PREFIX):
                    relative = _safe_relative(member.name[len(_DIRECTORY_PREFIX) :])
                    if relative is None:
                        return None
                    destination = _destination(directory, os.path.join(directory, relative))
                    mode = 0o644
                else:
                    continue
                staging.stage(member.name, tar.extractfile(member), destination, mode)
                found.add(member.name)
            # Everything the caller needs has to be there before anything is
            # put back: an entry missing the model is a miss, not half a hit.
            if not found.issuperset(roles):
                return None
        # The caller's files in the caller's order, then the directory's.
        staging.place(first=list(roles))
    finally:
        staging.discard()

    if directory:
        result = _relocate(result, DIRECTORY_PLACEHOLDER, directory)
    return result


async def restore_async(cache, hash: Optional[CacheHash], files: dict = None, directory: str = None):
    """The stored answer to 'hash', with its files put back, or None on a miss.

    'files' maps each role the caller needs to the path it is to be written to
    - or is a function of the stored result that answers with that mapping, or
    with None to dismiss the hit - and 'directory' is where a run's directory of
    artifacts goes, and what every file put back has to stay inside. Whatever goes
    wrong reading an entry - a tier that cannot be reached, an entry written by
    something else, a file that cannot be written - is a miss: the run happens,
    and that is always a valid answer.
    """
    if cache is None or hash is None or not cache.enabled:
        return None
    try:
        found = await cache.read_data_async(hash, [ARTIFACT_KEY])
        data = found.get(ARTIFACT_KEY)
        if not data:
            return None
        result = _unpack(data, files or {}, directory)
    except Exception as e:
        pc_logging.debug("Ignoring the cached result of %s: %s" % (hash.name, e))
        return None
    if result is not None:
        pc_logging.debug("Using the cached result of %s" % hash.name)
    return result


async def store_async(cache, hash: Optional[CacheHash], result: dict, files: dict = None, directory: str = None):
    """Store 'result' and the files it came with under 'hash'.

    'files' maps a role to the file this run wrote for it, and 'directory' is a
    directory whose whole content belongs to the answer. True when some tier
    took the entry. Never raises: a cache that cannot be written is a cache
    that is not used, and the run it was asked to remember has already
    succeeded.
    """
    if cache is None or hash is None or not cache.enabled:
        return False
    try:
        data = _pack(result, files or {}, directory, _limit(cache))
    except _TooLarge:
        pc_logging.debug("The result of %s is larger than any cache tier takes" % hash.name)
        return False
    except Exception as e:
        pc_logging.debug("Failed to pack the result of %s for the cache: %s" % (hash.name, e))
        return False
    saved = await cache.write_data_async(hash, {ARTIFACT_KEY: data})
    return bool(saved.get(ARTIFACT_KEY))


# What a stored output file's entry says about the names of its files (see
# 'files_layout'), kept beside the implementation's own result and taken off it
# again on the way back.
_LAYOUT = "__files_layout__"
# The role the file a caller asked for is stored under; the others are
# '_OTHER_ROLE' and their position in the layout.
_OUTPUT_ROLE = "output"
_OTHER_ROLE = "other-%d"


def _boundary(path: str, at: int) -> bool:
    """Whether 'path' can be cut at 'at' into a prefix and a suffix of its own.

    At its end; before something that is not a letter or a digit - the '.' of an
    extension, the '_' of 'logo_meshes'; or after a separator. Never inside a
    word, which is what keeps 'abc.jpg' and 'abc.jpeg' from sharing 'abc.jp'.
    """
    return at == len(path) or not path[at].isalnum() or path[at - 1] in (os.sep, "/")


def _slashed(name: str) -> str:
    return name.replace(os.sep, "/")


def files_layout(path: str, written=()) -> Optional[dict]:
    """How the files one run wrote are named after the path it was asked for, or None.

    'written' is what the implementation said it wrote ('output.FILES_KEY'):
    paths relative to the directory of 'path', or absolute ones, with 'path'
    itself allowed among them. The answer is the longest prefix they all share
    that ends between two words ('_boundary'), and what each of them adds to it:

        logo.urdf + logo_meshes/bolt.stl  ->  ".urdf"     + ["_meshes/bolt.stl"]
        cube.gltf + cube.bin              ->  ".gltf"     + [".bin"]
        bracket.svg                       ->  ""          + []

    And whether the files name each other ('linked': one of them holds another
    one's name, which a rename would leave pointing at nothing), or name the
    directory they are in ('anchored': a move would). Searched for rather than
    declared, because the implementation knows what it wrote and not what a
    cache does with it.

    None - not cached - for a file outside the directory of 'path', or one that
    is not a regular file: neither could be put back.
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    others = set()
    for name in written:
        other = os.path.normpath(os.path.join(directory, str(name)))
        if other == path:
            continue
        if os.path.commonpath([directory, other]) != directory or not os.path.isfile(other) or os.path.islink(other):
            return None
        others.add(other)
    others = sorted(others)
    paths = [path] + others

    cut = len(os.path.commonprefix(paths))
    while not all(_boundary(candidate, cut) for candidate in paths):
        cut -= 1
    prefix = path[:cut]
    layout = {
        "suffix": _slashed(path[cut:]),
        "others": [_slashed(other[cut:]) for other in others],
        "stem": prefix[len(directory) + 1 :] if len(prefix) > len(directory) else "",
        "linked": False,
    }
    if others:
        # What a rename changes is the stem, and what it changes it in is the
        # first name each suffix makes of it - 'logo_meshes', 'cube.bin' - so
        # that is what a file naming another holds, however it goes on.
        names = {
            candidate: (layout["stem"] + _slashed(candidate[cut:]).split("/")[0]).encode("utf-8") for candidate in paths
        }
        anchor = directory.encode("utf-8")
        for candidate in paths:
            with open(candidate, "rb") as f:
                content = f.read()
            # Not the name it is under itself: two meshes in 'logo_meshes/'
            # reach each other as 'bone.stl', which no rename changes.
            if layout["stem"] and any(
                names[other] in content for other in paths if other != candidate and names[other] != names[candidate]
            ):
                layout["linked"] = True
            if anchor in content:
                layout["anchored"] = directory
    return layout


def placed_files(layout: dict, path: str) -> Optional[list]:
    """Where the files of 'layout' go when 'path' is asked for: that path first, or None.

    The suffix the path was stored under is compared in any case - 'XYZ.JPG'
    is the file 'abc.jpg' was - and what is in front of it is the prefix the
    other files are named with. None is a hit that cannot be put back: a path
    ending in another suffix, a rename of files that name each other, a move of
    files that name their directory, or a name that would land outside the
    directory of 'path' (an entry is read from tiers others may write to).
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    suffix = str(layout.get("suffix", ""))
    native = suffix.replace("/", os.sep)
    if not path.lower().endswith(native.lower()):
        return None
    prefix = path[: len(path) - len(native)]
    stem = prefix[len(directory) + 1 :] if len(prefix) > len(directory) else ""
    if layout.get("linked") and stem != layout.get("stem"):
        return None
    if layout.get("anchored") and directory != layout["anchored"]:
        return None
    placed = [path]
    for other in layout.get("others") or []:
        other = str(other)
        if not other or "\\" in other or ".." in other.split("/"):
            return None
        target = os.path.normpath(prefix + other.replace("/", os.sep))
        if os.path.commonpath([directory, target]) != directory or target == directory:
            return None
        placed.append(target)
    return placed


async def restore_files_async(cache, hash: Optional[CacheHash], path: str) -> Optional[dict]:
    """The stored answer to 'hash', with its files put back named after 'path', or None.

    The read half of 'store_files_async'. A hit that 'placed_files' cannot put
    back under 'path' is dismissed - reported, and a miss - rather than written
    under names nothing would look for.
    """
    path = os.path.abspath(path)

    def place(stored):
        layout = stored.get(_LAYOUT)
        targets = placed_files(layout, path) if isinstance(layout, dict) else None
        if targets is None:
            pc_logging.debug(
                "The cached result of %s cannot be put back as %s, so it is produced again"
                % (hash.name, os.path.basename(path))
            )
            return None
        # The others first and the file asked for last, which is the order a
        # run writes them in when they are an exporter's meshes and the file
        # naming them: a reader that takes the newest file it finds (the IDE's
        # "render to a file") takes the one it asked for.
        roles = {_OTHER_ROLE % index: target for index, target in enumerate(targets[1:])}
        roles[_OUTPUT_ROLE] = targets[0]
        return roles

    result = await restore_async(cache, hash, files=place, directory=os.path.dirname(path))
    if result is None:
        return None
    return {key: value for key, value in result.items() if key != _LAYOUT}


async def store_files_async(cache, hash: Optional[CacheHash], result: dict, path: str, written) -> bool:
    """Store 'result' and the files a run wrote for 'path' under 'hash'.

    'written' is what the implementation said it wrote besides 'path' (see
    'files_layout'); the names are remembered as suffixes of a prefix they share
    with it, so that 'restore_files_async' can name them after the next path.
    False, and nothing stored, when the files cannot be put back that way.
    """
    if cache is None or hash is None or not cache.enabled:
        return False
    path = os.path.abspath(path)
    try:
        layout = files_layout(path, written)
    except OSError as e:
        pc_logging.debug("The files of %s could not be read for the cache: %s" % (hash.name, e))
        return False
    if layout is None:
        pc_logging.debug("The files of %s are not all beside %s, so it is not cached" % (hash.name, path))
        return False
    targets = placed_files(layout, path)
    if targets is None:
        return False
    files = {_OTHER_ROLE % index: target for index, target in enumerate(targets[1:])}
    files[_OUTPUT_ROLE] = targets[0]
    return await store_async(cache, hash, dict(result, **{_LAYOUT: layout}), files=files)
