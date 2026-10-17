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
from types import SimpleNamespace

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

    def __init__(self, force_update=False, internal_state_dir=None, devel_index=False, settings=None):
        self.force_update = force_update
        self.internal_state_dir = internal_state_dir
        self.devel_index = devel_index
        # What UserConfig.from_dict() was handed, so a test can tell a context
        # built from the caller's configuration from one built from the
        # daemon's own.
        self.settings = settings

    @classmethod
    def from_dict(cls, data):
        """``partcad.UserConfig.from_dict``: the caller's configuration, rebuilt."""
        return cls(
            force_update=bool(data.get("forceUpdate")),
            devel_index=bool(data.get("develIndex")),
            settings=dict(data),
        )


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
        # As on a real Context: the root package it loaded, and the only thing
        # that knows whether that package parsed. A missing or unparseable
        # 'partcad.yaml' leaves this 'None' or 'broken'.
        self.root = SimpleNamespace(broken=False, config_path=os.path.join(path, "partcad.yaml"))
        self.fail_with = None
        # get_all_packages() records the force_update and the refresh it
        # actually ran under: 'pc update' refreshes the imports of its own
        # context for the length of the call, and nothing else may.
        self.force_update_during_fetch = None
        self.refresh_imports = False
        self.refresh_during_fetch = None
        self.get_all_packages_calls = 0
        # How many times everything loaded was dropped and read again
        # ('Context.reload_all_packages', which 'pc update' asks for).
        self.full_reloads = 0
        # How many times a request asked for the changed packages to be
        # reloaded (see 'Context.reload_changed_packages').
        self.reloads = 0

    def reload_changed_packages(self, packages=None, recursive=False):
        self.reloads += 1
        self.reload_targets = (packages, recursive)
        return []

    def reload_all_packages(self):
        self.full_reloads += 1
        return list(self.packages)

    def get_all_packages(self, parent_name=None, has_stuff=True):
        self.get_all_packages_calls += 1
        self.force_update_during_fetch = self.user_config.force_update
        self.refresh_during_fetch = self.refresh_imports
        if self.fail_with is not None:
            raise self.fail_with
        return [{"name": name, "desc": ""} for name in self.packages]

    def resolve_package_path(self, package):
        return "//" if package in (None, "", ".") else package

    def get_project(self, name):
        # The daemon reads the resolved package's own name back off the package
        # object; mirror that so a test can tell which one an operation picked.
        # 'project = None' stands for a package that does not exist.
        if self.project is not None:
            self.project.name = name or "//"
        return self.project


class FakeInstallAction:
    """``partcad.actions.package``: records what an install was asked to prepare.

    The actions themselves (walking a package's objects and computing their
    cache keys; moving the pins of tracked dependencies) live in ``partcad`` and
    are tested there; what matters here is which packages the operation hands
    them and what it does with the counts back.
    """

    def __init__(self):
        self.calls = []
        self.stats = {"sketch": 0, "part": 0, "assembly": 0, "software": 0, "failed": 0, "failed_packages": 0}
        self.update_calls = []
        self.update_stats = {"pinned": 0, "current": 0, "failed": 0}

    def install(self, ctx, packages):
        self.calls.append((ctx, list(packages)))
        return dict(self.stats)

    def update(self, ctx):
        # What the real one does to the context, which is what the daemon's
        # warm state depends on: everything read again, then fetched under a
        # refresh that ends with the call however the call ends.
        self.update_calls.append(ctx)
        ctx.reload_all_packages()
        ctx.refresh_imports = True
        try:
            count = len(ctx.get_all_packages())
        finally:
            ctx.refresh_imports = False
        return dict(self.update_stats, count=count)


class FakeSandboxLock:
    """``partcad.sandbox_lock``: records each configuration the slots were sized for.

    In order, so that a test can tell which request's configuration the slots
    were left at -- they belong to the process, and every request moves them.
    """

    def __init__(self):
        self.followed = []

    def follow(self, config):
        self.followed.append(config)


