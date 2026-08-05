#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the shared operations core.

These lock in two contracts: the event contract the VS Code extension depends
on, and the user-visible output of the report-style operations that back the
``pc`` commands (message wording, Process labels, totals). The heavy ``partcad``
context is replaced by a faithful fake so the operation glue (param extraction,
event emission, formatting) is exercised without a real CAD environment.
"""

import contextlib
import sys
import types

import pytest
from partcad_service_json_rpc.core import events, operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session

# ---- fakes -----------------------------------------------------------------


class RecordingLogging:
    """Stand-in for ``partcad.logging`` that remembers what was reported.

    PartCAD's level functions forward to a ``logging.Logger``, so a caller may
    pass either a preformatted string (``info("x %s" % v)``) or a lazy template
    plus args (``info("x %s", v)``). Both have to be recorded as the same final
    line: that line is what the user, and the behave suite, actually see.
    """

    def __init__(self):
        self.records = []  # (level, formatted message), in order
        self.processes = []  # (op, package) of every Process entered
        self.actions = []  # (op, package) of every Action entered

    def _record(self, level, msg, args):
        self.records.append((level, str(msg) % args if args else str(msg)))

    def debug(self, msg, *args, **kwargs):
        self._record("debug", msg, args)

    def info(self, msg, *args, **kwargs):
        self._record("info", msg, args)

    def warning(self, msg, *args, **kwargs):
        self._record("warning", msg, args)

    def error(self, msg, *args, **kwargs):
        self._record("error", msg, args)

    def exception(self, msg, *args, **kwargs):
        self._record("exception", msg, args)

    @contextlib.contextmanager
    def Process(self, op, package, item=None):
        self.processes.append((op, package))
        yield

    @contextlib.contextmanager
    def Action(self, op, package, item=None):
        self.actions.append((op, package))
        yield

    def messages(self, level=None):
        return [message for lvl, message in self.records if level is None or lvl == level]

    def only(self, level="info"):
        """The single message reported at ``level`` (the list operations emit one)."""
        messages = self.messages(level)
        assert len(messages) == 1, messages
        return messages[0]


class FakeUserConfig:
    def __init__(self, internal_state_dir="/nonexistent"):
        self.internal_state_dir = internal_state_dir
        self.force_update = False
        self.threads_max = 1


class FakeUtils:
    """The subset of ``partcad.utils`` the operations reach for.

    Reimplemented rather than imported so the tests stay off the heavy package.
    It covers the plain ``name`` and ``//pkg:name`` forms; globs and the
    deprecated single-slash root are out of scope here.
    """

    @staticmethod
    def resolve_resource_path(current_project_name, pattern):
        if ":" not in pattern:
            pattern = ":" + pattern
        project_pattern, item_pattern = pattern.split(":")
        if project_pattern == "":
            project_pattern = current_project_name
        elif not project_pattern.startswith("//"):
            separator = "" if current_project_name.endswith("/") else "/"
            project_pattern = current_project_name + separator + project_pattern
        return project_pattern, item_pattern


class FakePartcad:
    __version__ = "0.7.155"

    def __init__(self):
        self.logging = RecordingLogging()
        self.user_config = FakeUserConfig()
        self.utils = FakeUtils()


class FakeShape:
    def __init__(self):
        self.shown = False

    def show(self):
        self.shown = True

    def render(self, ctx, export_type, filepath=None):
        self.rendered = (export_type, filepath)


class FakeObject:
    """A part, sketch, assembly or interface as the report operations see it."""

    def __init__(self, name, desc=None, project_name=None, project=None, config=None, info=None):
        self.name = name
        self.desc = desc
        self.config = config if config is not None else ({"desc": desc} if desc else {})
        self._info = dict(info or {})
        # Interfaces carry their package as an object (`.project`) and have no
        # `.project_name` at all; the other shapes carry the flat name. Set only
        # what the corresponding real class sets, so a lookup of the wrong one
        # fails here the way it fails in production.
        if project is not None:
            self.project = project
        if project_name is not None:
            self.project_name = project_name

    def matches(self, keyword):
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in str(self.config).lower() or keyword in self.name.lower()

    def info(self):
        return dict(self._info)


class FakeProject:
    def __init__(self, name="//", path="pkgdir", desc=None, url=None, config_obj=None, broken=False):
        self.name = name
        self.path = path
        self.desc = desc
        self.broken = broken
        self.config_obj = dict(config_obj or {})
        if url is not None:
            # Only imported packages have a `url` attribute; `list packages`
            # branches on `hasattr(project, "url")`.
            self.url = url
            self.config_obj.setdefault("url", url)
        self.parts = {}
        self.sketches = {}
        self.assemblies = {}
        self.interfaces = {}
        self.providers = {}

    def add(self, kind, obj):
        getattr(self, kind)[obj.name] = obj
        return self

    def object_count(self):
        return len(self.sketches) + len(self.parts) + len(self.assemblies)

    def matches(self, keyword):
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in str(self.config_obj).lower() or keyword in self.name.lower()

    def info(self):
        info = {"Path": self.name}
        if self.config_obj.get("url") is not None:
            info["Url"] = self.config_obj["url"]
        if self.config_obj.get("importUrl") is not None:
            info["ImportUrl"] = self.config_obj["importUrl"]
        if self.desc:
            info["Desc"] = self.desc
        return info


class FakeContext:
    def __init__(self, name="//"):
        self.name = name
        self.current_project_path = name
        self.config_path = "/abs/partcad.yaml"
        self.requested = []
        self.mates = {}
        self.stats_git_ops = 0
        self.user_config = FakeUserConfig()
        self.projects = {name: FakeProject(name=name)}
        # Instantiated objects, keyed by (kind, "package:name") as the context
        # is asked for them.
        self.shapes = {}
        # Stats attributes read by the info/getStats operation.
        for name in (
            "stats_packages",
            "stats_packages_instantiated",
            "stats_sketches",
            "stats_sketches_instantiated",
            "stats_interfaces",
            "stats_interfaces_instantiated",
            "stats_parts",
            "stats_parts_instantiated",
            "stats_assemblies",
            "stats_assemblies_instantiated",
            "stats_memory",
        ):
            setattr(self, name, 0)

    def stats_recalc(self):
        self.stats_packages = 3

    def _get_shape(self, kind, path, params=None):
        self.requested.append((kind, path, params))
        return self.shapes.get((kind, path))

    def get_part(self, path, params=None):
        return self._get_shape("part", path, params)

    def get_sketch(self, path, params=None):
        return self._get_shape("sketch", path, params)

    def get_assembly(self, path, params=None):
        return self._get_shape("assembly", path, params)

    def get_interface(self, path):
        return self._get_shape("interface", path)

    def get_project(self, name):
        return self.projects.get(name)

    def get_current_project_path(self):
        return self.current_project_path

    def resolve_package_path(self, package):
        """Mirrors ``Context.resolve_package_path`` for the non-glob forms."""
        if package is None:
            return self.get_current_project_path()
        while len(package) > 1 and package != "//" and package.endswith("/"):
            package = package[:-1]
        if package in ("/", "//"):
            return self.name
        if package in ("", "."):
            return self.get_current_project_path()
        if not package.startswith("/"):
            package = self.get_current_project_path() + "/" + package
        return package

    def get_all_packages(self, parent_name=None, has_stuff=True):
        projects = list(self.projects.values())
        if parent_name is not None:
            projects = [p for p in projects if p.name.startswith(parent_name)]
        if has_stuff:
            # As in Context.get_packages(): packages with no sketch, part or
            # assembly are dropped -- which is why `list interfaces` asks for
            # has_stuff=False.
            projects = [p for p in projects if p.object_count() > 0]
        return [{"name": p.name, "desc": p.desc} for p in projects]


def make_session():
    seen = []
    session = Session(EventEmitter(lambda e, p: seen.append((e, p))))
    session.partcad = FakePartcad()
    session.partcad_ctx = FakeContext()
    return session, seen


def install_fake_partcad_modules(monkeypatch, modules):
    """Register fake ``partcad.*`` modules for the operations' lazy imports.

    Operations import their PartCAD dependencies inside the function body, so
    pre-seeding ``sys.modules`` keeps the real (CAD-heavy) package out of the
    test run. The ancestor packages are seeded too: ``import partcad.a.b as x``
    resolves the root through ``sys.modules`` and would otherwise import the
    real ``partcad``.
    """
    created = {}

    def ensure(name):
        module = created.get(name)
        if module is not None:
            return module
        module = types.ModuleType(name)
        module.__path__ = []  # marks it a package, so `from x.y import z` works
        created[name] = module
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name:
            parent_name, _, child = name.rpartition(".")
            setattr(ensure(parent_name), child, module)
        return module

    for name, attributes in modules.items():
        module = ensure(name)
        for key, value in attributes.items():
            setattr(module, key, value)
    return created


def lines_of(message):
    return message.rstrip("\n").split("\n")


def row_for(message, name):
    """The single output row mentioning ``name``."""
    rows = [line for line in lines_of(message) if name in line]
    assert len(rows) == 1, rows
    return rows[0]


# ---- events and stats ------------------------------------------------------


def test_bind_log_stream_exposes_the_external_write_stream():
    import io

    session = Session()
    stream = io.StringIO()
    session.bind_log_stream(stream)
    assert session.log_write_stream is stream


def test_inspect_part_shows_the_part_and_signals_done():
    session, seen = make_session()
    part = FakeShape()
    session.partcad_ctx.shapes[("part", "//:foo")] = part
    operations.inspect_part(session, {"package": "//", "name": "foo"})
    assert ("part", "//:foo", None) in session.partcad_ctx.requested
    assert part.shown is True
    assert seen[-1] == (events.SHOW_PART_DONE, None)


def test_inspect_part_without_context_is_a_silent_noop():
    seen = []
    session = Session(EventEmitter(lambda e, p: seen.append((e, p))))
    session.partcad_ctx = None
    assert operations.inspect_part(session, {"package": "//", "name": "foo"}) is None
    assert seen == []


@pytest.mark.parametrize(
    "operation, params",
    [
        (operations.list_objects, {"kind": "parts"}),
        (operations.list_packages, {}),
        (operations.list_providers, {}),
        (operations.list_mates, {}),
        (operations.search_objects, {"kind": "parts"}),
        (operations.info_object, {}),
        (operations.render_objects, {}),
        (operations.convert_object, {"object_name": "widget"}),
        (operations.test_run, {}),
        (operations.lint_run, {}),
    ],
)
def test_context_aware_operations_are_silent_noops_without_a_context(operation, params):
    # The VS Code extension calls these before a package is loaded; they have to
    # report nothing rather than fail, exactly as the legacy LSP server did.
    session, seen = make_session()
    session.partcad_ctx = None
    assert operation(session, params) is None
    assert session.partcad.logging.records == []
    assert seen == []


def test_info_emits_stats_with_version_and_recalculated_counts():
    session, seen = make_session()
    operations.info(session, {})
    event, payload = seen[-1]
    assert event == events.STATS
    assert payload["version"] == "0.7.155"
    assert payload["stats"]["packages"] == 3
    assert payload["stats"]["path"] == "/abs/partcad.yaml"


def test_package_path_emits_execute_with_the_callback(tmp_path):
    session, seen = make_session()
    session.partcad_ctx.projects["//sub"] = FakeProject(name="//sub", path=str(tmp_path))
    operations.package_path(session, {"package": "//sub", "callback": "partcad.addPart2"})
    event, payload = seen[-1]
    assert event == events.EXECUTE
    assert payload["command"] == "partcad.addPart2"
    assert payload["args"][0]["packageName"] == "//sub"
    assert payload["args"][0]["isAbsolute"] is True


def test_export_part_renders_to_filepath_and_signals_export_done():
    session, seen = make_session()
    part = FakeShape()
    session.partcad_ctx.shapes[("part", "//:foo")] = part
    operations.export_part(
        session,
        {"type": "stl", "path": "/tmp/out.stl", "package": "//", "name": "foo"},
    )
    assert part.rendered == ("stl", "/tmp/out.stl")
    assert seen[-1] == (events.EXPORT_PART_DONE, None)


# ---- search ----------------------------------------------------------------


def fake_search(select):
    """Build a stand-in for the ``partcad.actions.*.search_*`` functions.

    Mirrors ``partcad.actions.common._search``: keyword-filter the selected
    objects of the package, and of its children when recursive.
    """

    def search(ctx, package, recursive, keyword):
        names = [package]
        if recursive:
            # `_search` seeds the list with the package itself and then appends
            # get_all_packages(parent_name=package), which reports that package
            # again; mirrored here rather than deduplicated so the fake matches.
            names += [p["name"] for p in ctx.get_all_packages(parent_name=package)]
        found = []
        for name in names:
            project = ctx.projects.get(name)
            if project is None:
                continue
            found += [obj for obj in select(project) if not keyword or obj.matches(keyword)]
        return found

    return search


def install_fake_search(monkeypatch):
    install_fake_partcad_modules(
        monkeypatch,
        {
            "partcad.actions.shape": {
                "search_parts": fake_search(lambda p: p.parts.values()),
                "search_sketches": fake_search(lambda p: p.sketches.values()),
                "search_assemblies": fake_search(lambda p: p.assemblies.values()),
                "search_interfaces": fake_search(lambda p: p.interfaces.values()),
            },
            "partcad.actions.package": {"search_packages": fake_search(lambda p: [p])},
        },
    )


@pytest.mark.parametrize(
    "kind, process_label",
    [
        ("parts", "Search Parts"),
        ("sketches", "Search Sketches"),
        ("assemblies", "Search Assemblies"),
        ("interfaces", "Search Interfaces"),
    ],
)
def test_search_objects_reports_a_match_per_kind(monkeypatch, kind, process_label):
    install_fake_search(monkeypatch)
    session, _ = make_session()
    ctx = session.partcad_ctx
    root = ctx.projects["//"]
    # An interface knows its package as an object; the other shapes know it as a
    # flat name. Only the matching attribute is set, so the wrong one would
    # raise AttributeError here exactly as it did in production.
    if kind == "interfaces":
        obj = FakeObject("widget", desc="a cube widget", project=root)
    else:
        obj = FakeObject("widget", desc="a cube widget", project_name="//")
    root.add(kind, obj)

    operations.search_objects(session, {"kind": kind, "keyword": "cube", "package": "//"})

    log = session.partcad.logging
    assert log.processes == [(process_label, "//")]
    output = lines_of(log.only("info"))
    assert output[0] == "PartCAD %s with 'cube' keyword:" % kind
    assert output[1].startswith("\t// widget")
    assert output[1].endswith("a cube widget")
    assert output[-1] == "Matches: 1"


def test_search_packages_reports_the_package_with_its_url(monkeypatch):
    install_fake_search(monkeypatch)
    session, _ = make_session()
    session.partcad_ctx.projects["//"] = FakeProject(
        name="//",
        desc="a cube factory",
        url="https://example.com/cubes",
    )

    operations.search_objects(session, {"kind": "packages", "keyword": "cube", "package": "//"})

    log = session.partcad.logging
    assert log.processes == [("Search Packages", "//")]
    output = lines_of(log.only("info"))
    assert output[0] == "PartCAD packages with 'cube' keyword:"
    assert output[1].startswith("\t//")
    assert output[1].endswith("a cube factory")
    assert output[2].strip() == "https://example.com/cubes"
    assert output[-1] == "Matches: 1"


def test_search_objects_without_matches_reports_none(monkeypatch):
    install_fake_search(monkeypatch)
    session, _ = make_session()
    session.partcad_ctx.projects["//"].add("parts", FakeObject("widget", desc="a sphere"))

    operations.search_objects(session, {"kind": "parts", "keyword": "cube", "package": "//"})

    output = lines_of(session.partcad.logging.only("info"))
    assert output == ["PartCAD parts with 'cube' keyword:", "\t<none>"]


def test_search_objects_recursive_covers_child_packages(monkeypatch):
    install_fake_search(monkeypatch)
    session, _ = make_session()
    ctx = session.partcad_ctx
    for child in ("//pkg1", "//pkg2"):
        project = FakeProject(name=child)
        project.add("parts", FakeObject(child[2:] + "_part", desc="cube in " + child[2:], project_name=child))
        ctx.projects[child] = project

    operations.search_objects(session, {"kind": "parts", "keyword": "cube", "package": "//", "recursive": True})

    output = session.partcad.logging.only("info")
    assert row_for(output, "pkg1_part").startswith("\t//pkg1 pkg1_part")
    assert row_for(output, "pkg2_part").endswith("cube in pkg2")
    assert lines_of(output)[-1] == "Matches: 2"


# ---- ad-hoc conversion -----------------------------------------------------


class FakeConverter:
    """A ``convert_cad_file``/``convert_sketch_file`` stand-in."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, input_filename, input_type, output_filename, output_type):
        self.calls.append((input_filename, input_type, output_filename, output_type))
        if self.error is not None:
            raise self.error


