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
import copy
import os
import sys
import types

import pytest
from partcad_service_json_rpc.core import events, operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError

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


class FakeNeedsUpdateException(Exception):
    """Stand-in for ``partcad.exception.NeedsUpdateException``."""


class FakePartcad:
    __version__ = "0.7.158"

    def __init__(self):
        self.logging = RecordingLogging()
        self.user_config = FakeUserConfig()
        self.utils = FakeUtils()
        # A real 'partcad' exposes this, and the load operations catch through
        # it to tell "PartCAD is too old" apart from an ordinary failure.
        self.exception = types.SimpleNamespace(NeedsUpdateException=FakeNeedsUpdateException)


class FakeShape:
    def __init__(self):
        self.shown = False

    def show(self):
        self.shown = True

    def render(self, ctx, export_type, filepath=None):
        self.rendered = (export_type, filepath)


class FakeObject:
    """A part, sketch, assembly, interface or software as the report operations see it."""

    def __init__(self, name, desc=None, project_name=None, project=None, config=None, info=None, path=None):
        self.name = name
        self.desc = desc
        self.config = config if config is not None else ({"desc": desc} if desc else {})
        self._info = dict(info or {})
        # `Part`, `Sketch` and `Assembly` all declare `path` with a `None`
        # default, so the attribute is always readable; the factory fills it in
        # for file-backed objects. Note they do *not* carry `orig_name` as an
        # attribute - it only ever lands in `.config` - so the fake omits it too.
        self.path = path
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
        # A real Project knows the 'partcad.yaml' it was parsed from; the
        # Context does not, which is what '_root_config_path' exists for.
        self.config_path = "/abs/partcad.yaml"
        self.config_dir = path
        self.broken_objects = {}
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
        self.software = {}
        self.providers = {}
        self.children = []
        # The providers this package buys through, as `get_suppliers()` reports
        # them: empty on a package that declares none, which is the ordinary
        # case and the one the supply operation must not complain about.
        self.suppliers = {}
        # The assembly instruction books this package can produce, by assembly
        # name, and the refusal to produce one (an assembly with no steps).
        self.guides = {}
        self.guide_error = None
        self.guide_requests = []
        # A real package's parsed configuration carries its name, which is what
        # the client reads each row's label from.
        self.config_obj.setdefault("name", name)

    def get_child_project_names(self):
        return list(self.children)

    def get_suppliers(self):
        return dict(self.suppliers)

    async def assembly_guide_data_async(self, assembly_name, ignore_manufacturability=False):
        self.guide_requests.append((assembly_name, ignore_manufacturability))
        if self.guide_error is not None:
            raise self.guide_error
        return self.guides.get(assembly_name)

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
        self.requested = []
        self.mates = {}
        # What `ProviderCart.add_object()` puts in the cart, by object name: the
        # line items an object breaks down into.
        self.cart_contents = {}
        # The suppliers of each line item, by item name, and the providers they
        # name.
        self.item_suppliers = {}
        self.provider_plugins = {}
        self.stats_git_ops = 0
        self.user_config = FakeUserConfig()
        self.projects = {name: FakeProject(name=name)}
        # As on a real Context: the root package, and the only place the loaded
        # 'partcad.yaml' path can be read from.
        self.root = self.projects[name]
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

    async def find_part_suppliers(self, cart_item, cart=None):
        return list(self.item_suppliers.get(cart_item.name, []))

    def get_provider(self, name, params=None):
        return self.provider_plugins.get(name)

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
        (operations.assembly_guide, {"object": "top"}),
        (operations.supply_quote, {"object": "top"}),
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
    assert payload["version"] == "0.7.158"
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


# ---- inspect by path -------------------------------------------------------
#
# `inspect_file` backs the extension's save-triggered live reload: it finds the
# object a saved file defines, drops every cached instance of it so the client's
# follow-up inspect rebuilds it, and asks the client to inspect it. The cache
# keys are what `Project.get_object()` writes: the bare object name, or
# `"<name>;<param>=<value>,..."` for a parameterized instance.


def touch(path):
    path.write_text("")
    return str(path)


