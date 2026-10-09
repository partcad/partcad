#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an analysis, a route or a simulation produced, kept so one question is answered once.

A solver or a simulator is the most expensive thing PartCAD runs - minutes
where a part takes seconds - and a route implementation is not far behind;
what each produces depends on nothing but what it was asked. So the answer is
cached the way a shape is: under a key that describes the question, in the
same tiers ('Cache', 'ctx.cache_artifacts'), with the same switches
('cacheFiles', 'cacheRemote', 'cacheS3', '--cache-bypass'). A second
`pc cae fea` of an unchanged part, the IDE's FEA tab opened again, a `pc cam`
of an unchanged part, a `pc simulate` of an unchanged assembly: each is a read.

**The key is the question, and the question is the subject plus the run.**
'question_hash()' starts from the subject's own cache key
('Shape.get_cache_key_async()'), which already covers its configuration, the
files it is built from, the keys of what it is built out of and the sandbox it
was built in; and adds what the run adds - the boundary conditions, a route's
job and machine, the implementation's resolved options, the sandbox it runs in,
and the *content* of its script and of the PartCAD wrapper that runs it. A
subject with no key ('cache: false', or made of something that says so) has no
question to key on, and its runs are never cached.

**What is stored is the result and the files it wrote, as one entry.** One,
because a hit has to be a hit: a result whose model went missing is worse than
running again. The files go in by *role* rather than by path, since a path is
where this run put them and the next one may ask for them somewhere else; and
a run that writes a directory of artifacts (a simulation: the scene, its
meshes, a trajectory, a video) has the whole directory taken, with every
mention of that directory in the result replaced by a placeholder, so that a
hit read on another machine - through a shared tier - points at where the files
are there.

**Only an answer is stored.** A run that failed raised before anything here was
asked, so the cache never holds "no solver on this machine"; installing one
changes no key, and a remembered failure would outlive its reason. That is the
same rule `pc test` has for its CAE verdict ('Test.NOT_CACHEABLE').

A tier's size window applies to an entry from above and never from below (see
'cache_backend.MAX_ONLY_KEYS'): no answer from a solver is too small to keep,
but one can be too big for memcached. An entry no tier would take is not even
packed.
"""

import io
import json
import os
import tarfile
from typing import Optional

from . import logging as pc_logging
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


def question_hash(name: str, subject_key: Optional[str], question: dict, files=()) -> Optional[CacheHash]:
    """The key one run's answer is stored under, or None when it has none.

    'subject_key' is the cache key of the shape the run is about, 'question'
    everything the run adds to it, and 'files' the scripts that do the work -
    hashed by content, so a solver script that changed is a question asked
    again. None when the subject has no key, which is what makes `cache: false`
    on an object mean what it says for everything derived from it.
    """
    if not subject_key:
        return None
    hash = CacheHash(name, cache=True)
    hash.add_string("artifact-v%d" % VERSION)
    hash.add_string(subject_key)
    hash.add_dict(question)
    for filename in files:
        hash.add_filename(filename)
    return hash


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
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        encoded = json.dumps(result).encode("utf-8")
        info = tarfile.TarInfo(_RESULT_MEMBER)
        info.size = len(encoded)
        tar.addfile(info, io.BytesIO(encoded))
        for role, path in sorted(files.items()):
            tar.add(path, arcname=_FILES_PREFIX + role, recursive=False)
        if directory:
            for relative in _directory_files(directory):
                tar.add(os.path.join(directory, relative), arcname=_DIRECTORY_PREFIX + relative, recursive=False)
    return buffer.getvalue()


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


def _unpack(data: bytes, files: dict, directory: Optional[str]) -> Optional[dict]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = {member.name: member for member in tar.getmembers() if member.isfile()}
        if _RESULT_MEMBER not in members:
            return None
        # Everything the caller needs has to be there before anything is
        # written: an entry missing the model is a miss, not half a hit.
        for role in files:
            if _FILES_PREFIX + role not in members:
                return None
        placed = []
        if directory:
            for name in members:
                if not name.startswith(_DIRECTORY_PREFIX):
                    continue
                relative = _safe_relative(name[len(_DIRECTORY_PREFIX) :])
                if relative is None:
                    return None
                placed.append((name, os.path.join(directory, relative)))

        result = json.loads(tar.extractfile(members[_RESULT_MEMBER]).read().decode("utf-8"))
        targets = [(_FILES_PREFIX + role, path) for role, path in files.items()] + placed
        for name, path in targets:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "wb") as f:
                f.write(tar.extractfile(members[name]).read())

    if directory:
        result = _relocate(result, DIRECTORY_PLACEHOLDER, directory)
    return result


async def restore_async(cache, hash: Optional[CacheHash], files: dict = None, directory: str = None):
    """The stored answer to 'hash', with its files put back, or None on a miss.

    'files' maps each role the caller needs to the path it is to be written to,
    and 'directory' is where a run's directory of artifacts goes. Whatever goes
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