def install_fake_convert(monkeypatch, part=None, sketch=None):
    part = part if part is not None else FakeConverter()
    sketch = sketch if sketch is not None else FakeConverter()
    install_fake_partcad_modules(
        monkeypatch,
        {
            "partcad.adhoc.convert": {"convert_cad_file": part, "convert_sketch_file": sketch},
            # Mirrors partcad.shape; the duplicate ".py"/".json" extensions are
            # what make suffix inference ambiguous, so keep the tables whole.
            "partcad.shape": {
                "PART_EXTENSION_MAPPING": {
                    "step": "step",
                    "brep": "brep",
                    "stl": "stl",
                    "3mf": "3mf",
                    "threejs": "json",
                    "obj": "obj",
                    "iges": "iges",
                    "gltf": "json",
                    "cadquery": "py",
                    "build123d": "py",
                    "sdf": "py",
                    "scad": "scad",
                },
                "SKETCH_EXTENSION_MAPPING": {
                    "svg": "svg",
                    "dxf": "dxf",
                    "cadquery": "py",
                    "build123d": "py",
                },
            },
        },
    )
    return part, sketch


@pytest.mark.parametrize(
    "kind, input_name, output_name, expected",
    [
        ("part", "model.unknown", "out.step", "Cannot infer input type. Please specify --input explicitly."),
        ("sketch", "draw.unknown", "out.dxf", "Cannot infer input sketch type. Please specify --input explicitly."),
        ("part", "model.step", "out.unknown", "Cannot infer output type. Please specify --output explicitly."),
        ("sketch", "draw.svg", "out.unknown", "Cannot infer output sketch type. Please specify --output explicitly."),
    ],
)
def test_adhoc_convert_reports_uninferrable_types(monkeypatch, tmp_path, kind, input_name, output_name, expected):
    part, sketch = install_fake_convert(monkeypatch)
    session, _ = make_session()

    operations.adhoc_convert(
        session,
        {
            "kind": kind,
            "input_filename": str(tmp_path / input_name),
            "output_filename": str(tmp_path / output_name),
        },
    )

    assert session.partcad.logging.messages("error") == [expected]
    assert part.calls == [] and sketch.calls == []


