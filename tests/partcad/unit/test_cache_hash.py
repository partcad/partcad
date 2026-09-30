#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The cache format version takes part in every hash, and only that."""

import hashlib
import os

from partcad import cache_hash as cache_hash_module
from partcad.cache_hash import VERSION, CacheHash


def _string(value: str) -> bytes:
    """A string as the hash takes it in: tagged, and its length in front."""
    data = value.encode()
    return b"s" + len(data).to_bytes(8, "big") + data


def test_version_is_hashed_before_the_data():
    """A bump of VERSION has to move every entry to a new key."""
    cache_hash = CacheHash("test", cache=True)
    cache_hash.add_string("something")

    expected = hashlib.md5()
    expected.update(("partcad-cache-v%d" % VERSION).encode())
    expected.update(_string("something"))

    assert cache_hash.get() == expected.hexdigest()
    # ...and that is not what the same input hashed to before the version.
    assert cache_hash.get() != hashlib.md5(b"something").hexdigest()


def test_the_version_alone_does_not_make_a_hash():
    """No data means no cache entry, exactly as before the version existed."""
    assert CacheHash("test", cache=True).get() is None


def test_no_hash_when_caching_is_disabled():
    cache_hash = CacheHash("test", cache=False)
    cache_hash.add_string("something")

    assert cache_hash.get() is None


def test_a_continued_hash_does_not_repeat_the_version():
    """'hasher' continues a hash that already carries the version."""
    base = CacheHash("base", cache=True)
    base.add_string("prefix")

    continued = CacheHash("continued", hasher=base.hasher, cache=True)
    continued.add_string("suffix")

    expected = hashlib.md5()
    expected.update(("partcad-cache-v%d" % VERSION).encode())
    expected.update(_string("prefix"))
    expected.update(_string("suffix"))

    assert continued.get() == expected.hexdigest()


def _dict_key(data):
    cache_hash = CacheHash("test", cache=True)
    cache_hash.add_dict(data)
    return cache_hash.get()


def test_list_items_do_not_run_into_each_other():
    """The regression: two offsets, one key, one cached shape for both parts."""
    assert _dict_key({"offset": [1, 23, 0]}) != _dict_key({"offset": [12, 3, 0]})


def test_where_a_key_ends_and_its_value_begins_is_part_of_the_hash():
    assert _dict_key({"ab": "c"}) != _dict_key({"a": "bc"})
    assert _dict_key({"a": ["b", "c"]}) != _dict_key({"a": ["bc"]})
    assert _dict_key({"a": {"b": "c"}}) != _dict_key({"a": "bc"})


def test_a_number_and_the_string_spelling_it_are_different_values():
    """A script reads '1' and 1 differently, so they are different parts."""
    assert _dict_key({"p": 1}) != _dict_key({"p": "1"})
    assert _dict_key({"p": True}) != _dict_key({"p": "True"})
    assert _dict_key({"p": None}) != _dict_key({"p": "None"})


def test_a_set_hashes_the_same_whatever_order_it_iterates_in():
    assert _dict_key({"s": {"b", "a", "c"}}) == _dict_key({"s": {"c", "a", "b"}})


def _files_key(*paths):
    cache_hash = CacheHash("test", cache=True)
    cache_hash.add_string("config")
    cache_hash.set_dependencies(list(paths))
    return cache_hash.get()


def test_files_do_not_run_into_each_other(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.write_bytes(b"ab")
    second.write_bytes(b"c")
    before = _files_key(str(first), str(second))
    first.write_bytes(b"a")
    second.write_bytes(b"bc")
    assert _files_key(str(first), str(second)) != before


def test_a_missing_dependency_is_not_the_same_as_an_empty_one(tmp_path):
    """Skipped, a file that has not appeared yet keyed as if it were not declared."""
    path = tmp_path / "helper.py"
    missing = _files_key(str(path))
    path.write_bytes(b"")
    assert _files_key(str(path)) != missing
    assert _files_key() != missing


def test_a_file_is_not_keyed_on_its_modification_time(tmp_path):
    """Two clones of one repository have to find each other's entries.

    A checkout writes every file at the time it happens, so a key that covered
    the modification time would differ on every machine and in every clone, and
    a shared tier would never be hit.
    """
    path = tmp_path / "part.step"
    path.write_bytes(b"one")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    before = _files_key(str(path))
    os.utime(path, ns=(2_000_000_000, 2_000_000_000))
    assert _files_key(str(path)) == before


def test_a_small_file_is_keyed_on_all_of_its_content(tmp_path):
    path = tmp_path / "part.step"
    path.write_bytes(b"one")
    before = _files_key(str(path))
    path.write_bytes(b"two")
    assert _files_key(str(path)) != before


def _large(tmp_path, middle: bytes, head: bytes = b"h", tail: bytes = b"t"):
    """A file over the sample size, with one byte set at each end and in the middle."""
    path = tmp_path / "large.step"
    size = cache_hash_module._SAMPLE_SIZE * 3
    body = bytearray(size)
    body[0:1] = head
    body[size // 2 : size // 2 + 1] = middle
    body[-1:] = tail
    path.write_bytes(bytes(body))
    return str(path)


def test_a_large_file_is_keyed_on_its_head_and_its_tail(tmp_path):
    base = _files_key(_large(tmp_path, b"m"))
    assert _files_key(_large(tmp_path, b"m", head=b"H")) != base
    assert _files_key(_large(tmp_path, b"m", tail=b"T")) != base


def test_a_large_file_is_not_read_in_the_middle(tmp_path):
    """What the sample leaves out is covered by the size alone, not read.

    Asserted so that the saving is not quietly undone - and so that what it
    costs is written down: an edit there that keeps the size is not seen, and
    '--cache-bypass' is the way past it.
    """
    assert _files_key(_large(tmp_path, b"m")) == _files_key(_large(tmp_path, b"M"))


def test_a_key_and_the_string_spelling_it_are_different_keys():
    assert _dict_key({1: "value"}) != _dict_key({"1": "value"})
    assert _dict_key({True: "value"}) != _dict_key({"True": "value"})


def test_keys_of_different_types_hash_in_a_fixed_order():
    """Mixed keys cannot be compared with each other, and must not need to be."""
    assert _dict_key({1: "a", "b": 2, None: 3}) == _dict_key({None: 3, "b": 2, 1: "a"})
