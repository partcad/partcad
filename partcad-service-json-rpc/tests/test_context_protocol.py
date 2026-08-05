#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the context protocol and the daemon's warm state.

The daemon is long-lived and per-workspace: ``context.create`` builds a PartCAD
context once, keys it by the resolved workspace root, and every later command
carries that id back so the warm context is reused. That is the daemon's reason
to exist, and it is also what makes it fragile -- state that leaks between
requests (``force_update``) or survives a mutation (a context whose
``partcad.yaml`` changed underneath it) is invisible to any single-command test.

``partcad`` itself is never imported here: the operations reach the module only
through ``session.partcad``, so a fake module object that behaves like the real
one -- one shared ``user_config``, contexts built from a directory and never
re-read afterwards, ``init()`` memoizing per path -- exercises all of it without a
CAD environment.
"""

import contextlib
import os
from pathlib import Path

import pytest
import yaml
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError


class FakeLogging:
    """The subset of ``partcad.logging`` these operations reach for."""

    @contextlib.contextmanager
    def Process(self, *args, **kwargs):  # noqa: N802 - mirrors partcad.logging
        yield

    @contextlib.contextmanager
    def Action(self, *args, **kwargs):  # noqa: N802 - mirrors partcad.logging
        yield

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class FakeUserConfig:
    """``partcad.user_config``: one object per process, shared by every context.

    That sharing is the reason a leaked ``force_update`` is severe -- it does not
    just affect the workspace that ran ``pc install``, it affects every workspace
    the daemon serves.
    """

    def __init__(self, force_update=False, internal_state_dir=None):
        self.force_update = force_update
        self.internal_state_dir = internal_state_dir


class FakePackage:
    """The subset of ``partcad.Project`` the mutating operations touch."""

    def __init__(self, name="//"):
        self.name = name
        self.added = []
        self.add_result = True
        self.add_error = None

    def add_assembly(self, kind, path, config=None):
        if self.add_error is not None:
            raise self.add_error
        self.added.append((kind, path))
        return self.add_result

    def rel_path(self, path):
        return os.path.basename(path)


class FakeContext:
    """A PartCAD context as the daemon holds it.

    Built once from a directory and never re-read afterwards -- which is exactly
    why a mutation of ``partcad.yaml`` has to evict it rather than refresh it.
    """

    def __init__(self, path, user_config):
        self.path = path
        self.user_config = user_config
        self.stats_git_ops = 0
        self.packages = ["//", "//sub"]
        self.project = FakePackage()
        self.fail_with = None
        # get_all_packages() records the force_update it actually ran under: the
        # point of install/update is that the fetch *is* forced, and the point of
        # the save/restore is that nothing else is.
        self.force_update_during_fetch = None
        self.get_all_packages_calls = 0

    def get_all_packages(self, parent_name=None, has_stuff=True):
        self.get_all_packages_calls += 1
        self.force_update_during_fetch = self.user_config.force_update
        if self.fail_with is not None:
            raise self.fail_with
        return [{"name": name, "desc": ""} for name in self.packages]

    def resolve_package_path(self, package):
        return "//" if package in (None, "", ".") else package

    def get_project(self, name):
        return self.project


class FakePartcad:
    """Stands in for the ``partcad`` module on ``session.partcad``.

    ``session.ensure_partcad()`` hands this back untouched because the session
    already has a module, so no real ``import partcad`` happens.
    """

    __version__ = "0.7.153"

    def __init__(self, user_config=None):
        self.logging = FakeLogging()
        self.user_config = user_config if user_config is not None else FakeUserConfig()
        self.contexts_built = []  # every context the daemon constructed, in order
        self.init_calls = []  # pc.init() must never be used to build one
        self.context_error = None  # raised by the next Context() call
        self._init_cache = {}

    def Context(self, path, user_config=None, **kwargs):  # noqa: N802 - mirrors partcad.Context
        if self.context_error is not None:
            raise self.context_error
        ctx = FakeContext(path, user_config if user_config is not None else self.user_config)
        self.contexts_built.append(ctx)
        return ctx

    def init(self, path, user_config=None):
        # The real pc.init() memoizes one context per path and hands the same
        # (possibly stale) object back on every call. Reproduce that so a test can
        # tell an init()-built context from a freshly constructed one.
        self.init_calls.append(path)
        if self.context_error is not None:
            raise self.context_error
        if path not in self._init_cache:
            self._init_cache[path] = FakeContext(path, self.user_config)
        return self._init_cache[path]


def make_session(user_config=None):
    """A session holding the fake partcad module and no context yet."""
    seen = []
    session = Session(EventEmitter(lambda e, p: seen.append((e, p))))
    session.partcad = FakePartcad(user_config)
    return session, seen


def workspace_url(path):
    """Build the workspace URL exactly as ``partcad_cli.click.service.run`` does."""
    return Path(path).resolve().as_uri()


def create_context(session, path):
    """Run the ``context.create`` handshake the CLI performs before every command."""
    return operations.context_create(session, {"url": workspace_url(path)})["context"]


# ---- context.create: identity and reuse -------------------------------------


def test_the_same_url_yields_the_same_id_and_reuses_the_warm_context(tmp_path):
    session, _ = make_session()

    first = operations.context_create(session, {"url": workspace_url(tmp_path)})
    second = operations.context_create(session, {"url": workspace_url(tmp_path)})

    assert first["context"] == second["context"]
    # Reused rather than rebuilt -- otherwise the daemon buys the client nothing.
    assert len(session.partcad.contexts_built) == 1
    assert session.contexts[first["context"]] is session.partcad.contexts_built[0]


def test_a_request_without_a_url_uses_the_working_directory_as_a_real_uri(tmp_path, monkeypatch):
    """The no-url fallback must build the same context as an explicit URL.

    It used to concatenate "file://" onto the path, which is not a valid URL for
    a Windows working directory ("file://C:\\proj" parses the drive as the
    authority): the daemon would build the context on the wrong root and give it
    an id that never matches the one a client computes for the same directory.
    """
    session, _ = make_session()
    monkeypatch.chdir(tmp_path)

    implicit = operations.context_create(session, {})["context"]
    explicit = operations.context_create(session, {"url": workspace_url(tmp_path)})["context"]

    assert implicit == explicit
    assert len(session.partcad.contexts_built) == 1


def test_urls_denoting_the_same_directory_share_one_context(tmp_path):
    """The id is keyed on the resolved root, not on the URL text."""
    session, _ = make_session()

    plain = operations.context_create(session, {"url": workspace_url(tmp_path)})["context"]
    trailing_slash = operations.context_create(session, {"url": workspace_url(tmp_path) + "/"})["context"]

    assert trailing_slash == plain
    assert len(session.partcad.contexts_built) == 1


def test_different_workspaces_get_different_ids_and_separate_contexts(tmp_path):
    session, _ = make_session()
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()

    first = create_context(session, first_dir)
    second = create_context(session, second_dir)

    assert first != second
    assert session.contexts[first] is not session.contexts[second]
    assert len(session.contexts) == 2
    assert session.contexts[first].path.endswith("one")
    assert session.contexts[second].path.endswith("two")


def test_context_create_leaves_the_newest_context_as_the_session_default(tmp_path):
    """The extension's context-less operations keep working alongside the CLI's."""
    session, _ = make_session()
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()

    create_context(session, first_dir)
    second = create_context(session, second_dir)

    assert session.partcad_ctx is session.contexts[second]


def test_context_create_never_goes_through_pc_init(tmp_path):
    """pc.init() caches a context per path, so it would hand back a stale one."""
    session, _ = make_session()

    create_context(session, tmp_path)

    assert session.partcad.init_calls == []
    assert len(session.partcad.contexts_built) == 1


def test_an_evicted_context_is_rebuilt_from_disk_under_the_same_id(tmp_path):
    """The recovery half of the mutation story: re-read, do not resurrect."""
    session, _ = make_session()
    first_id = create_context(session, tmp_path)
    stale = session.contexts[first_id]

    operations._invalidate_context(session, {"context": first_id})
    second_id = create_context(session, tmp_path)

    assert second_id == first_id  # same workspace, same id
    assert session.contexts[second_id] is not stale  # but a fresh read of partcad.yaml
    assert len(session.partcad.contexts_built) == 2
    assert session.partcad.init_calls == []
    assert session.partcad_ctx is session.contexts[second_id]


def test_an_unparseable_config_is_reported_and_leaves_the_registry_clean(tmp_path):
    session, _ = make_session()
    session.partcad.context_error = yaml.scanner.ScannerError(None, None, "mapping values are not allowed", None)

    with pytest.raises(JsonRpcError) as excinfo:
        operations.context_create(session, {"url": workspace_url(tmp_path)})

    assert excinfo.value.code == operations.INVALID_CONFIG
    assert excinfo.value.message == "Invalid configuration file"
    assert "mapping values are not allowed" in excinfo.value.data["detail"]
    # A failed create must not leave a half-built context behind, or the next
    # command would be served by it.
    assert session.contexts == {}
    assert session.partcad_ctx is None


def test_a_context_that_failed_to_build_can_be_created_after_the_config_is_fixed(tmp_path):
    session, _ = make_session()
    session.partcad.context_error = yaml.parser.ParserError(None, None, "bad syntax", None)
    with pytest.raises(JsonRpcError):
        operations.context_create(session, {"url": workspace_url(tmp_path)})

    session.partcad.context_error = None
    context_id = create_context(session, tmp_path)

    assert session.contexts[context_id] is not None


# ---- _ctx: which context serves a request -----------------------------------


def test_a_request_without_a_context_id_falls_back_to_the_session_context(tmp_path):
    """The VS Code extension's flow: one context, established out of band."""
    session, _ = make_session()
    warm = FakeContext(str(tmp_path), session.partcad.user_config)
    session.partcad_ctx = warm

    assert operations._ctx(session, {}) is warm

    operations.install(session, {})
    assert warm.get_all_packages_calls == 1