class FakePartcad:
    """Stands in for the ``partcad`` module on ``session.partcad``.

    ``session.ensure_partcad()`` hands this back untouched because the session
    already has a module, so no real ``import partcad`` happens.
    """

    __version__ = "0.7.158"

    # partcad exports the class next to the singleton; the daemon builds the
    # caller's configuration through it.
    UserConfig = FakeUserConfig

    def __init__(self, user_config=None):
        self.logging = FakeLogging()
        self.actions = SimpleNamespace(package=FakeInstallAction())
        self.user_config = user_config if user_config is not None else FakeUserConfig()
        self.sandbox_lock = FakeSandboxLock()
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


@pytest.mark.parametrize(
    "state",
    [
        # A 'partcad.yaml' that is not there at all.
        "missing",
        # One that is there and did not parse, or named an 'import:' section the
        # root may not have: 'Project.broken', reported and remembered.
        "broken",
    ],
)
def test_a_context_whose_root_did_not_load_is_read_again(tmp_path, state):
    """A failed load must not be what this daemon answers with from then on.

    The errors explaining it were logged while the context was being built, so a
    cached failure is a command that exits non-zero with a reason followed by any
    number of commands that exit zero with an empty answer -- which is how two
    spellings of one request ('...' and './...') come to look like one of them is
    broken, when what differs is which of them was typed first. Re-reading also
    means a 'partcad.yaml' written in between is seen, rather than denied until
    the daemon is stopped.
    """
    session, _ = make_session()

    first = operations.context_create(session, {"url": workspace_url(tmp_path)})["context"]
    if state == "missing":
        session.contexts[first].root = None
    else:
        session.contexts[first].root.broken = True

    second = operations.context_create(session, {"url": workspace_url(tmp_path)})["context"]

    # The same workspace, so the same id: the client's context id stays valid.
    assert second == first
    assert len(session.partcad.contexts_built) == 2
    assert session.contexts[second] is session.partcad.contexts_built[1]
    # ...and the operations that follow this handshake get the fresh one.
    assert session.partcad_ctx is session.contexts[second]


def test_an_operation_on_a_context_reloads_its_changed_packages_first(tmp_path):
    """The CLI's path: a context id, and the context kept rather than rebuilt."""
    session, _ = make_session()
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    assert operations._ctx(session, {"context": context_id}) is ctx
    assert ctx.reloads == 1
    assert create_context(session, tmp_path) == context_id
    assert len(session.partcad.contexts_built) == 1


@pytest.mark.parametrize(
    "params, expected",
    [
        # Nothing named: the package the command runs in.
        ({}, (["//"], False)),
        ({"package": "//app"}, (["//app"], False)),
        # '-r', and the '...' suffix that says the same.
        ({"package": "//app", "recursive": True}, (["//app"], True)),
        ({"package": "//app..."}, (["//app"], True)),
        # An object that names its own package - from the CLI, and the editor.
        ({"package": "//app", "object": "//lib:bolt"}, (["//lib"], False)),
        ({"package": "//app", "name": "//lib:bolt"}, (["//lib"], False)),
        # ...and one that does not.
        ({"package": "//app", "object": "bolt"}, (["//app"], False)),
    ],
)
def test_the_packages_checked_are_the_ones_the_request_is_about(tmp_path, params, expected):
    session, _ = make_session()
    context_id = create_context(session, tmp_path)

    operations._ctx(session, {"context": context_id, **params})

    assert session.contexts[context_id].reload_targets == expected


def test_a_configuration_that_no_longer_parses_is_reported_as_one(tmp_path):
    """As 'context.create' reports it, rather than as an internal error."""
    import yaml

    session, _ = make_session()
    context_id = create_context(session, tmp_path)

    def unparseable(packages=None, recursive=False):
        yaml.safe_load("parts: [\n")

    session.contexts[context_id].reload_changed_packages = unparseable

    with pytest.raises(JsonRpcError) as raised:
        operations._ctx(session, {"context": context_id})
    assert raised.value.code == operations.INVALID_CONFIG
    # Kept: its next request loads the root again.
    assert context_id in session.contexts


def test_an_operation_on_the_session_context_reloads_its_changed_packages_first(tmp_path):
    """The VS Code extension's path: no context id, the session's default."""
    session, _ = make_session()
    session.partcad_ctx = FakeContext(str(tmp_path), session.partcad.user_config)

    assert operations._ctx(session, {}) is session.partcad_ctx
    assert session.partcad_ctx.reloads == 1


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