@pytest.mark.parametrize(
    "kind, extension, command",
    [
        ("assemblies", ".assy", "partcad.inspectAssembly"),
        ("parts", ".py", "partcad.inspectPart"),
        ("sketches", ".svg", "partcad.inspectSketch"),
    ],
)
def test_inspect_file_evicts_the_saved_object_with_its_parameterized_instances(tmp_path, kind, extension, command):
    session, seen = make_session()
    project = session.partcad_ctx.projects["//"]
    saved = touch(tmp_path / ("bracket" + extension))
    sibling = touch(tmp_path / ("bracket_v2" + extension))
    # The base object first: that is the order a package instantiates them in,
    # and the loops pick the first object whose file is the saved one.
    project.add(kind, FakeObject("bracket", path=saved))
    project.add(kind, FakeObject("bracket;size=10", path=saved))
    project.add(kind, FakeObject("bracket;size=20,thickness=2", path=saved))
    project.add(kind, FakeObject("bracket_v2", path=sibling))
    project.add(kind, FakeObject("bracket_mount", path=sibling))

    operations.inspect_file(session, {"path": saved})

    # The saved object and its parameterized instances are gone; the objects
    # that merely start with the same name are untouched (rebuilding them costs
    # a re-render each and nothing about them changed).
    assert sorted(getattr(project, kind)) == ["bracket_mount", "bracket_v2"]
    assert seen[-1] == (
        events.EXECUTE,
        {"command": command, "args": [{"name": "bracket", "pkg": "//"}, {}, True]},
    )


def test_inspect_file_invalidates_the_saved_sketch_before_evicting_it(tmp_path):
    # Sketches get their model invalidated in place as well, so that anything
    # still holding the instance (the viewer) does not keep the stale geometry.
    session, seen = make_session()
    project = session.partcad_ctx.projects["//"]
    saved = touch(tmp_path / "outline.svg")
    outline = FakeObject("outline", path=saved)
    outline.shape, outline.components = object(), ["stale"]
    project.add("sketches", outline)
    project.add("sketches", FakeObject("outline;width=5", path=saved))

    operations.inspect_file(session, {"path": saved})

    assert outline.shape is None
    assert outline.components == []
    assert project.sketches == {}
    assert seen[-1][1]["command"] == "partcad.inspectSketch"


def test_inspect_file_without_a_matching_file_changes_nothing(tmp_path):
    session, seen = make_session()
    project = session.partcad_ctx.projects["//"]
    project.add("parts", FakeObject("bracket", path=touch(tmp_path / "bracket.py")))

    operations.inspect_file(session, {"path": touch(tmp_path / "elsewhere.py")})

    assert sorted(project.parts) == ["bracket"]
    assert seen == []


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


# ---- package loading -------------------------------------------------------
#
# The operations that answer "which package is loaded, and what is in it". They
# had no coverage at all, which is how the extension shipped unable to load any
# package: they read `Context.config_path` and `Context.broken`, neither of
# which a Context has -- both belong to the root Project.


def test_package_load_reports_the_root_packages_config_path():
    session, seen = make_session()
    session.partcad.init = lambda path: session.partcad_ctx

    operations.package_load(session, {"path": "/abs"})

    loaded = [payload for event, payload in seen if event == events.PACKAGE_LOADED]
    assert loaded == [{"configPath": "/abs/partcad.yaml", "root": "//"}]
    assert events.PACKAGE_LOAD_FAILED not in [event for event, _ in seen]


def test_package_load_says_why_when_the_root_package_is_missing():
    session, seen = make_session()
    session.partcad.init = lambda path: session.partcad_ctx
    # A context whose root never loaded, which is the real "no package here".
    session.partcad_ctx.root = None

    operations.package_load(session, {"path": "/abs"})

    assert events.PACKAGE_LOAD_FAILED in [event for event, _ in seen]
    # ...and the reason is reported rather than swallowed, which is what left
    # the user with a bare "No PartCAD package is detected".
    errors = [payload for event, payload in seen if event == events.ERROR]
    assert len(errors) == 1
    assert "Failed to load package" in errors[0]


