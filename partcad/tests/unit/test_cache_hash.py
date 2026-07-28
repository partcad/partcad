#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The cache format version takes part in every hash, and only that."""

import hashlib

from partcad.cache_hash import VERSION, CacheHash


def test_version_is_hashed_before_the_data():
    """A bump of VERSION has to move every entry to a new key."""
    hash = CacheHash("test", cache=True)
    hash.add_string("something")

    expected = hashlib.md5()
    expected.update(("partcad-cache-v%d" % VERSION).encode())
    expected.update(b"something")

    assert hash.get() == expected.hexdigest()
    # ...and that is not what the same input hashed to before the version.
    assert hash.get() != hashlib.md5(b"something").hexdigest()


def test_the_version_alone_does_not_make_a_hash():
    """No data means no cache entry, exactly as before the version existed."""
    assert CacheHash("test", cache=True).get() is None


def test_no_hash_when_caching_is_disabled():
    hash = CacheHash("test", cache=False)
    hash.add_string("something")

    assert hash.get() is None


def test_a_continued_hash_does_not_repeat_the_version():
    """'hasher' continues a hash that already carries the version."""
    base = CacheHash("base", cache=True)
    base.add_string("prefix")

    continued = CacheHash("continued", hasher=base.hasher, cache=True)
    continued.add_string("suffix")

    expected = hashlib.md5()
    expected.update(("partcad-cache-v%d" % VERSION).encode())
    expected.update(b"prefix")
    expected.update(b"suffix")

    assert continued.get() == expected.hexdigest()