# ---- warm state: neither install nor update may leave anything forced --------


@pytest.mark.parametrize("initial", [False, True], ids=["off", "on"])
def test_install_fetches_what_the_pins_name_and_forces_nothing(tmp_path, initial):
    """``pc install`` used to force a refresh of every import, and once left it on.

    Downloading a dependency is an install; moving one is ``pc update``, which
    writes the new pin into ``partcad.yaml``. So an install runs under whatever
    the user configured, and refreshes nothing on its own.
    """
    session, _ = make_session(FakeUserConfig(force_update=initial))
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    operations.install(session, {"context": context_id})

    assert ctx.force_update_during_fetch is initial
    assert ctx.refresh_during_fetch is False
    assert ctx.user_config.force_update is initial


@pytest.mark.parametrize("initial", [False, True], ids=["off", "on"])
def test_update_refreshes_its_own_context_and_leaves_the_configuration_alone(tmp_path, initial):
    """The refresh is the context's, so it cannot leak through the shared configuration."""
    session, _ = make_session(FakeUserConfig(force_update=initial))
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    operations.update(session, {"context": context_id})

    assert ctx.full_reloads == 1  # what the warm context had loaded is read again
    assert ctx.refresh_during_fetch is True  # the fetch really was a refresh
    assert ctx.refresh_imports is False  # ...for this one call
    assert ctx.user_config.force_update is initial


def test_the_refresh_ends_even_when_the_fetch_fails(tmp_path):
    """A failed fetch is the likeliest way to leave a context refreshing for good."""
    session, _ = make_session(FakeUserConfig(force_update=False))
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]
    ctx.fail_with = RuntimeError("network is down")

    with pytest.raises(RuntimeError):
        operations.update(session, {"context": context_id})

    assert ctx.refresh_imports is False
    assert ctx.user_config.force_update is False


def test_updating_one_workspace_does_not_refresh_another(tmp_path):
    session, _ = make_session(FakeUserConfig(force_update=False))
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = create_context(session, first_dir)
    second = create_context(session, second_dir)

    operations.update(session, {"context": first})

    session.contexts[second].get_all_packages()
    assert session.contexts[second].refresh_during_fetch is False
    assert session.contexts[second].force_update_during_fetch is False


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


# ---- install: which packages get their objects prepared ----------------------


def test_install_prepares_the_objects_of_the_current_package(tmp_path):
    """The second half of an install: every object of the package is prepared."""
    session, _ = make_session()
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    operations.install(session, {"context": context_id})

    assert session.partcad.actions.package.calls == [(ctx, ["//"])]


def test_install_prepares_only_the_named_package(tmp_path):
    session, _ = make_session()
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]

    operations.install(session, {"context": context_id, "package": "//sub"})

    assert session.partcad.actions.package.calls == [(ctx, ["//sub"])]


def test_install_prepares_the_whole_subtree_when_recursive(tmp_path):
    """'-r' widens the object pass to the imported packages, not the fetch:
    the fetch is always the entire tree."""
    session, _ = make_session()
    context_id = create_context(session, tmp_path)
    ctx = session.contexts[context_id]
    ctx.packages = ["//", "//sub", "//sub/deeper"]

    operations.install(session, {"context": context_id, "recursive": True})

    assert session.partcad.actions.package.calls == [(ctx, ["//", "//sub", "//sub/deeper"])]


def test_install_reports_the_objects_it_could_not_prepare(tmp_path):
    """The count comes back so the CLI can exit non-zero on a partial install."""
    session, seen = make_session()
    context_id = create_context(session, tmp_path)
    session.partcad.actions.package.stats = {
        "sketch": 1,
        "part": 2,
        "assembly": 0,
        "software": 0,
        "failed": 3,
        "failed_packages": 0,
    }

    result = operations.install(session, {"context": context_id})

    assert result["failed"] == 3
    assert ("error", "Failed to install 3 objects") in seen