def test_load_package_contents_lists_objects_that_could_not_be_created():
    session, seen = make_session()
    project = session.partcad_ctx.projects["//"]
    project.broken_objects = {"part": {"tier01": "unknown part type 'ai-cadquery'"}}

    operations._load_package_contents(session, "//")

    (items,) = [payload for event, payload in seen if event == events.ITEMS]
    assert items["broken"] == [{"kind": "part", "name": "tier01", "reason": "unknown part type 'ai-cadquery'"}]
    # The user is told to go look, since the package otherwise appears empty.
    warnings = [payload for event, payload in seen if event == events.WARNING]
    assert any("could not be loaded" in w for w in warnings)


def test_load_package_contents_lists_the_packages_software():
    session, seen = make_session()
    project = session.partcad_ctx.projects["//"]
    project.add(
        "software",
        FakeObject("firmware", config={"name": "firmware", "type": "raw", "fileHash": "sha256:abc"}, path="fw.bin"),
    )

    operations._load_package_contents(session, "//")

    (items,) = [payload for event, payload in seen if event == events.ITEMS]
    # Reported beside the geometry, because software is part of what the package
    # ships and the client has no other way to find out that it is there.
    assert items["software"] == [
        {
            "name": "firmware",
            "type": "raw",
            "fileHash": "sha256:abc",
            "item_path": os.path.join(project.config_dir, "fw.bin"),
        }
    ]


def test_load_package_contents_skips_a_child_package_it_cannot_read():
    session, seen = make_session()
    project = session.partcad_ctx.projects["//"]
    project.children = ["//good", "//missing"]
    session.partcad_ctx.projects["//good"] = FakeProject(name="//good")
    # '//missing' resolves to None, as it does for a package that failed to load.

    operations._load_package_contents(session, "//")

    (items,) = [payload for event, payload in seen if event == events.ITEMS]
    assert [p["name"] for p in items["packages"]] == ["//good"]
    warnings = [payload for event, payload in seen if event == events.WARNING]
    assert any("//missing" in w for w in warnings)


# ---- the viewer's tabs -----------------------------------------------------
#
# What the PartCAD Viewer's panel shows beside the geometry: the assembly
# instruction book, and where to buy what an object is made of.


class FakeDocumentError(Exception):
    """Stand-in for ``partcad.exception.AssemblyDocumentError``."""


class FakeCartItem:
    """Stand-in for ``partcad.plugin_provider_data_cart.ProviderCartItem``."""

    def __init__(self, name, count=1, vendor=None, sku=None, count_per_sku=1):
        self.name = name
        self.count = count
        self.vendor = vendor
        self.sku = sku
        self.count_per_sku = count_per_sku


class FakeCart:
    """Stand-in for ``partcad.plugin_provider_data_cart.ProviderCart``.

    ``add_object()`` is what decides the line items -- an assembly becomes the
    things it is made of, a part is one thing -- and the context says which,
    raising for an object it does not know exactly as the real cart does.
    """

    def __init__(self, qos=None):
        self.qos = qos
        self.parts = {}

    async def add_object(self, ctx, name, recursive=False):
        self.recursive = recursive
        if name not in ctx.cart_contents:
            raise Exception("Part or assembly '%s' not found" % name)
        for item in ctx.cart_contents[name]:
            self.parts[item.name] = item

    def add_item(self, item, count=1):
        copied = copy.deepcopy(item)
        self.parts[copied.name] = copied
        return copied


class FakeQuoteRequest:
    """Stand-in for ``partcad.plugin_request_provider_quote.ProviderRequestQuote``."""

    def __init__(self, cart):
        self.cart = cart
        self.result = None

    def set_result(self, result):
        self.result = result


class FakeProvider:
    def __init__(self, name, price=None, currency=None, url=None, desc=None, error=None):
        self.name = name
        self.desc = desc
        self.url = url
        self.config = {"parameters": {"currency": {"default": currency}}} if currency else {}
        self.price = price
        self.error = error
        self.quoted = []

    async def load(self, cart_item):
        pass

    async def query_quote(self, request):
        if self.error is not None:
            raise Exception(self.error)
        # One cart per line item is what makes a per-part price possible at all.
        self.quoted.append(sorted(request.cart.parts.keys()))
        return {"price": self.price, "cartId": "cart-" + self.name, "qos": request.cart.qos}