def test_adhoc_convert_sketch_converts_and_reports_progress(monkeypatch, tmp_path):
    part, sketch = install_fake_convert(monkeypatch)
    session, _ = make_session()
    source, target = tmp_path / "circle.svg", tmp_path / "circle.dxf"

    operations.adhoc_convert(
        session,
        {"kind": "sketch", "input_filename": str(source), "output_filename": str(target)},
    )

    assert sketch.calls == [(str(source), "svg", str(target), "dxf")]
    assert part.calls == []
    assert session.partcad.logging.messages("info") == [
        "Converting %s (svg) to %s (dxf)..." % (source, target),
        "Conversion complete: %s" % target,
    ]


def test_adhoc_convert_part_derives_the_output_path_from_the_output_type(monkeypatch, tmp_path):
    part, sketch = install_fake_convert(monkeypatch)
    session, _ = make_session()
    source = tmp_path / "model.step"

    operations.adhoc_convert(
        session,
        {"kind": "part", "input_filename": str(source), "output_filename": None, "output_type": "threejs"},
    )

    expected_output = tmp_path / "model.json"
    assert part.calls == [(str(source), "step", str(expected_output), "threejs")]
    assert sketch.calls == []
    assert session.partcad.logging.messages("info")[-1] == "Conversion complete: %s" % expected_output