def test_install_of_an_unknown_package_is_a_usage_error(tmp_path):
    """Naming a package that is not there must not report a clean install."""
    session, _ = make_session()
    context_id = create_context(session, tmp_path)
    session.contexts[context_id].project = None

    with pytest.raises(JsonRpcError) as excinfo:
        operations.install(session, {"context": context_id, "package": "//nope"})

    assert excinfo.value.code == operations.USAGE_ERROR
    assert session.partcad.actions.package.calls == []


def test_update_reports_the_number_of_packages_it_refreshed(tmp_path):
    session, seen = make_session()
    context_id = create_context(session, tmp_path)
    session.contexts[context_id].packages = ["//", "//sub", "//sub/deeper"]

    assert operations.update(session, {"context": context_id}) == {"pinned": 0, "current": 0, "failed": 0, "count": 3}
    assert ("info", "Successfully updated 3 packages") in seen


def test_update_reports_the_pins_it_moved_and_the_ones_it_could_not(tmp_path):
    session, seen = make_session()
    context_id = create_context(session, tmp_path)
    session.partcad.actions.package.update_stats = {"pinned": 2, "current": 1, "failed": 1}

    operations.update(session, {"context": context_id})

    assert ("info", "Pinned 2 tracked dependencies to the tip of their branch, 1 were there already") in seen
    assert ("error", "Failed to update 1 tracked dependencies") in seen


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


def test_daemon_reset_drops_every_warm_context(tmp_path):
    """The reset deletes the directories the contexts point into; none may survive."""
    session, _ = make_session(FakeUserConfig(internal_state_dir=str(tmp_path / "state")))
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    create_context(session, first_dir)
    create_context(session, second_dir)

    operations.daemon_reset(session, {})

    assert session.contexts == {}
    assert session.partcad_ctx is None


# ---- context.create: whose user configuration the context is built from ------
#
# The daemon's own configuration was resolved from the environment that happened
# to start it, and it then stays warm for every later command -- so it says
# nothing about how the command being served was invoked. A client that knows
# its own configuration sends a copy, and the context is built from that.


def create_with_config(session, path, **options):
    """The handshake a configured client performs before every command."""
    return operations.context_create(session, {"url": workspace_url(path), "userConfig": dict(options)})


def test_the_context_is_built_from_the_caller_s_configuration(tmp_path):
    session, _ = make_session(FakeUserConfig(devel_index=False, force_update=False))

    create_with_config(session, tmp_path, develIndex=True, forceUpdate=True)

    built = session.partcad.contexts_built[0]
    assert built.user_config is not session.partcad.user_config
    assert built.user_config.devel_index is True
    assert built.user_config.force_update is True


def test_the_daemon_s_own_configuration_is_ignored_when_one_is_sent(tmp_path):
    """The daemon says the opposite of the caller; the caller has to win."""
    session, _ = make_session(FakeUserConfig(devel_index=True, force_update=True))

    create_with_config(session, tmp_path, develIndex=False, forceUpdate=False)

    assert session.partcad.contexts_built[0].user_config.devel_index is False
    # ...and the daemon's own is left exactly as it was, not mutated in passing.
    assert session.partcad.user_config.devel_index is True


def test_the_whole_configuration_travels_not_just_the_options_read_here(tmp_path):
    """Whatever the client resolved reaches the context, credentials included."""
    session, _ = make_session()

    create_with_config(session, tmp_path, **{"git.auth": {"github.com": {"username": "alice"}}})

    settings = session.partcad.contexts_built[0].user_config.settings
    assert settings["git.auth"] == {"github.com": {"username": "alice"}}


def test_a_context_built_from_another_configuration_is_rebuilt(tmp_path):
    """A warm context resolved its package graph against the other config."""
    session, _ = make_session()
    first = create_with_config(session, tmp_path, develIndex=False)

    second = create_with_config(session, tmp_path, develIndex=True)

    assert first["context"] == second["context"]  # same workspace, same id
    assert len(session.partcad.contexts_built) == 2  # rebuilt, not reused
    assert session.contexts[second["context"]] is session.partcad.contexts_built[1]
    assert session.contexts[second["context"]].user_config.devel_index is True


def test_the_same_configuration_still_reuses_the_warm_context(tmp_path):
    """Every command sends one, so an unchanged one must cost nothing."""
    session, _ = make_session()
    create_with_config(session, tmp_path, develIndex=True, forceUpdate=False)

    create_with_config(session, tmp_path, develIndex=True, forceUpdate=False)

    assert len(session.partcad.contexts_built) == 1


