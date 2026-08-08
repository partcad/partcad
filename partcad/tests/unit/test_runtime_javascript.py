#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The JavaScript sandbox layout and its dependency bookkeeping.

These exercise the parts that decide *where* things go and *what* gets
installed, which is what makes two PartCAD packages independent of each other.
Nothing here needs a Node.js on the host.
"""

import json
import os

import pytest

from partcad import sandbox_versions
from partcad.runtime_javascript import (
    BASE_ENV_DIR,
    GUARD_INVALIDATED_BY,
    JavaScriptRuntime,
    clear_reassert,
    env_dir_name,
    get_guard_path,
    invalidate_dependent_guards,
    link_or_copy,
    needs_reassert,
    package_dir_name,
    runtime_exit_description,
)


def _bare_runtime(path):
    """A JavaScriptRuntime with just the attributes the layout helpers touch.

    __init__ wants a full context, which is far more than these need.
    """
    runtime = JavaScriptRuntime.__new__(JavaScriptRuntime)
    runtime.path = str(path)
    return runtime


#
# Version pins
#


def test_the_default_chili3d_is_an_exact_version():
    """The default has to be reproducible; a package may still float its own."""
    assert sandbox_versions.CHILI3D == "chili3d@" + sandbox_versions.DEFAULT_CHILI3D_VERSION
    assert sandbox_versions.DEFAULT_CHILI3D_VERSION[0].isdigit()


@pytest.mark.parametrize(
    "requirement, expected",
    [
        ("chili3d", "chili3d"),
        ("chili3d@1.1.2", "chili3d"),
        ("happy-dom@^20.11.2", "happy-dom"),
        # A scoped name's leading '@' is not the version separator
        ("@scope/pkg", "@scope/pkg"),
        ("@scope/pkg@1.2.3", "@scope/pkg"),
    ],
)
def test_js_package_name(requirement, expected):
    assert sandbox_versions.js_package_name(requirement) == expected


@pytest.mark.parametrize(
    "version, expected",
    [
        (None, sandbox_versions.CHILI3D),
        ("", sandbox_versions.CHILI3D),
        # A bare version becomes an exact requirement
        ("1.0.0", "chili3d@1.0.0"),
        # ... and anything npm would read as a range or a tag is passed through,
        # so a package that wants to float can say so.
        ("^1.1", "chili3d@^1.1"),
        ("latest", "chili3d@latest"),
    ],
)
def test_chili3d_requirement(version, expected):
    assert sandbox_versions.chili3d_requirement(version) == expected


@pytest.mark.parametrize(
    "version, expected",
    [("22", "22"), ("22.11", "22"), ("v22.11.0", "22"), (22, "22")],
)
def test_node_major_version(version, expected):
    assert sandbox_versions.node_major_version(version) == expected


def test_min_node_version_is_not_above_the_default():
    """A package that asks for nothing must not get a sandbox below the floor."""
    assert (
        sandbox_versions.at_least(sandbox_versions.DEFAULT_NODE_VERSION, sandbox_versions.MIN_NODE_VERSION)
        == sandbox_versions.DEFAULT_NODE_VERSION
    )


#
# The sandbox layout
#


def test_env_dir_name_is_the_set_not_the_order():
    """Two packages that ask for the same things share one dependency tree."""
    assert env_dir_name(["a@1", "b@2"]) == env_dir_name(["b@2", "a@1"])
    assert env_dir_name(["a@1", "b@2", "a@1"]) == env_dir_name(["a@1", "b@2"])


def test_env_dir_name_separates_different_sets():
    assert env_dir_name(["a@1"]) != env_dir_name(["a@2"])
    assert env_dir_name(["a@1"]) != env_dir_name(["a@1", "b@2"])


def test_env_dir_name_of_nothing_is_the_baseline():
    assert env_dir_name([]) == BASE_ENV_DIR


def test_package_dir_is_named_after_the_package():
    assert package_dir_name("//pub/a") != package_dir_name("//pub/b")
    assert package_dir_name("//pub/a") == package_dir_name("//pub/a")
    assert package_dir_name("//pub/a").startswith("pkg-")


def test_a_clean_session_uses_the_baseline_environment(tmp_path):
    runtime = _bare_runtime(tmp_path)
    session = {"name": "//pub/a", "dirty": False, "deps": list(sandbox_versions.DEFAULT_JS_REQUIREMENTS)}

    assert runtime.get_env_path(session) == os.path.join(str(tmp_path), BASE_ENV_DIR)


def test_a_dirty_session_gets_its_own_environment(tmp_path):
    runtime = _bare_runtime(tmp_path)
    session = {"name": "//pub/a", "dirty": True, "deps": ["seedrandom@3.0.5"]}

    env_path = runtime.get_env_path(session)

    assert env_path != os.path.join(str(tmp_path), BASE_ENV_DIR)
    assert os.path.basename(env_path).startswith("v-env-")


def test_packages_never_share_a_working_directory(tmp_path):
    """The third level is what keeps one package's local files out of another's."""
    runtime = _bare_runtime(tmp_path)
    a = {"name": "//pub/a", "dirty": False, "deps": []}
    b = {"name": "//pub/b", "dirty": False, "deps": []}

    a_path = runtime.get_package_path(a)
    b_path = runtime.get_package_path(b)

    assert a_path != b_path
    # ... but they do share the dependency tree above them
    assert os.path.dirname(a_path) == os.path.dirname(b_path)


def test_without_a_session_the_environment_itself_is_the_working_directory(tmp_path):
    runtime = _bare_runtime(tmp_path)

    assert runtime.get_package_path() == runtime.get_env_path()


def test_prepare_package_dir_links_the_tree_in(tmp_path):
    runtime = _bare_runtime(tmp_path)
    session = {"name": "//pub/a", "dirty": False, "deps": []}
    env_path = runtime.get_env_path(session)
    os.makedirs(os.path.join(env_path, "node_modules"))
    open(os.path.join(env_path, "package.json"), "w").write("{}")

    package_path = runtime.prepare_package_dir_locked(session)

    # Node.js and npm both resolve from the working directory, so both have to
    # be reachable from inside it.
    assert os.path.isdir(os.path.join(package_path, "node_modules"))
    assert os.path.exists(os.path.join(package_path, "package.json"))


def test_prepare_package_dir_is_idempotent(tmp_path):
    runtime = _bare_runtime(tmp_path)
    session = {"name": "//pub/a", "dirty": False, "deps": []}
    os.makedirs(os.path.join(runtime.get_env_path(session), "node_modules"))

    runtime.prepare_package_dir_locked(session)
    package_path = runtime.prepare_package_dir_locked(session)

    assert os.path.isdir(os.path.join(package_path, "node_modules"))


def test_link_or_copy_leaves_an_existing_entry_alone(tmp_path):
    source = tmp_path / "source"
    source.write_text("source")
    destination = tmp_path / "destination"
    destination.write_text("destination")

    link_or_copy(str(source), str(destination))

    assert destination.read_text() == "destination"


#
# The manifest
#


def test_prepare_env_creates_a_manifest_npm_can_install_into(tmp_path):
    runtime = _bare_runtime(tmp_path)
    env_path = os.path.join(str(tmp_path), BASE_ENV_DIR)

    runtime.prepare_env_locked(env_path)

    manifest = json.load(open(os.path.join(env_path, "package.json")))
    assert manifest["private"] is True
    # The wrappers and the scripts they run are ES modules
    assert manifest["type"] == "module"


def test_prepare_env_keeps_what_npm_recorded(tmp_path):
    """Rewriting the manifest from scratch would make npm prune the tree.

    npm records every install under "dependencies" in this very file and treats
    anything missing from it as no longer wanted, so a package installed by an
    earlier call has to survive the next one.
    """
    runtime = _bare_runtime(tmp_path)
    env_path = os.path.join(str(tmp_path), BASE_ENV_DIR)
    runtime.prepare_env_locked(env_path)
    manifest_path = os.path.join(env_path, "package.json")
    manifest = json.load(open(manifest_path))
    manifest["dependencies"] = {"chili3d": "1.1.2"}
    json.dump(manifest, open(manifest_path, "w"))

    runtime.prepare_env_locked(env_path)

    assert json.load(open(manifest_path))["dependencies"] == {"chili3d": "1.1.2"}


#
# Install guards
#


def test_guards_are_per_package_and_per_environment(tmp_path):
    other = tmp_path / "other"
    other.mkdir()

    assert get_guard_path(str(tmp_path), "a@1") != get_guard_path(str(tmp_path), "a@2")
    assert get_guard_path(str(tmp_path), "a@1") != get_guard_path(str(other), "a@1")


def test_reassert_round_trip(tmp_path):
    """The mechanism the Python side needs for OCP, kept in step for npm."""
    assert not needs_reassert(str(tmp_path), "a@1")

    guard = get_guard_path(str(tmp_path), "a@1")
    open(guard, "w").close()
    GUARD_INVALIDATED_BY["clobberer@1"] = ("a@1",)
    try:
        invalidate_dependent_guards(str(tmp_path), "clobberer@1")
    finally:
        del GUARD_INVALIDATED_BY["clobberer@1"]

    assert not os.path.exists(guard)
    assert needs_reassert(str(tmp_path), "a@1")

    clear_reassert(str(tmp_path), "a@1")
    assert not needs_reassert(str(tmp_path), "a@1")


def test_unrelated_install_invalidates_nothing(tmp_path):
    guard = get_guard_path(str(tmp_path), "a@1")
    open(guard, "w").close()

    invalidate_dependent_guards(str(tmp_path), "b@1")

    assert os.path.exists(guard)
    assert not needs_reassert(str(tmp_path), "a@1")


#
# Sessions
#


def _runtime_for_sessions(tmp_path):
    runtime = _bare_runtime(tmp_path)
    runtime.superseded_requirements = set()
    return runtime


def test_a_session_starts_on_the_shared_baseline(tmp_path):
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    assert session["dirty"] is False
    assert set(session["deps"]) == set(sandbox_versions.DEFAULT_JS_REQUIREMENTS)


def test_asking_for_a_pinned_package_keeps_the_session_clean(tmp_path):
    """A part declaring the stack it already has must not fork a tree for it."""
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, sandbox_versions.CHILI3D)

    assert session["dirty"] is False
    assert runtime.get_env_path(session) == os.path.join(str(tmp_path), BASE_ENV_DIR)


def test_asking_for_anything_else_forks_a_tree(tmp_path):
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, "seedrandom@3.0.5")

    assert session["dirty"] is True
    # The forked tree carries the whole set, baseline included: a package that
    # adds a dependency still needs Chili3D.
    assert set(sandbox_versions.DEFAULT_JS_REQUIREMENTS) <= set(session["deps"])
    assert "seedrandom@3.0.5" in session["deps"]


def test_a_dependency_is_declared_once(tmp_path):
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, "seedrandom@3.0.5")
    runtime.declare_dependency(session, "seedrandom@3.0.5")

    assert session["deps"].count("seedrandom@3.0.5") == 1


def test_two_packages_with_the_same_extra_share_a_tree(tmp_path):
    runtime = _runtime_for_sessions(tmp_path)
    a = JavaScriptRuntime.get_session(runtime, "//pub/a")
    b = JavaScriptRuntime.get_session(runtime, "//pub/b")

    runtime.declare_dependency(a, "seedrandom@3.0.5")
    runtime.declare_dependency(b, "seedrandom@3.0.5")

    assert runtime.get_env_path(a) == runtime.get_env_path(b)
    assert runtime.get_package_path(a) != runtime.get_package_path(b)


def test_a_part_may_choose_its_own_chili3d(tmp_path):
    """The version is a package's to choose - it only moves that package."""
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, "chili3d@1.0.0")

    # One tree cannot hold two Chili3D versions, so the ask replaces the default
    # rather than joining it...
    assert session["deps"].count("chili3d@1.0.0") == 1
    assert sandbox_versions.CHILI3D not in session["deps"]
    # ... and it lands somewhere of its own, so no other package is affected.
    assert session["dirty"] is True
    assert runtime.get_env_path(session) != os.path.join(str(tmp_path), BASE_ENV_DIR)