def test_adhoc_convert_reports_a_failed_conversion(monkeypatch, tmp_path):
    install_fake_convert(monkeypatch, part=FakeConverter(error=RuntimeError("unsupported geometry")))
    session, _ = make_session()

    result = operations.adhoc_convert(
        session,
        {
            "kind": "part",
            "input_filename": str(tmp_path / "model.step"),
            "output_filename": str(tmp_path / "model.stl"),
        },
    )

    assert result is None
    log = session.partcad.logging
    assert log.messages("error") == ["Failed to convert: unsupported geometry"]
    assert not any(m.startswith("Conversion complete") for m in log.messages("info"))


# ---- system ----------------------------------------------------------------


def test_system_status_reports_version_and_sizes_in_megabytes(tmp_path):
    session, _ = make_session()
    session.partcad.user_config.internal_state_dir = str(tmp_path)
    (tmp_path / "git").mkdir()
    (tmp_path / "git" / "blob").write_bytes(b"\0" * 1048576)
    (tmp_path / "tar").mkdir()
    (tmp_path / "tar" / "blob").write_bytes(b"\0" * 524288)
    (tmp_path / "sandbox").mkdir()

    operations.system_status(session, {})

    log = session.partcad.logging
    assert log.messages("info") == [
        "PartCAD version: 0.7.155",
        "Internal data storage location: %s" % tmp_path,
        "Total internal data storage size: 1.50MB",
        "Git cache size: 1.00MB",
        "Tar cache size: 0.50MB",
        "Sandbox environments size: 0.00MB",
    ]
    assert log.processes == [("Status", "global")]
    assert log.actions == [
        ("Status", "total"),
        ("Status", "git"),
        ("Status", "tar"),
        ("Status", "sandbox"),
    ]