def test_a_context_id_outranks_the_session_default(tmp_path):
    """One daemon serves several workspaces; the id decides, not recency."""
    session, _ = make_session()
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = create_context(session, first_dir)
    second = create_context(session, second_dir)
    assert session.partcad_ctx is session.contexts[second]

    assert operations._ctx(session, {"context": first}) is session.contexts[first]


def test_an_unknown_context_id_is_a_usage_error(tmp_path):
    session, _ = make_session()
    session.partcad_ctx = FakeContext(str(tmp_path), session.partcad.user_config)

    with pytest.raises(JsonRpcError) as excinfo:
        operations._ctx(session, {"context": "0123456789abcdef"})

    assert excinfo.value.code == operations.USAGE_ERROR
    assert "0123456789abcdef" in excinfo.value.message


def test_a_stale_context_id_fails_the_operation_instead_of_using_the_default(tmp_path):
    """A daemon restart invalidates every id the client holds; say so.

    Falling back to the session default here would silently run the command
    against whichever workspace the daemon happened to touch last.
    """
    session, _ = make_session()
    warm = FakeContext(str(tmp_path), session.partcad.user_config)
    session.partcad_ctx = warm

    with pytest.raises(JsonRpcError) as excinfo:
        operations.install(session, {"context": "deadbeefdeadbeef"})

    assert excinfo.value.code == operations.USAGE_ERROR
    assert warm.get_all_packages_calls == 0