def test_a_default_yields_to_what_was_already_asked_for(tmp_path):
    """This is what lets 'javascriptRequirements' name Chili3D itself."""
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, "chili3d@1.0.0")
    runtime.declare_dependency(session, sandbox_versions.CHILI3D, default=True)

    assert "chili3d@1.0.0" in session["deps"]


def test_restating_a_default_leaves_the_session_on_the_baseline(tmp_path):
    """'chili3dVersion' set to what PartCAD installs anyway must not fork a tree."""
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, sandbox_versions.CHILI3D)

    assert session["dirty"] is False
    assert runtime.get_env_path(session) == os.path.join(str(tmp_path), BASE_ENV_DIR)


def test_going_back_to_the_default_returns_to_the_baseline(tmp_path):
    """'dirty' is derived from the result, not accumulated as declarations arrive."""
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, "chili3d@1.0.0")
    runtime.declare_dependency(session, sandbox_versions.CHILI3D)

    assert session["dirty"] is False


def test_two_versions_of_one_package_never_coexist(tmp_path):
    """npm cannot produce such a tree, so the declarations have to resolve to one."""
    runtime = _runtime_for_sessions(tmp_path)
    session = JavaScriptRuntime.get_session(runtime, "//pub/a")

    runtime.declare_dependency(session, "seedrandom@3.0.5")
    runtime.declare_dependency(session, "seedrandom@2.4.4")

    assert [dep for dep in session["deps"] if dep.startswith("seedrandom")] == ["seedrandom@2.4.4"]


#
# Diagnostics
#


def test_runtime_exit_description_names_the_signal():
    import signal

    assert "SIGSEGV" in runtime_exit_description(-int(signal.SIGSEGV))
    assert "unknown signal" in runtime_exit_description(-99)


def test_runtime_exit_description_explains_a_wasm_abort():
    assert "WebAssembly" in runtime_exit_description(134)


def test_runtime_exit_description_plain_failure():
    assert runtime_exit_description(1) == "exit code 1"