def test_system_status_reports_zero_sizes_before_anything_is_cached(tmp_path):
    session, _ = make_session()
    session.partcad.user_config.internal_state_dir = str(tmp_path / "never-created")

    operations.system_status(session, {})

    sizes = [m for m in session.partcad.logging.messages("info") if m.endswith("MB")]
    assert sizes == [
        "Total internal data storage size: 0.00MB",
        "Git cache size: 0.00MB",
        "Tar cache size: 0.00MB",
        "Sandbox environments size: 0.00MB",
    ]


class FakeSystemConfig:
    """In-memory stand-in for ``partcad.actions.config``."""

    def __init__(self, config=None):
        self.config = config if config is not None else {}
        self.yaml = object()  # opaque handle the operation only passes through
        self.saved = None

    def system_config_get(self):
        return self.yaml, self.config

    def system_config_set(self, yaml, config):
        self.saved = (yaml, config)


@pytest.mark.parametrize(
    "key, value, process_label, expected",
    [
        ("type", "none", "SysSetTelType", "Telemetry collection disabled"),
        ("type", "sentry", "SysSetTelType", "Telemetry collection enabled with Sentry"),
        ("env", "dev", "SysSetTelEnv", "Telemetry environment set to dev"),
        ("sentryDsn", "https://k@example.com/1", "SysSetTelDsn", "Sentry DSN set to https://k@example.com/1"),
    ],
)
def test_system_set_telemetry_confirms_the_change_and_persists_it(monkeypatch, key, value, process_label, expected):
    config_module = FakeSystemConfig()
    install_fake_partcad_modules(
        monkeypatch,
        {
            "partcad.actions.config": {
                "system_config_get": config_module.system_config_get,
                "system_config_set": config_module.system_config_set,
            }
        },
    )
    session, _ = make_session()

    operations.system_set_telemetry(session, {"key": key, "value": value})

    log = session.partcad.logging
    assert log.messages("info") == [expected]
    assert log.processes == [(process_label, "global")]
    assert config_module.saved == (config_module.yaml, {"telemetry": {key: value}})