def install_fake_supply(monkeypatch):
    install_fake_partcad_modules(
        monkeypatch,
        {
            "partcad.plugin_provider_data_cart": {
                "ProviderCart": FakeCart,
                "resolve_cart_object": lambda ctx, name: ctx.cart_objects.get(name),
            },
            "partcad.plugin_request_provider_quote": {"ProviderRequestQuote": FakeQuoteRequest},
        },
    )


def make_supply_session(monkeypatch):
    """A package with an assembly of two parts, one of them sold by two stores."""
    install_fake_supply(monkeypatch)
    session, _ = make_session()
    ctx = session.partcad_ctx
    ctx.projects["//"].suppliers = {"//:cheap": {}, "//:dear": {}}
    ctx.cart_contents = {
        "//:top": [FakeCartItem("//:bolt", count=4, vendor="acme", sku="B-1"), FakeCartItem("//:nut", count=4)],
        "//:bolt": [FakeCartItem("//:bolt", count=1, vendor="acme", sku="B-1")],
    }
    ctx.cart_objects = {
        "//:bolt": FakeObject("bolt", desc="A bolt", project_name="//"),
        "//:nut": FakeObject("nut", desc="A nut", project_name="//"),
    }
    ctx.item_suppliers = {"//:bolt": ["//:dear", "//:cheap"], "//:nut": []}
    ctx.provider_plugins = {
        "//:cheap": FakeProvider("//:cheap", price=1.5, currency="USD", url="https://cheap.example"),
        "//:dear": FakeProvider("//:dear", price=4.0, currency="USD"),
    }
    return session, ctx


def test_supply_lists_the_line_items_with_their_suppliers_cheapest_first(monkeypatch):
    session, ctx = make_supply_session(monkeypatch)

    result = operations.supply_quote(session, {"package": "//", "object": "top"})

    assert result["object"] == "//:top"
    assert [item["name"] for item in result["items"]] == ["//:bolt", "//:nut"]
    bolt = result["items"][0]
    assert (bolt["count"], bolt["vendor"], bolt["sku"], bolt["desc"]) == (4, "acme", "B-1", "A bolt")
    # Cheapest first: what the tab is read for is which supplier to order from.
    assert [option["name"] for option in bolt["suppliers"]] == ["//:cheap", "//:dear"]
    assert bolt["suppliers"][0]["price"] == 1.5
    assert bolt["suppliers"][0]["currency"] == "USD"
    assert bolt["suppliers"][0]["url"] == "https://cheap.example"
    assert bolt["suppliers"][0]["cartId"] == "cart-//:cheap"
    # A line item with no supplier is still a line item: it has to be sourced.
    assert result["items"][1]["suppliers"] == []
    assert result["totals"] == [{"currency": "USD", "price": 1.5}]
    assert ("Supply", "//") in session.partcad.logging.processes


def test_supply_quotes_each_line_item_on_its_own(monkeypatch):
    # A cart of the whole assembly comes back as one price for all of it, which
    # cannot say what any one part costs.
    session, ctx = make_supply_session(monkeypatch)

    operations.supply_quote(session, {"package": "//", "object": "top"})

    assert ctx.provider_plugins["//:cheap"].quoted == [["//:bolt"]]


def test_supply_of_a_part_is_the_one_thing_to_order(monkeypatch):
    session, _ = make_supply_session(monkeypatch)

    result = operations.supply_quote(session, {"package": "//", "object": "bolt"})

    assert [item["name"] for item in result["items"]] == ["//:bolt"]
    assert result["items"][0]["count"] == 1


def test_supply_says_nothing_when_the_package_declares_no_supplier(monkeypatch):
    # In the IDE an error is a modal popup, one per part, and a package with no
    # supplier is the ordinary case rather than a failure.
    session, ctx = make_supply_session(monkeypatch)
    ctx.projects["//"].suppliers = {}

    result = operations.supply_quote(session, {"package": "//", "object": "top"})

    assert all(item["suppliers"] == [] for item in result["items"])
    assert result["totals"] == []
    assert session.partcad.logging.messages("error") == []


