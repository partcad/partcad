#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The files a part was read from that nothing declared: learnt by building it, and keyed on from then on.

A part is cached under a hash of what it is made of, and that has to be known
before it is built - which is easy for the file a part names and the files its
package lists under 'dependencies:', and impossible for the ones only reading the
part finds: the layers an OpenUSD stage composes, the textures its materials
name. Opening the stage before every cache lookup to find them would cost what
the cache exists to save.

So the part type that reads such a file reports, as it builds the part, every
other file it read (a 'partType' that says 'reportsDependencies', see
'PartFactoryWrapper'), and that list is kept in the shape cache beside the part,
under the key the part has *without* it - its declared key, which is known before
anything is built. Every lookup after that reads the list back and keys the part
on those files too, so editing one of them builds the part again, and that build
reports the list afresh. It is the manifest a compiler cache keeps of the headers
a source file included.

The first build of a part has no list yet, so it is keyed on its declared key and
nothing else; the list it reports keys it from the next lookup on. Whatever was
built from it in the same run - an assembly that placed it - was keyed on the key
it had then, and is built once more the next time, when the part is a hit.

A file is listed relative to the directory of the file the part is read from
where it is under it, which keeps the list the same wherever the package is and
whichever machine reads it from a shared tier, and absolute otherwise. A listed
file that is not there is hashed as missing (see 'CacheHash.add_filename'), so
one that appears later builds the part again too - which is why a part type
reports the files it looked for and did not find, as well as the ones it read.
A script that cannot tell what it read says so ('None'), and that build is not
cached: it is built again until it can.
"""

import json
import os

from .cache_hash import CacheHash

# The cache entry the list is kept under, beside the part's own under its
# declared key. Not one of the geometry keys a tier's size window applies to.
KEY = "deps"

# What the list is told apart by in the hash, so that a part keyed on no files
# and one keyed on files whose names happen to hash alike cannot collide.
_TAG = "discovered dependencies"

# The most files one list may name: past it, a list is a part type gone wrong
# rather than a stage, and is not kept.
MAX_FILES = 100_000


def normalized(reported, base_dir, own=None) -> list[str]:
    """The files of 'reported' as a list keeps them: relative to 'base_dir' where under it, sorted, each once.

    'reported' is what the part type said it read, absolute or relative to
    'base_dir'; anything that is not a path is left out, and so is 'own', the
    file the part is read from, which its key covers already.
    """
    if not isinstance(reported, (list, tuple)):
        return []
    base_dir = os.path.abspath(base_dir)
    own = os.path.normcase(os.path.abspath(own)) if own else None
    kept = set()
    for entry in reported[:MAX_FILES]:
        if not isinstance(entry, str) or not entry.strip():
            continue
        path = os.path.normpath(entry if os.path.isabs(entry) else os.path.join(base_dir, entry))
        if own is not None and os.path.normcase(path) == own:
            continue
        relative = os.path.relpath(path, base_dir) if _under(path, base_dir) else path
        kept.add(relative.replace(os.sep, "/") if not os.path.isabs(relative) else relative)
    return sorted(kept)


def resolved(listed, base_dir) -> list[str]:
    """The files of a kept list, as paths on this machine: a relative one against 'base_dir'."""
    return [
        os.path.normpath(entry if os.path.isabs(entry) else os.path.join(base_dir, *entry.split("/")))
        for entry in listed
    ]


def keyed_on(base: CacheHash, listed: list[str], base_dir: str) -> CacheHash:
    """'base' - a declared key, as 'CacheHash.snapshot' gives it - continued with the files of a kept list.

    Each file by the name the list gives it, which is relative to the part's
    file where it can be and so the same wherever the package is, and by its
    content - never by where it is on this machine, so that a shared tier is
    shared. 'base' itself when there are none: a part that read nothing else is
    keyed exactly as it was before it reported anything.
    """
    if not listed or base.hasher is None or base.get() is None:
        return base
    key = CacheHash(base.name, hasher=base.hasher, cache=True)
    key.add_string(_TAG)
    for entry, path in zip(listed, resolved(listed, base_dir)):
        key.add_string(entry)
        key.add_filename(path)
    return key


def serialize(listed: list[str]) -> bytes:
    return json.dumps({"files": list(listed)}).encode("utf-8")


def parse(data) -> list[str] | None:
    """A kept list read back, or None for none - nothing kept, or something that is not one."""
    if not data:
        return None
    try:
        files = json.loads(bytes(data).decode("utf-8")).get("files")
    except (ValueError, AttributeError, UnicodeDecodeError):
        return None
    if not isinstance(files, list) or not all(isinstance(entry, str) for entry in files):
        return None
    return files[:MAX_FILES]


def _under(path: str, directory: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(directory)]) == os.path.normcase(directory)
    except ValueError:  # another drive
        return False