def test_system_set_telemetry_keeps_the_other_telemetry_settings(monkeypatch):
    config_module = FakeSystemConfig({"telemetry": {"type": "sentry", "env": "prod"}})
    install_fake_partcad_modules(
        monkeypatch,
        {
            "partcad.actions.config": {
                "system_config_get": config_module.system_config_get,
                "system_config_set": config_module.system_config_set,
            }
        },
    )
    session, _ = make_session()

    operations.system_set_telemetry(session, {"key": "env", "value": "dev"})

    assert config_module.saved[1] == {"telemetry": {"type": "sentry", "env": "dev"}}


# ---- listing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, header, process_label",
    [
        ("parts", "PartCAD parts:", "ListParts"),
        ("sketches", "PartCAD sketches:", "ListSketches"),
        ("assemblies", "PartCAD assemblies:", "ListAssemblies"),
        ("interfaces", "PartCAD interfaces:", "ListInterfaces"),
    ],
)
def test_list_objects_reports_each_kind_with_its_header(kind, header, process_label):
    session, _ = make_session()
    session.partcad_ctx.projects["//"].add(kind, FakeObject("widget", desc="a cube"))

    operations.list_objects(session, {"kind": kind, "package": "//"})

    log = session.partcad.logging
    assert log.processes == [(process_label, "//")]
    output = lines_of(log.only("info"))
    assert output[0] == header
    assert output[1].startswith("\twidget")
    assert output[1].endswith("a cube")
    assert output[-1] == "Total: 1"


