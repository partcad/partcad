#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What a cache key is made of: the format version, the values, and the files - by their whole content."""

import hashlib
import os
import time

import pytest

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


def _large(tmp_path, middle: bytes, head: bytes = b"h", tail: bytes = b"t", name: str = "large.step"):
    """A file over a megabyte, with one byte set at each end and in the middle."""
    path = tmp_path / name
    size = 3 << 20
    body = bytearray(size)
    body[0:1] = head
    body[size // 2 : size // 2 + 1] = middle
    body[-1:] = tail
    path.write_bytes(bytes(body))
    return str(path)


def test_a_large_file_is_keyed_on_all_of_its_content(tmp_path):
    base = _files_key(_large(tmp_path, b"m"))
    assert _files_key(_large(tmp_path, b"m", head=b"H")) != base
    assert _files_key(_large(tmp_path, b"m", tail=b"T")) != base


def test_an_edit_in_the_middle_of_a_large_file_that_keeps_its_size_is_seen(tmp_path):
    """The regression: a file used to be keyed on its size and its first and last half megabyte.

    An edit in between that kept the size was not seen at all, and the part
    went on being served as it was before the edit, until '--cache-bypass'.
    """
    assert _files_key(_large(tmp_path, b"m")) != _files_key(_large(tmp_path, b"M"))


def test_a_file_is_keyed_on_its_content_and_not_on_where_it_is(tmp_path):
    """Two clones of one repository are two paths, and have to find each other's entries."""
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    assert _files_key(_large(tmp_path / "one", b"m")) == _files_key(_large(tmp_path / "two", b"m", name="other.step"))


# ------------------------------------------------------------- the memo --
#
# A digest is remembered for as long as the file looks the same from outside,
# so that it is read once per change rather than once per key asked for.


@pytest.fixture
def cold(monkeypatch, tmp_path):
    """No digest remembered, in this process or on disk, and a clock to settle files by.

    The disk memo goes to a directory of the test's own; what this process
    remembers is forgotten before and after, so that no test finds another's.
    Returns a function counting the reads of a file's content from here on.
    """
    monkeypatch.setattr(cache_hash_module, "_digests_dir", lambda: str(tmp_path / "digests"))
    memo = cache_hash_module._file_digests
    memo.forget()
    reads = []
    compute = memo._compute

    def counting(f):
        reads.append(f.name)
        return compute(f)

    monkeypatch.setattr(memo, "_compute", counting)
    yield reads
    memo.forget()


def _settle(monkeypatch):
    """Make every file on disk old enough to be trusted, as a checkout from yesterday is."""
    now = cache_hash_module._now_ns()
    monkeypatch.setattr(cache_hash_module, "_now_ns", lambda: now + 2 * cache_hash_module.RACY_NS)


@pytest.fixture(params=["os.fstat", "asked of Windows"])
def change_time(request, monkeypatch):
    """Each of the two ways a file's change time is had: 'os.fstat()', or Windows itself.

    The second is what Windows before Python 3.12 goes by (see
    'cache_hash._WINDOWS_CREATION_CTIME'), and is run everywhere else with
    'os.fstat()' answering for Windows, so that what is built on it is tested
    on every platform and not only where it is real.
    """
    if request.param == "asked of Windows":
        if os.name == "nt":
            pytest.skip("Windows is asked for real here, by whichever branch this interpreter takes")
        monkeypatch.setattr(cache_hash_module, "_WINDOWS_CREATION_CTIME", True)
        monkeypatch.setattr(cache_hash_module, "_windows_change_time_ns", lambda fd: os.fstat(fd).st_ctime_ns)
    return request.param


def _identity(path):
    with open(path, "rb") as f:
        return cache_hash_module.file_identity(f)


def _after_the_clock_moves_past(path, tmp_path):
    """Wait until a write now is stamped later than everything 'path' was stamped with.

    A file system stamps a file from a clock that ticks far more coarsely than
    nanoseconds - every 15.6 ms on Windows by default, every few on Linux - and a
    rewrite inside the tick its file was last written in keeps every timestamp
    it had. That is what the racy rule ('settled') keeps from being trusted in
    use, and '_settle' declares it trusted here; so a test that changes a file
    it has settled first waits for a write to be stamped later, as one in use
    would be. It asks the file system rather than sleeping for a guess at its
    tick, so it holds on any of them, and returns at once where the tick has
    already passed.
    """
    stamped = max(_identity(path)[3:])
    probe = tmp_path / "clock-probe"
    while True:
        probe.write_bytes(b"tick")
        if max(_identity(str(probe))[3:]) > stamped:
            return
        time.sleep(0.002)


def test_a_file_that_has_not_changed_is_not_read_again(tmp_path, monkeypatch, cold, change_time):
    path = _large(tmp_path, b"m")
    _settle(monkeypatch)

    first = _files_key(path)
    assert _files_key(path) == first
    assert _files_key(path) == first

    assert cold == [path]


def test_a_file_that_changed_is_read_again(tmp_path, monkeypatch, cold, change_time):
    """However it changed: in place, the same size, and the modification time put back."""
    path = _large(tmp_path, b"m")
    _settle(monkeypatch)
    stat = os.stat(path)
    before = _files_key(path)

    _after_the_clock_moves_past(path, tmp_path)
    _large(tmp_path, b"M")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    _settle(monkeypatch)

    assert _files_key(path) != before
    assert cold == [path, path]


def test_a_files_identity_is_the_same_however_often_it_is_asked(tmp_path, monkeypatch):
    """What a lookup compares has to be taken the way what was kept was.

    The regression: the kept identity came from 'os.fstat()' and the lookup's
    from 'os.stat()', which on Windows from Python 3.12 report different times
    as 'st_ctime' - the change time and the creation time.
    """
    path = _large(tmp_path, b"m")
    first = _identity(path)

    assert first is not None
    assert _identity(path) == first
    # Reading it changes nothing a later lookup compares.
    with open(path, "rb") as f:
        f.read()
    assert _identity(path) == first


def test_a_file_with_no_change_time_to_go_by_is_never_kept(tmp_path, monkeypatch, cold):
    """Where the platform cannot say when a file last changed, nothing about it is trusted.

    Windows before Python 3.12 reports a creation time where the change time
    should be, and the change time is asked of Windows itself; when that fails,
    the file is read every time rather than risk an answer about it as it was.
    """
    monkeypatch.setattr(cache_hash_module, "_WINDOWS_CREATION_CTIME", True)
    monkeypatch.setattr(cache_hash_module, "_windows_change_time_ns", lambda fd: None)
    path = _large(tmp_path, b"m")
    _settle(monkeypatch)

    first = _files_key(path)
    assert _files_key(path) == first

    assert cold == [path, path]
    assert not (tmp_path / "digests").exists()


def test_a_file_written_a_moment_ago_is_read_every_time(tmp_path, cold):
    """Its next change could land in the same tick of the clock and leave it looking the same."""
    path = _large(tmp_path, b"m")

    _files_key(path)
    _files_key(path)

    assert cold == [path, path]


def test_a_large_files_digest_is_kept_for_the_next_process(tmp_path, monkeypatch, cold):
    path = _large(tmp_path, b"m")
    _settle(monkeypatch)
    first = _files_key(path)

    # A new process: nothing remembered in memory.
    cache_hash_module._file_digests.forget()
    assert _files_key(path) == first
    assert cold == [path]

    # The entry names the file, never what is in it - and not the path in clear.
    (entry,) = (tmp_path / "digests").iterdir()
    assert path not in entry.name


def test_a_kept_digest_of_a_file_since_changed_is_not_believed(tmp_path, monkeypatch, cold):
    path = _large(tmp_path, b"m")
    _settle(monkeypatch)
    before = _files_key(path)
    cache_hash_module._file_digests.forget()

    _after_the_clock_moves_past(path, tmp_path)
    _large(tmp_path, b"M")
    _settle(monkeypatch)

    assert _files_key(path) != before
    assert cold == [path, path]


def test_a_kept_digest_that_is_not_one_is_ignored(tmp_path, monkeypatch, cold):
    path = _large(tmp_path, b"m")
    _settle(monkeypatch)
    expected = _files_key(path)
    (entry,) = (tmp_path / "digests").iterdir()
    entry.write_text("{not json")
    cache_hash_module._file_digests.forget()

    assert _files_key(path) == expected
    assert cold == [path, path]


def test_a_small_files_digest_is_not_kept_on_disk(tmp_path, monkeypatch, cold):
    """Hashing it again costs less than the memo would to read."""
    path = tmp_path / "part.py"
    path.write_bytes(b"small")
    _settle(monkeypatch)

    _files_key(str(path))

    assert not (tmp_path / "digests").exists()


def test_a_key_and_the_string_spelling_it_are_different_keys():
    assert _dict_key({1: "value"}) != _dict_key({"1": "value"})
    assert _dict_key({True: "value"}) != _dict_key({"True": "value"})


def test_keys_of_different_types_hash_in_a_fixed_order():
    """Mixed keys cannot be compared with each other, and must not need to be."""
    assert _dict_key({1: "a", "b": 2, None: 3}) == _dict_key({None: 3, "b": 2, 1: "a"})