def test_a_request_with_nothing_loaded_is_a_silent_noop():
    session, seen = make_session()

    assert operations._ctx(session, {}) is None
    assert operations.install(session, {}) is None
    assert seen == []


# ---- warm state: force_update must not outlive the command -------------------


@pytest.mark.parametrize("operation", [operations.install, operations.update], ids=["install", "update"])
@pytest.mark.parametrize("initial", [False, True], ids=["off", "on"])
def test_fetching_packages_forces_the_update_and_then_restores_the_setting(tmp_path, operation, initial):
    """``pc install`` used to leave force_update on, so every later command in
    that daemon re-fetched every package."""
    session, _ = make_session(FakeUserConfig(force_update=initial))
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    operation(session, {"context": context_id})

    assert ctx.force_update_during_fetch is True  # the fetch really was forced
    assert ctx.user_config.force_update is initial  # ...and the daemon is back to normal


@pytest.mark.parametrize("operation", [operations.install, operations.update], ids=["install", "update"])
def test_force_update_is_restored_even_when_the_fetch_fails(tmp_path, operation):
    """A failed fetch is the likeliest way to leave the daemon permanently forced."""
    session, _ = make_session(FakeUserConfig(force_update=False))
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]
    ctx.fail_with = RuntimeError("network is down")

    with pytest.raises(RuntimeError):
        operation(session, {"context": context_id})

    assert ctx.user_config.force_update is False