def test_switching_back_reuses_nothing_stale(tmp_path):
    """Off, on, off again: the last one must not be served the middle graph."""
    session, _ = make_session()
    create_with_config(session, tmp_path, develIndex=False)
    create_with_config(session, tmp_path, develIndex=True)

    create_with_config(session, tmp_path, develIndex=False)

    assert len(session.partcad.contexts_built) == 3
    assert session.partcad.contexts_built[-1].user_config.devel_index is False


def test_a_client_that_sends_no_configuration_gets_the_daemon_s_own(tmp_path):
    """The VS Code extension configures the daemon once, at launch."""
    own = FakeUserConfig(devel_index=True)
    session, _ = make_session(own)

    operations.context_create(session, {"url": workspace_url(tmp_path)})

    assert session.partcad.contexts_built[0].user_config is own
    # And it stays reusable rather than rebuilding on every call.
    operations.context_create(session, {"url": workspace_url(tmp_path)})
    assert len(session.partcad.contexts_built) == 1


def test_the_sandbox_slots_are_sized_for_the_caller_before_the_context_is_built(tmp_path):
    """PC_THREADS_MAX on a daemon started without it: the slots are the process's,
    sized once at import from the daemon's own configuration, and a client's
    'threadsMax' used to stop at the context."""
    session, _ = make_session()
    built_before = []
    follow = session.partcad.sandbox_lock.follow

    def follow_noting_what_was_built(config):
        built_before.append(len(session.partcad.contexts_built))
        follow(config)

    session.partcad.sandbox_lock.follow = follow_noting_what_was_built

    create_with_config(session, tmp_path, threadsMax=6)

    followed = session.partcad.sandbox_lock.followed
    assert followed[0].settings == {"threadsMax": 6}
    assert followed[0] is session.partcad.contexts_built[0].user_config
    assert built_before[0] == 0


def test_each_operation_sizes_the_slots_for_its_own_context_again(tmp_path):
    """Requests are served one at a time, and another client's may have run in
    between: the slots are left at whatever that one asked for."""
    session, _ = make_session()
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    six = create_with_config(session, first_dir, threadsMax=6)["context"]
    create_with_config(session, second_dir, threadsMax=8)

    operations._ctx(session, {"context": six})

    assert session.partcad.sandbox_lock.followed[-1] is session.contexts[six].user_config


def test_a_client_that_sends_no_configuration_gets_the_daemon_s_own_slots(tmp_path):
    """The VS Code extension: the daemon's own 'threadsMax', not the last CLI's."""
    own = FakeUserConfig()
    session, _ = make_session(own)
    operations.context_create(session, {"url": workspace_url(tmp_path)})

    operations._ctx(session, {})

    assert session.partcad.sandbox_lock.followed[-1] is own


def test_two_workspaces_keep_their_own_configurations(tmp_path):
    """The fingerprint is per context, not one global 'last config seen'."""
    session, _ = make_session()
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()

    a = create_with_config(session, first_dir, develIndex=True)
    b = create_with_config(session, second_dir, develIndex=False)

    assert session.contexts[a["context"]].user_config.devel_index is True
    assert session.contexts[b["context"]].user_config.devel_index is False
    # Revisiting the first with its own configuration reuses it.
    create_with_config(session, first_dir, develIndex=True)
    assert len(session.partcad.contexts_built) == 2


def test_evicting_a_context_forgets_the_configuration_it_was_built_from(tmp_path):
    """A mutation drops the context; its configuration must not outlive it."""
    session, _ = make_session()
    context_id = create_with_config(session, tmp_path, develIndex=True)["context"]

    operations._invalidate_context(session, {"context": context_id})

    assert context_id not in session.context_user_configs


def test_a_daemon_reset_forgets_every_configuration(tmp_path):
    session, _ = make_session(FakeUserConfig(internal_state_dir=str(tmp_path / "state")))
    create_with_config(session, tmp_path, develIndex=True)

    operations.daemon_reset(session, {})

    assert session.context_user_configs == {}
