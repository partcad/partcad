#!/usr/bin/env python3
#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the cache version a repository plugin states in its own code.

The number says when the plugin's answers stopped meaning what they used to
mean. It is read out of the script - parsed, never executed - because the answer
is needed before the plugin can be asked anything: it names both the cache the
answers are kept in and the directory the plugin's own files land in.
"""

import os

import pytest

from partcad import project_factory_external as pfe


class FakeProject:
    """Just enough of a Project to resolve a plugin reference to a file."""

    def __init__(self, name, config_dir, repositories):
        self.name = name
        self.config_dir = str(config_dir)
        self.config_obj = {"repositories": repositories}


class FakeContext:
    """Weak-referenceable, because the memo is keyed by context."""

    def __init__(self, projects=None):
        self._projects = projects or {}

    def get_project(self, name):
        return self._projects.get(name)


@pytest.fixture(autouse=True)
def _forget_previous_answers():
    """The answer is memoized per context; these tests reuse none of them."""
    pfe._declared_versions.clear()
    yield
    pfe._declared_versions.clear()


def _rewrite(path, body):
    """Rewrite a script so that its stat really differs.

    The guard is modification time and size, and a test that rewrites a file
    within the same filesystem timestamp tick and to the same length would be
    testing that nothing was noticed.
    """
    path.write_text(body)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def _plugin(tmp_path, body, path="repo.py"):
    (tmp_path / path).write_text(body)
    parent = FakeProject("//pkg", tmp_path, {"repo": {"type": "basic", "path": path}})
    return FakeContext(), parent


def test_the_script_says_which_version_its_answers_are(tmp_path):
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 9\n\n\ndef get(key):\n    return None\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 9


def test_an_annotated_constant_says_it_just_as_well(tmp_path):
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION: int = 4\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 4


def test_a_script_that_says_nothing_is_unversioned(tmp_path):
    # The default, and what every plugin written before this said.
    ctx, parent = _plugin(tmp_path, "def get(key):\n    return None\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 0


def test_the_script_is_parsed_and_not_run(tmp_path):
    """A plugin is a subprocess elsewhere for a reason; this is not the place.

    Reading the number must not import the module, run its top level, or care
    that it would fail if it did.
    """
    ctx, parent = _plugin(
        tmp_path,
        "raise SystemExit('this top level must never run')\n\nCACHE_VERSION = 2\n",
    )
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 2


def test_a_version_that_is_not_a_number_is_refused_rather_than_guessed(tmp_path):
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 'nine'\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 0


def test_true_is_a_typo_and_not_version_one(tmp_path):
    # 'bool' is an 'int' in Python, so this would otherwise read as 1 and move
    # the whole repository to a namespace nobody meant.
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = True\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 0


def test_a_constant_set_inside_something_is_not_the_module_s(tmp_path):
    ctx, parent = _plugin(tmp_path, "def get(key):\n    CACHE_VERSION = 7\n    return CACHE_VERSION\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 0


def test_a_broken_script_costs_the_version_and_not_the_run(tmp_path):
    """A plugin that will not parse has worse problems, and they are not ours."""
    ctx, parent = _plugin(tmp_path, "def get(key)\n    return None\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 0


def test_a_missing_script_costs_the_version_and_not_the_run(tmp_path):
    parent = FakeProject("//pkg", tmp_path, {"repo": {"type": "basic", "path": "gone.py"}})
    assert pfe.declared_cache_version(FakeContext(), parent, "//pkg:repo") == 0


def test_a_repository_with_no_script_of_its_own_has_no_code_to_version(tmp_path):
    # An 'enrich' repository rewrites another repository's answers and declares
    # no 'path' at all.
    parent = FakeProject("//pkg", tmp_path, {"repo": {"type": "enrich", "source": "other"}})
    assert pfe.declared_cache_version(FakeContext(), parent, "//pkg:repo") == 0


def test_a_plugin_in_another_package_is_looked_up_there(tmp_path):
    """'plugin:' may name another package; the script is still that package's."""
    (tmp_path / "repo.py").write_text("CACHE_VERSION = 5\n")
    host = FakeProject("//host", tmp_path, {"repo": {"type": "basic", "path": "repo.py"}})
    importer = FakeProject("//other", tmp_path, {})
    ctx = FakeContext({"//host": host})
    assert pfe.declared_cache_version(ctx, importer, "//host:repo") == 5