def test_installing_one_workspace_does_not_force_updates_in_another(tmp_path):
    """Contexts share ``partcad.user_config``, so a leak crosses workspaces."""
    session, _ = make_session(FakeUserConfig(force_update=False))
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = create_context(session, first_dir)
    second = create_context(session, second_dir)
    assert session.contexts[first].user_config is session.contexts[second].user_config

    operations.install(session, {"context": first})

    # Stand-in for the next command served for the other workspace: its package
    # fetch must not be in force-update mode.
    session.contexts[second].get_all_packages()
    assert session.contexts[second].force_update_during_fetch is False


def test_update_reports_the_number_of_packages_it_refreshed(tmp_path):
    session, seen = make_session()
    context_id = create_context(session, tmp_path)
    session.contexts[context_id].packages = ["//", "//sub", "//sub/deeper"]

    assert operations.update(session, {"context": context_id}) == {"count": 3}
    assert ("info", "Successfully updated 3 packages") in seen


# ---- warm state: a mutation must evict the context it changed ----------------


def add_assembly_params(context_id, path):
    """Params for the one mutating operation that needs no real partcad import."""
    return {
        "context": context_id,
        "obj_kind": "assembly",
        "kind": "assy",
        "path": str(path),
        "package": ".",
    }


def test_adding_an_object_evicts_the_context_it_mutated(tmp_path):
    """PartCAD writes partcad.yaml without refreshing the in-memory registry, so
    the warm context would keep serving the package as it was before the add."""
    session, _ = make_session()
    assembly = tmp_path / "assy.assy"
    assembly.write_text("{}")
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    result = operations.add_object(session, add_assembly_params(context_id, assembly))

    assert result == {"name": "assy"}
    assert ctx.project.added == [("assy", str(assembly))]
    assert context_id not in session.contexts
    # The evicted context was also the session default; it must not survive there.
    assert session.partcad_ctx is None


def test_the_context_is_evicted_even_when_the_mutation_fails(tmp_path):
    """A failed add may still have written part of partcad.yaml, so the warm copy
    cannot be trusted either way."""
    session, _ = make_session()
    assembly = tmp_path / "assy.assy"
    assembly.write_text("{}")
    context_id = create_context(session, tmp_path)
    session.contexts[context_id].project.add_error = RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        operations.add_object(session, add_assembly_params(context_id, assembly))

    assert context_id not in session.contexts


def test_evicting_one_context_leaves_the_other_workspaces_alone(tmp_path):
    session, _ = make_session()
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    assembly = first_dir / "assy.assy"
    assembly.write_text("{}")
    first = create_context(session, first_dir)
    second = create_context(session, second_dir)
    second_ctx = session.contexts[second]

    operations.add_object(session, add_assembly_params(first, assembly))

    assert first not in session.contexts
    assert session.contexts[second] is second_ctx
    # The session default was the *other* workspace, so it stays warm.
    assert session.partcad_ctx is second_ctx


def test_the_command_after_a_mutation_is_served_by_a_freshly_read_context(tmp_path):
    """The whole point of the eviction, end to end: create, mutate, create again."""
    session, _ = make_session()
    assembly = tmp_path / "assy.assy"
    assembly.write_text("{}")
    first_id = create_context(session, tmp_path)
    stale = session.contexts[first_id]

    operations.add_object(session, add_assembly_params(first_id, assembly))
    second_id = create_context(session, tmp_path)

    assert second_id == first_id
    assert operations._ctx(session, {"context": second_id}) is not stale
    assert len(session.partcad.contexts_built) == 2


def test_a_rejected_path_is_reported_without_touching_the_context(tmp_path):
    """The existence check runs before any mutation, so nothing needs evicting."""
    session, _ = make_session()
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    with pytest.raises(JsonRpcError) as excinfo:
        operations.add_object(session, add_assembly_params(context_id, tmp_path / "missing.assy"))

    assert excinfo.value.code == operations.USAGE_ERROR
    assert session.contexts[context_id] is ctx
    assert ctx.project.added == []


def test_system_reset_drops_every_warm_context(tmp_path):
    """The reset deletes the directories the contexts point into; none may survive."""
    session, _ = make_session(FakeUserConfig(internal_state_dir=str(tmp_path / "state")))
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    create_context(session, first_dir)
    create_context(session, second_dir)

    operations.system_reset(session, {})

    assert session.contexts == {}
    assert session.partcad_ctx is None
