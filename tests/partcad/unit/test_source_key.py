#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an implementation runs, as a cache key (`partcad.source_key`).

The key has to move when anything the implementation imports from its package
changes, and must not move for anything else: not for what a run writes into
the package, not for where the package is on this machine, not for when its
files were touched, not for the line endings a checkout chose.
"""

import os
import shutil
import stat
import sys

import pygit2
import pytest

import partcad as pc
from partcad import source_key
from partcad.user_config import UserConfig


def _package(root, files):
    root.mkdir(parents=True, exist_ok=True)
    (root / "partcad.yaml").write_text("name: //plugin\n")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


PLUGIN = {
    "simulate.py": "import common\n",
    "common.py": "SCALE = 1.0\n",
    "lib/geometry.py": "def area(): return 1\n",
}


def test_the_same_package_anywhere_on_any_machine_is_the_same_key(tmp_path):
    here = _package(tmp_path / "home" / "alice" / "plugin", PLUGIN)
    there = _package(tmp_path / "srv" / "ci" / "checkout", PLUGIN)
    assert source_key.directory_key(str(here)) == source_key.directory_key(str(there))


def test_a_helper_is_part_of_it_wherever_it_sits_in_the_package(tmp_path):
    root = _package(tmp_path / "plugin", PLUGIN)
    before = source_key.directory_key(str(root))
    (root / "lib" / "geometry.py").write_text("def area(): return 2\n")
    assert source_key.directory_key(str(root)) != before


def test_a_new_module_and_a_removed_one_are_both_new_keys(tmp_path):
    root = _package(tmp_path / "plugin", PLUGIN)
    first = source_key.directory_key(str(root))
    (root / "extra.py").write_text("X = 1\n")
    second = source_key.directory_key(str(root))
    os.remove(root / "extra.py")
    assert len({first, second, source_key.directory_key(str(root))}) == 2
    assert source_key.directory_key(str(root)) == first


def test_line_endings_a_checkout_chose_are_not_in_it(tmp_path):
    unix = _package(tmp_path / "unix", {"simulate.py": b"import common\nX = 1\n"})
    windows = _package(tmp_path / "windows", {"simulate.py": b"import common\r\nX = 1\r\n"})
    assert source_key.directory_key(str(unix)) == source_key.directory_key(str(windows))


def test_touching_a_file_is_not_changing_it(tmp_path):
    root = _package(tmp_path / "plugin", PLUGIN)
    before = source_key.directory_key(str(root))
    later = os.stat(root / "common.py").st_mtime + 100
    os.utime(root / "common.py", (later, later))
    assert source_key.directory_key(str(root)) == before


def test_what_a_run_writes_into_the_package_is_not_in_it(tmp_path):
    """PartCAD writes models, pictures and READMEs into packages, and never a '.py'."""
    root = _package(tmp_path / "plugin", PLUGIN)
    before = source_key.directory_key(str(root))
    for name in ("bracket.fea.vtu", "panel.nc", "block.svg", "README.md", "scene.xml"):
        (root / name).write_text("output")
    assert source_key.directory_key(str(root)) == before


def test_caches_version_control_environments_and_other_packages_are_not_in_it(tmp_path):
    root = _package(tmp_path / "plugin", PLUGIN)
    before = source_key.directory_key(str(root))
    for relative in (
        "__pycache__/common.py",
        ".git/hooks/pre-commit.py",
        ".venv/lib/thing.py",
        "venv/lib/thing.py",
        "node_modules/x/y.py",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("X = 1\n")
    # A package below this one keys its own runs.
    _package(root / "examples", {"part.py": "show_object(None)\n"})
    assert source_key.directory_key(str(root)) == before


def _settle(root, seconds_ago=60):
    """Make every file of a package as old as files usually are when a run asks."""
    then = os.stat(root / "partcad.yaml").st_mtime - seconds_ago
    for directory, _dirs, files in os.walk(root):
        for name in files:
            os.utime(os.path.join(directory, name), (then, then))


def test_an_unchanged_package_is_not_read_again(tmp_path, monkeypatch):
    """Asked on every run: a 'stat' per file, and a read only of what moved."""
    root = _package(tmp_path / "plugin", PLUGIN)
    _settle(root)
    source_key.directory_key(str(root))

    reads = []
    real = source_key._content

    def counting(path):
        reads.append(os.path.basename(path))
        return real(path)

    monkeypatch.setattr(source_key, "_content", counting)
    source_key.directory_key(str(root))
    source_key.directory_key(str(root))
    assert reads == []

    (root / "common.py").write_text("SCALE = 3.0\n")
    source_key.directory_key(str(root))
    assert "common.py" in reads


def test_two_quick_edits_of_the_same_length_are_both_seen(tmp_path):
    """Racily clean, in git's words: the size and the timestamp are what they were, the content is not.

    Within one tick of the file system's clock a second write leaves the
    modification time as the first one left it. A file that recent is not
    trusted to have been read already.
    """
    root = _package(tmp_path / "plugin", PLUGIN)
    tick = os.stat(root / "common.py").st_mtime_ns
    first = source_key.directory_key(str(root))

    (root / "common.py").write_text("SCALE = 9.0\n")
    os.utime(root / "common.py", ns=(tick, tick))
    assert source_key.directory_key(str(root)) != first


def _commit(repository_path, files, message):
    repository = pygit2.Repository(repository_path)
    for relative, content in files.items():
        path = os.path.join(repository_path, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    repository.index.add_all()
    repository.index.write()
    tree = repository.index.write_tree()
    signature = pygit2.Signature("PartCAD test", "test@partcad.org")
    parents = [] if repository.head_is_unborn else [repository.head.target]
    return str(repository.create_commit("HEAD", signature, signature, message, tree, parents))


def _origin(tmp_path, files=None):
    """A repository a plugin is released from, with one release in it."""
    origin = tmp_path / "origin"
    pygit2.init_repository(str(origin), initial_head="main")
    commit = _commit(str(origin), files or dict(PLUGIN, **{"partcad.yaml": "name: //plugin\n"}), "release 1")
    return origin, commit


def _workspace(tmp_path, state):
    """A context of its own: its own package, and its own state directory to clone into."""
    root = tmp_path / ("workspace-" + state)
    root.mkdir(parents=True, exist_ok=True)
    (root / "partcad.yaml").write_text("name: //workspace\n")
    config = UserConfig()
    config.internal_state_dir = str(tmp_path / state)
    return pc.Context(str(root), user_config=config)


def _imported(tmp_path, origin, state="state"):
    """The package as a 'type: git' import leaves it, through the real import.

    Not a stand-in. The import keeps its type where the import puts it -- the
    package's 'config_obj["type"]', copied there by 'ProjectFactory._create()'
    -- and a stand-in that carried it anywhere else would test a package no
    import ever makes, which is how this was once wrong and green.
    """
    ctx = _workspace(tmp_path, state)
    factory = pc.ProjectFactoryGit(ctx, None, {"name": "//plugin", "type": "git", "url": str(origin)})
    return factory.project


def test_a_package_imported_from_git_is_keyed_on_its_commit(tmp_path):
    origin, commit = _origin(tmp_path)
    package = _imported(tmp_path, origin)

    assert package.config_obj["type"] == "git"
    key = source_key.package_key(package)
    assert key == source_key.directory_key(package.config_dir) + ";git:" + commit


def test_a_release_that_changed_only_a_data_file_is_a_new_key(tmp_path):
    """A data file the plugin reads is not a '.py', and its release still has to count."""
    origin, first = _origin(tmp_path)
    before = source_key.package_key(_imported(tmp_path, origin, state="before"))

    second = _commit(str(origin), {"table.json": "[1, 2]\n"}, "release 2: a data file only")
    after = source_key.package_key(_imported(tmp_path, origin, state="after"))

    assert after != before
    assert after == before.replace(first, second)


def test_one_release_imported_on_two_machines_is_one_key(tmp_path):
    """Two clones in two state directories: the paths differ, the release does not."""
    origin, _commit_id = _origin(tmp_path)
    here = _imported(tmp_path, origin, state="here")
    there = _imported(tmp_path, origin, state="there")

    assert here.config_dir != there.config_dir
    assert source_key.package_key(here) == source_key.package_key(there)


def test_a_local_package_inside_a_repository_is_keyed_on_its_files_alone(tmp_path):
    """Its revision is the one of a tree somebody is editing; the edit is what has to count."""
    checkout = tmp_path / "checkout"
    pygit2.init_repository(str(checkout))
    _commit(str(checkout), dict(PLUGIN, **{"partcad.yaml": "name: //plugin\n"}), "work in progress")
    config = UserConfig()
    config.internal_state_dir = str(tmp_path / "state")
    package = pc.Context(str(checkout), user_config=config).get_project("//")

    key = source_key.package_key(package)
    assert ";git:" not in key
    assert key == source_key.directory_key(str(checkout))


def test_a_revision_is_read_once_per_package(tmp_path, monkeypatch):
    """A managed clone changes only when its package is fetched again, which makes a new package."""
    origin, _commit_id = _origin(tmp_path)
    package = _imported(tmp_path, origin)
    source_key.package_key(package)

    opened = []
    real = pygit2.Repository

    def counting(*args, **kwargs):
        opened.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(pygit2, "Repository", counting)
    source_key.package_key(package)
    assert opened == []


def _remove_tree(path):
    """'shutil.rmtree', for a tree git wrote: its object files are read-only, and Windows refuses those."""

    def writable_then_again(function, target, _error):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable_then_again)
    else:
        shutil.rmtree(path, onerror=writable_then_again)


def test_a_git_package_whose_repository_is_gone_is_still_keyed_on_its_files(tmp_path):
    origin, _commit_id = _origin(tmp_path)
    package = _imported(tmp_path, origin)
    _remove_tree(os.path.join(package.config_dir, ".git"))
    assert source_key.package_key(package) == source_key.directory_key(package.config_dir)


def test_partcad_s_wrappers_are_keyed_the_same_way():
    """'wrapper_export.py' imports 'wrapper_common' and 'ocp_serialize'; the exporters import 'urdf_common'."""
    key = source_key.wrappers_key()
    assert key.startswith("py:")
    assert key == source_key.wrappers_key()


@pytest.mark.parametrize("missing", ["config_dir"])
def test_an_implementation_with_no_package_cannot_be_keyed(missing):
    from partcad import output

    impl = output.Implementation(output.CAE, "fea", {"path": "solve.py"}, None)
    with pytest.raises(ValueError):
        impl.source_cache_key()