def test_supply_keeps_a_supplier_that_would_not_quote(monkeypatch):
    session, ctx = make_supply_session(monkeypatch)
    ctx.provider_plugins["//:cheap"] = FakeProvider("//:cheap", error="Not enough stock")

    options = operations.supply_quote(session, {"package": "//", "object": "top"})["items"][0]["suppliers"]

    # The one that answered wins the sort; the refusal is carried, not hidden.
    assert [option["name"] for option in options] == ["//:dear", "//:cheap"]
    assert options[1]["error"] == "Not enough stock"
    assert "price" not in options[1]


def test_supply_reads_a_price_that_is_not_a_number_as_no_price(monkeypatch):
    """A quote is whatever a provider's own script put in it

    Everything downstream treats the price as a number -- the options are sorted
    by it and the cheapest of each are added up -- so a string where a number
    belongs must cost that one supplier its price, not fail the whole request.
    """
    session, ctx = make_supply_session(monkeypatch)
    ctx.provider_plugins["//:cheap"] = FakeProvider("//:cheap", price="$1.50", currency="USD")
    ctx.provider_plugins["//:dear"] = FakeProvider("//:dear", price="4.00", currency="USD")

    result = operations.supply_quote(session, {"package": "//", "object": "top"})

    options = {option["name"]: option for option in result["items"][0]["suppliers"]}
    assert options["//:cheap"]["price"] is None
    # A number that merely arrived as a string is still a number.
    assert options["//:dear"]["price"] == 4.0
    # The one that could be read wins the sort, and is what the total is of.
    assert [option["name"] for option in result["items"][0]["suppliers"]] == ["//:dear", "//:cheap"]
    assert result["totals"] == [{"currency": "USD", "price": 4.0}]


def test_supply_reports_an_object_that_cannot_be_ordered(monkeypatch):
    session, _ = make_supply_session(monkeypatch)

    with pytest.raises(JsonRpcError) as caught:
        operations.supply_quote(session, {"package": "//", "object": "missing"})

    assert caught.value.code == operations.USAGE_ERROR
    assert "Nothing to supply for //:missing" in str(caught.value)


def test_assembly_guide_returns_the_document_of_the_assembly(monkeypatch):
    install_fake_partcad_modules(monkeypatch, {"partcad.exception": {"AssemblyDocumentError": FakeDocumentError}})
    session, _ = make_session()
    document = {"title": "top", "pages": [{"title": "top", "blocks": []}]}
    session.partcad_ctx.projects["//"].guides["top"] = document

    result = operations.assembly_guide(session, {"package": "//", "object": "top"})

    assert result == {"assembly": "//:top", "document": document}
    assert session.partcad_ctx.projects["//"].guide_requests == [("top", False)]
    assert ("Guide", "//") in session.partcad.logging.processes


def test_assembly_guide_reports_a_refusal_as_a_usage_error(monkeypatch):
    # An assembly PartCAD cannot write instructions for -- one that is not an
    # ASSY file, or not meant to be built -- is what the user asked for, not a
    # failure of the machinery, and the reader is told why.
    install_fake_partcad_modules(monkeypatch, {"partcad.exception": {"AssemblyDocumentError": FakeDocumentError}})
    session, _ = make_session()
    session.partcad_ctx.projects["//"].guide_error = FakeDocumentError("//:top is a 'file' assembly")

    with pytest.raises(JsonRpcError) as caught:
        operations.assembly_guide(session, {"package": "//", "object": "top"})

    assert caught.value.code == operations.USAGE_ERROR
    assert "is a 'file' assembly" in str(caught.value)


def test_assembly_guide_reports_a_missing_assembly(monkeypatch):
    install_fake_partcad_modules(monkeypatch, {"partcad.exception": {"AssemblyDocumentError": FakeDocumentError}})
    session, _ = make_session()

    assert operations.assembly_guide(session, {"package": "//", "object": "nope"}) is None
    assert session.partcad.logging.messages("error") == ["Assembly //:nope is not found"]