def test_the_whole_hierarchy_gets_one_answer(tmp_path):
    """Read once per plugin reference, so a child cannot land somewhere else.

    The root resolves it first; a child asks with its own parent, which is the
    plugin-backed package rather than the one that hosts the script, and could
    not resolve the script by itself. It must still get the root's answer, or it
    would compute a different cache namespace and stop sharing the root's.
    """
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 3\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 3

    stranger = FakeProject("//ext", tmp_path, {})
    assert pfe.declared_cache_version(ctx, stranger, "//pkg:repo") == 3
    # ...and on its own it could not have: nothing resolves '//pkg' for it.
    assert pfe.declared_cache_version(FakeContext(), stranger, "//pkg:repo") == 0


def test_another_context_reads_the_script_again(tmp_path):
    """The memo is what keeps one hierarchy consistent, not a cache of its own."""
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 3\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 3

    _rewrite(tmp_path / "repo.py", "CACHE_VERSION = 8\n")
    assert pfe.declared_cache_version(FakeContext(), parent, "//pkg:repo") == 8


def test_the_same_context_reads_it_again_once_the_script_changes(tmp_path):
    """A warm daemon must not go on reporting a version the script withdrew.

    'Context.reload_changed_packages()' drops the packages whose configuration
    changed and keeps the context, so an answer held for the life of a context
    outlives the file it came from. A plugin-backed package is not one of the
    packages that reload looks at either - it has no configuration file to stat.
    The script does, and this is what stats it.
    """
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 3\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 3

    _rewrite(tmp_path / "repo.py", "CACHE_VERSION = 8\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 8

    # ...including a plugin that stops stating one at all.
    _rewrite(tmp_path / "repo.py", "def get(key):\n    return None\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 0


def test_an_unchanged_script_is_not_parsed_twice(tmp_path):
    """The memo still earns its keep: a stat, not a parse, on the way back."""
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 3\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 3

    reads = []
    real = pfe._read_declared_cache_version
    pfe._read_declared_cache_version = lambda *a: (reads.append(a), real(*a))[1]
    try:
        assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 3
        # ...and a child of the hierarchy, which cannot resolve the package.
        assert pfe.declared_cache_version(ctx, FakeProject("//ext", tmp_path, {}), "//pkg:repo") == 3
    finally:
        pfe._read_declared_cache_version = real
    assert reads == []


def test_the_old_place_to_say_it_is_named_when_it_is_still_used(caplog):
    """Says which key it was and what replaced it - and only warns about it.

    The package carrying one is somebody else's, published before this changed.
    Raising it to an error would end every command that reaches an unmigrated
    dependency, which is how this was first noticed: the examples suite aborted
    on a library three packages away.
    """

    class Importer(pfe.ExternalImportConfiguration):
        def __init__(self, config_obj):
            self.config_obj = config_obj
            super().__init__()

    Importer({"plugin": ":repo", "cacheVersion": 3})
    assert "cacheVersion" in caplog.text and pfe.CACHE_VERSION_NAME in caplog.text
    assert [r.levelname for r in caplog.records] == ["WARNING"]

    caplog.clear()
    Importer({"plugin": ":repo"})
    assert "cacheVersion" not in caplog.text


def test_a_child_that_cannot_resolve_the_script_does_not_lose_its_version(tmp_path):
    """A stale memo must be refreshed from the script, not from whoever asked.

    The root is the only caller that can resolve the script; a child of the
    hierarchy asks with its own parent and cannot. So when the script changes,
    the child must re-read the path the root found rather than resolving one of
    its own - otherwise it gets 0, and writing that back leaves every later
    lookup, the root's included, reading 0 from a plugin that says 9.
    """
    ctx, parent = _plugin(tmp_path, "CACHE_VERSION = 3\n")
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 3

    _rewrite(tmp_path / "repo.py", "CACHE_VERSION = 9\n")
    stranger = FakeProject("//ext", tmp_path, {})
    assert pfe.declared_cache_version(ctx, stranger, "//pkg:repo") == 9
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 9


def test_the_version_is_found_among_the_plugin_s_other_constants(tmp_path):
    """Every real plugin states other things at module level, and states them first.

    'ldraw_repo.py' sets some forty constants before anything else; the walk has
    to pass over them rather than stop at the first assignment it sees.
    """
    ctx, parent = _plugin(
        tmp_path,
        "_LDU_MM = 0.4\n" "_STUD_MM = 8\n" "NAMES = {'brick': 1}\n" "CACHE_VERSION = 9\n" "_AFTERWARDS = None\n",
    )
    assert pfe.declared_cache_version(ctx, parent, "//pkg:repo") == 9
