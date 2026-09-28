#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The cache format version takes part in every hash, and only that."""

import hashlib
import os

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


def test_a_file_edited_after_it_was_hashed_is_noticed(tmp_path):
    """The hash is computed once; 'inputs_changed' is how a warm holder finds out."""
    path = tmp_path / "part.step"
    path.write_bytes(b"one")
    cache_hash = CacheHash("test", cache=True)
    cache_hash.set_dependencies([str(path)])
    cache_hash.get()
    assert not cache_hash.inputs_changed()

    path.write_bytes(b"three")
    assert cache_hash.inputs_changed()


def test_a_file_that_appears_after_it_was_hashed_is_noticed(tmp_path):
    path = tmp_path / "part.step"
    cache_hash = CacheHash("test", cache=True)
    cache_hash.set_dependencies([str(path)])
    cache_hash.get()
    assert not cache_hash.inputs_changed()

    path.write_bytes(b"one")
    assert cache_hash.inputs_changed()


def test_edits_are_noticed_with_caching_disabled_too(tmp_path):
    """What is built is still kept in memory, and goes stale all the same."""
    path = tmp_path / "part.step"
    path.write_bytes(b"one")
    cache_hash = CacheHash("test", cache=False)
    cache_hash.set_dependencies([str(path)])
    assert cache_hash.get() is None

    os.utime(path, ns=(0, 0))
    assert cache_hash.inputs_changed()