def test_list_objects_reports_none_for_an_empty_package():
    session, _ = make_session()

    operations.list_objects(session, {"kind": "parts", "package": "//"})

    output = lines_of(session.partcad.logging.only("info"))
    assert output == ["PartCAD parts:", "\t<none>"]


def test_list_objects_reports_a_missing_package_without_listing():
    session, _ = make_session()

    operations.list_objects(session, {"kind": "parts", "package": "//nope"})

    log = session.partcad.logging
    assert log.messages("error") == ["Package //nope is not found"]
    assert log.processes == []
    assert log.messages("info") == []


def test_list_objects_recursive_prefixes_rows_with_the_package():
    session, _ = make_session()
    child = FakeProject(name="//pkg1")
    child.add("parts", FakeObject("widget", desc="a cube"))
    session.partcad_ctx.projects["//pkg1"] = child

    operations.list_objects(session, {"kind": "parts", "package": "//", "recursive": True})

    output = session.partcad.logging.only("info")
    assert row_for(output, "widget").startswith("\t//pkg1")
    assert lines_of(output)[-1] == "Total: 1"


def test_list_interfaces_recursive_covers_packages_with_nothing_else_in_them():
    # `list interfaces` walks every package (has_stuff=False); a package that
    # declares interfaces but no part, sketch or assembly would be skipped
    # otherwise.
    session, _ = make_session()
    child = FakeProject(name="//pkg1")
    child.add("interfaces", FakeObject("m3", desc="3mm circular interface"))
    session.partcad_ctx.projects["//pkg1"] = child

    operations.list_objects(session, {"kind": "interfaces", "package": "//", "recursive": True})

    output = session.partcad.logging.only("info")
    assert row_for(output, "m3").startswith("\t//pkg1")
    assert lines_of(output)[-1] == "Total: 1"


def test_list_packages_reports_the_package_with_its_url():
    session, _ = make_session()
    session.partcad_ctx.projects["//"] = FakeProject(
        name="//",
        desc="Raspberry Pi",
        url="https://example.com/repo",
    )

    operations.list_packages(session, {"package": "//"})

    log = session.partcad.logging
    assert log.processes == [("ListPackages", "//")]
    output = lines_of(log.only("info"))
    assert output[0] == "PartCAD packages:"
    assert output[1].startswith("\t//")
    assert output[1].endswith("Raspberry Pi")
    assert output[2].strip() == "https://example.com/repo"


# ---- info ------------------------------------------------------------------


def test_info_object_without_an_object_reports_the_package():
    session, _ = make_session()
    session.partcad_ctx.projects["//"] = FakeProject(
        name="//",
        desc="Root package",
        url="https://example.com/repo",
    )

    operations.info_object(session, {"package": "//"})

    assert session.partcad.logging.messages("info") == [
        "INFO: Path: '//'",
        "INFO: Url: 'https://example.com/repo'",
        "INFO: Desc: 'Root package'",
    ]


def test_info_object_reports_a_missing_package():
    session, _ = make_session()

    operations.info_object(session, {"package": "//nope"})

    assert session.partcad.logging.messages("error") == ["Package //nope is not found"]


@pytest.mark.parametrize(
    "flag, kind",
    [
        (None, "part"),
        ("sketch", "sketch"),
        ("interface", "interface"),
        ("assembly", "assembly"),
    ],
)
def test_info_object_reports_the_object_of_the_requested_kind(flag, kind):
    session, _ = make_session()
    for candidate in ("part", "sketch", "interface", "assembly"):
        session.partcad_ctx.shapes[(candidate, "//:widget")] = FakeObject(
            "widget",
            config={"kind": candidate},
            info={"Kind": candidate},
        )
    params = {"object": "widget"}
    if flag is not None:
        params[flag] = True

    operations.info_object(session, params)

    assert session.partcad.logging.messages("info") == [
        "CONFIGURATION: {'kind': '%s'}" % kind,
        "INFO: Kind: '%s'" % kind,
    ]


def test_info_object_reports_a_missing_object():
    session, _ = make_session()

    operations.info_object(session, {"object": "missing"})

    assert session.partcad.logging.messages("error") == ["Object //:missing not found"]
