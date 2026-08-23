#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the 'export:'/'render:' sections and their implementations.

An output file type is configured by a section of 'partcad.yaml' and produced by
a script the resolution layers pick. Both ends are covered here without the
sandbox: the layering and the file naming from the configuration side, and the
meta-wrapper's contract with an implementation script from the other. A gated
end-to-end test writes a real file when a sandbox is available.
"""

import ast
import asyncio
import importlib.util
import math
import os
import sys

import pytest
import yaml

import partcad as pc
from partcad import output, sandbox_versions

EXAMPLES = "examples"
CUSTOM_EXAMPLE = "//feature_export_custom"
BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "builtin")


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(EXAMPLES)


# --------------------------------------------------------------------------- #
# The built-in packages                                                       #
# --------------------------------------------------------------------------- #


def test_builtin_packages_are_reachable(ctx):
    """'//builtin/export' and '//builtin/render' resolve in any context."""
    for section in output.SECTIONS:
        project = ctx.get_project(output.BUILTIN_PACKAGES[section])
        assert project is not None
        assert project.name == output.BUILTIN_PACKAGES[section]
        assert isinstance(project.config_obj.get(section), dict)


def test_builtin_packages_are_reachable_from_a_renamed_root():
    """The root package's own name does not shadow '//builtin'.

    'examples/partcad.yaml' renames the root to '//pub/examples/partcad', which
    is exactly the case a path-based lookup would get wrong.
    """
    context = pc.Context(EXAMPLES)
    assert context.name != "//"
    assert context.get_project("//builtin/export") is not None


def test_builtin_packages_are_not_loaded_until_used():
    """A context that writes no output file does not pay for them."""
    context = pc.Context(EXAMPLES)
    assert output.BUILTIN_PACKAGES[output.EXPORT] not in context.projects
    context.get_project(output.BUILTIN_PACKAGES[output.EXPORT])
    assert output.BUILTIN_PACKAGES[output.EXPORT] in context.projects


def test_every_builtin_format_has_an_implementation_on_disk(ctx):
    for section in output.SECTIONS:
        project = ctx.get_project(output.BUILTIN_PACKAGES[section])
        formats = project.config_obj[section]
        assert formats, section
        for format_name, config in formats.items():
            script = os.path.join(project.config_dir, config["path"])
            assert os.path.isfile(script), "%s: %s" % (format_name, script)
            assert config.get("extension"), format_name


def test_every_builtin_implementation_honours_the_wrapper_contract(ctx):
    """Each built-in script compiles and defines 'process(path, request)'.

    Checked by parsing rather than importing: these run in a sandbox and import
    a CAD stack this process does not have, but a script that does not define
    the entry point would only be found out at export time.
    """
    for section in output.SECTIONS:
        project = ctx.get_project(output.BUILTIN_PACKAGES[section])
        for format_name, config in project.config_obj[section].items():
            script = os.path.join(project.config_dir, config["path"])
            source = open(script).read()
            tree = ast.parse(source, filename=script)
            entry_points = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "process"]
            assert entry_points, "%s: %s defines no 'process()'" % (format_name, config["path"])
            arguments = [argument.arg for argument in entry_points[0].args.args]
            assert arguments == ["path", "request"], "%s: %s" % (format_name, arguments)


def _builtin_function(section, script_name, function_name):
    """One function out of a built-in implementation, without its imports.

    Same reason as the test above parses instead of importing: these scripts
    import a CAD stack this process does not have. Compiling the single
    function definition gives a callable to test the arithmetic in.
    """
    script = os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[section]], script_name)
    tree = ast.parse(open(script).read(), filename=script)
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
    namespace = {"DEFAULT_SIZE": 512, "math": math}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), script, "exec"), namespace)
    return namespace[function_name]


class _Drawing:
    """Just enough of a reportlab drawing for 'scale_for()' to measure."""

    width = 100.0
    height = 50.0


@pytest.mark.parametrize(
    "request_obj, expected",
    [
        ({}, 512.0 / 100.0),  # neither given: the default bounds both
        ({"width": 200}, 2.0),  # only one given: it alone bounds the result
        ({"height": 200}, 4.0),
        ({"width": 200, "height": 100}, 2.0),  # both given: the smaller wins
    ],
)
def test_the_raster_scale_is_bounded_by_the_dimensions_that_were_given(request_obj, expected):
    scale = _builtin_function(output.RENDER, "render_raster.py", "scale_for")
    assert scale(_Drawing(), request_obj) == expected


@pytest.mark.parametrize(
    "request_obj",
    [
        {"width": 0},
        {"height": 0},
        {"width": -1},
        {"height": -1},
        {"width": 0, "height": 100},
        # YAML spells these '.nan' and '.inf', so a configuration can carry
        # them. Neither is caught by comparing against zero.
        {"width": float("nan")},
        {"height": float("nan")},
        {"width": float("inf")},
        {"height": float("-inf")},
    ],
)
def test_a_raster_dimension_that_is_not_a_positive_finite_number_is_refused(request_obj):
    """Each of these otherwise scales to something no rasterizer can use."""
    scale = _builtin_function(output.RENDER, "render_raster.py", "scale_for")
    with pytest.raises(Exception, match="positive finite number"):
        scale(_Drawing(), request_obj)


def test_builtin_formats_cover_what_the_exporters_supported(ctx):
    """No format lost its implementation in the move into 'builtin/'."""
    assert set(output.builtin_formats(ctx, output.EXPORT)) == {
        "step",
        "brep",
        "stl",
        "3mf",
        "obj",
        "gltf",
        "iges",
        "threejs",
        "urdf",
    }
    assert set(output.builtin_formats(ctx, output.RENDER)) == {"svg", "png", "jpeg", "dxf"}


def test_builtin_requirements_match_the_pinned_cad_stack():
    """The versions in the built-in packages are the ones PartCAD pins.

    They are spelled out in YAML so the packages read as the packages they are,
    which means nothing but this test stops them drifting from
    'sandbox_versions', where a disagreement surfaces as a native crash with no
    Python traceback (see PINNED_REQUIREMENTS).
    """
    known = {
        "cadquery-ocp": sandbox_versions.CADQUERY_OCP,
        "ocpsvg": sandbox_versions.OCPSVG,
        "build123d": sandbox_versions.BUILD123D,
        "cadquery": sandbox_versions.CADQUERY,
        "svglib": sandbox_versions.SVGLIB,
        "reportlab": sandbox_versions.REPORTLAB,
        "rlpycairo": sandbox_versions.RLPYCAIRO,
        "svgpathtools": sandbox_versions.SVGPATHTOOLS,
        "ezdxf": sandbox_versions.EZDXF,
        "urdf-parser-py": sandbox_versions.URDF_PARSER_PY,
    }
    seen = set()
    for section in output.SECTIONS:
        config = yaml.safe_load(open(os.path.join(BUILTIN_DIR, section, "partcad.yaml")))
        for format_name, format_config in config[section].items():
            for requirement in format_config.get("pythonRequirements") or []:
                distribution = sandbox_versions.distribution_name(requirement)
                assert distribution in known, "%s: unknown requirement %s" % (format_name, requirement)
                assert requirement == known[distribution], "%s: %s" % (format_name, requirement)
                seen.add(distribution)
    assert seen == set(known), "unused pin(s): %s" % (set(known) - seen)


def test_cadquery_ocp_is_reasserted_after_build123d():
    """Installing build123d replaces OCP, so the pin has to come after it."""
    for section in output.SECTIONS:
        config = yaml.safe_load(open(os.path.join(BUILTIN_DIR, section, "partcad.yaml")))
        for format_name, format_config in config[section].items():
            requirements = format_config.get("pythonRequirements") or []
            if sandbox_versions.BUILD123D in requirements:
                assert requirements[-1] == sandbox_versions.CADQUERY_OCP, format_name


# --------------------------------------------------------------------------- #
# Resolving a file type                                                       #
# --------------------------------------------------------------------------- #


def _part(ctx, package, name):
    project = ctx.get_project(package)
    return project, project.get_part(name)


def test_a_builtin_format_resolves_to_the_builtin_implementation(ctx):
    project, part = _part(ctx, "//produce_part_step", "bolt")
    impl, _ = part.output_getopts(ctx, "step", project)
    assert impl.section == output.EXPORT
    assert impl.script == "export_step.py"
    assert impl.config["package"] == output.BUILTIN_PACKAGES[output.EXPORT]
    assert impl.parameters == {"write_pcurves": True, "precision_mode": 0}


def test_a_package_field_becomes_an_export_parameter(ctx):
    """'export: step: comment:' reaches the STEP implementation."""
    project, part = _part(ctx, CUSTOM_EXAMPLE, "cube")
    impl, _ = part.output_getopts(ctx, "step", project)
    # The implementation is still the built-in one...
    assert impl.config["package"] == output.BUILTIN_PACKAGES[output.EXPORT]
    # ...and it is handed the package's parameter alongside the defaults.
    assert impl.parameters["comment"].startswith("Produced by")
    assert impl.parameters["write_pcurves"] is True


def test_a_package_path_replaces_the_implementation(ctx):
    project, part = _part(ctx, CUSTOM_EXAMPLE, "cube")
    impl, _ = part.output_getopts(ctx, "stl", project)
    assert impl.script == "export_stl_commented.py"
    assert impl.config["package"] == project.name
    assert impl.parameters["comment"].startswith("Produced by")


def test_options_package_applies_to_another_packages_objects(ctx):
    """'--options-package' is what lets one package's exporter be used elsewhere."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    options_project = ctx.get_project(CUSTOM_EXAMPLE)

    impl, _ = part.output_getopts(ctx, "stl", project)
    assert impl.config["package"] == output.BUILTIN_PACKAGES[output.EXPORT]

    impl, _ = part.output_getopts(ctx, "stl", project, options_project=options_project)
    assert impl.script == "export_stl_commented.py"
    assert impl.config["package"] == options_project.name


def test_a_shape_overrides_its_package(ctx):
    project, part = _part(ctx, CUSTOM_EXAMPLE, "cube")
    part.config["export"] = {"step": {"comment": "from the shape"}}
    try:
        impl, _ = part.output_getopts(ctx, "step", project)
        assert impl.parameters["comment"] == "from the shape"
    finally:
        del part.config["export"]


def test_the_render_section_still_configures_export_formats(ctx):
    """Packages configured STEP and STL under 'render:' before 'export:' existed."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["render"] = {"step": {"precision_mode": 1, "comment": "from render:"}}
    try:
        impl, _ = part.output_getopts(ctx, "step", project)
        assert impl.parameters["precision_mode"] == 1
        assert impl.parameters["comment"] == "from render:"

        # 'export:' of the same source wins over its 'render:'.
        part.config["export"] = {"step": {"comment": "from export:"}}
        impl, _ = part.output_getopts(ctx, "step", project)
        assert impl.parameters["precision_mode"] == 1
        assert impl.parameters["comment"] == "from export:"
    finally:
        del part.config["render"]
        part.config.pop("export", None)


def test_the_output_path_comes_from_the_prefix_and_the_extension(ctx, tmp_path):
    project, part = _part(ctx, "//produce_part_step", "bolt")

    _, path = part.output_getopts(ctx, "step", project)
    assert path == os.path.join(project.config_dir, "bolt.step")

    # glTF is written as '.json', which the built-in package declares.
    _, path = part.output_getopts(ctx, "gltf", project)
    assert path.endswith("bolt.json")

    # An output directory that does not exist yet is still a directory.
    missing = str(tmp_path / "not-created-yet")
    _, path = part.output_getopts(ctx, "step", project, output_dir=missing)
    assert path == os.path.join(missing, "bolt.step")

    # An explicit file wins over everything.
    explicit = str(tmp_path / "somewhere.step")
    _, path = part.output_getopts(ctx, "step", project, filepath=explicit)
    assert path == explicit


def test_output_dir_is_a_section_setting_not_a_file_type(ctx):
    """'render: output_dir:' configures the section; it is not a format."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    section = {"output_dir": "build", "svg": {"prefix": "./"}}
    assert output.format_names(section) == ["svg"]
    assert "output_dir" not in output.all_formats(ctx)

    # ...and it still places the file it was set to place.
    part.config["render"] = section
    try:
        _, path = part.output_getopts(ctx, "svg", project)
        assert path == os.path.join("build", "bolt.svg")
    finally:
        del part.config["render"]


def test_export_wins_over_the_legacy_render_section_when_deciding_what_to_produce(ctx):
    """Project._output_cfg reads 'render:' first, so 'export:' is what lands."""
    project = ctx.get_project(CUSTOM_EXAMPLE)
    part = project.get_part("cube")
    part.config["render"] = {"step": {"exclude": ["parts"]}}
    part.config["export"] = {"step": {"comment": "from export:"}}
    try:
        cfg = project._output_cfg(part)
        assert cfg["step"]["comment"] == "from export:"
    finally:
        del part.config["render"]
        del part.config["export"]


def test_an_implementation_may_not_escape_its_package(ctx):
    """A 'path' that climbs out of the package is refused, not executed."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["export"] = {"step": {"path": "../../../etc/evil.py"}}
    try:
        impl, _ = part.output_getopts(ctx, "step", project)
        with pytest.raises(Exception, match="outside its package"):
            asyncio.run(part._materialize_output_script(ctx, impl))
    finally:
        del part.config["export"]


def test_an_unknown_format_falls_back_to_the_section_that_declares_it(ctx):
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["render"] = {"tiff": {"path": "tiff.py"}}
    try:
        impl, _ = part.output_getopts(ctx, "tiff", project)
        assert impl.section == output.RENDER
        assert impl.config["package"] == project.name
    finally:
        del part.config["render"]


def test_a_render_format_falls_back_to_the_export_implementation(ctx):
    """An export implementation stands in when 'render:' has none.

    A file a CAD tool opens as a part is also an output file, so it serves a
    render request; the reverse is not true, which is what the next test pins.
    """
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["export"] = {"tiff": {"path": "from_export.py"}}
    try:
        opts, _ = part._output_getopts(ctx, "tiff", output.RENDER, project)
        assert opts["path"] == "from_export.py"
    finally:
        del part.config["export"]


def test_a_render_implementation_wins_over_the_export_one_it_falls_back_to(ctx):
    """The fallback only applies where 'render:' left the format unimplemented."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["export"] = {"tiff": {"path": "from_export.py"}}
    part.config["render"] = {"tiff": {"path": "from_render.py"}}
    try:
        opts, _ = part._output_getopts(ctx, "tiff", output.RENDER, project)
        assert opts["path"] == "from_render.py"
    finally:
        del part.config["export"]
        del part.config["render"]


def test_an_export_format_does_not_fall_back_to_a_render_implementation(ctx):
    """'export:' owns the format, so its implementation is the one that runs."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["render"] = {"tiff": {"path": "from_render.py"}}
    part.config["export"] = {"tiff": {"path": "from_export.py"}}
    try:
        opts, _ = part._output_getopts(ctx, "tiff", output.EXPORT, project)
        assert opts["path"] == "from_export.py"
    finally:
        del part.config["render"]
        del part.config["export"]


# --------------------------------------------------------------------------- #
# The 'output' helpers                                                        #
# --------------------------------------------------------------------------- #


def test_merge_replaces_lists_instead_of_extending_them():
    merged = output.merge({"pythonRequirements": ["a", "b"]}, {"pythonRequirements": ["c"]})
    assert merged["pythonRequirements"] == ["c"]


def test_normalize_accepts_the_short_forms():
    assert output.normalize(None) == {}
    assert output.normalize("./out") == {"prefix": "./out"}
    assert output.normalize({"prefix": "x"}) == {"prefix": "x"}


def test_stamp_records_the_package_that_declared_a_path():
    assert output.stamp({"path": "x.py"}, "//pkg")["package"] == "//pkg"
    # A layer pointing at someone else's implementation is left alone...
    assert output.stamp({"path": "x.py", "package": "//other"}, "//pkg")["package"] == "//other"
    # ...and so is one that names no implementation at all.
    assert "package" not in output.stamp({"comment": "hi"}, "//pkg")


class _Assembly:
    """The little of an assembly that document selection actually reads."""

    kind = "assembly"

    def __init__(self, render_cfg):
        self.name = "widget"
        self.config = {"render": render_cfg}


def test_an_implemented_pdf_is_not_overwritten_by_the_assembly_guide(ctx):
    """The instruction book gives way to an implementation of the same file type.

    Both would be written to '<assembly>.pdf', so whichever ran second would win
    silently. The implementation is what the package asked for.
    """
    project = ctx.get_project("//produce_part_step")

    # Declared with nothing behind it: still the instruction book.
    assembly = _Assembly({"pdf": None})
    assert project._assembly_documents_to_render([assembly], None, None, "pdf") == ["widget"]

    # Declared with an implementation: a file of the assembly's own, produced
    # like any other file type.
    assembly = _Assembly({"pdf": {"package": "//pub/feature/render/draftwright", "path": "draw.py"}})
    assert project._assembly_documents_to_render([assembly], None, None, "pdf") == []

    # The implementation may equally come from the package rather than the
    # assembly, which is where the package-level configuration comes in.
    assembly = _Assembly({})
    package_cfg = {"pdf": {"package": "//pub/feature/render/draftwright", "path": "draw.py"}}
    assert project._assembly_documents_to_render([assembly], ["widget"], "pdf", "pdf", package_cfg) == []
    assert project._assembly_documents_to_render([assembly], ["widget"], "pdf", "pdf", {"pdf": None}) == ["widget"]


def test_a_document_format_stops_being_one_once_somebody_implements_it():
    """'pdf' is the instruction book only for as long as nobody writes a 'pdf'.

    A package that names an implementation for it is saying that its 'pdf' is a
    file of its own - a drawing, a datasheet - and PartCAD has to produce it the
    way it produces every other file type a package implements, instead of
    quietly rendering the assembly guide over it.
    """
    # Nothing declared, declared empty, or declared as a bare output location:
    # all still the document PartCAD assembles itself.
    assert output.is_document_format("pdf", {})
    assert output.is_document_format("pdf", {"pdf": None})
    assert output.is_document_format("pdf", {"pdf": "./drawings"})
    assert output.is_document_format("pdf", {"pdf": {"prefix": "./drawings"}})
    assert output.is_document_format("html", {})
    assert output.is_document_format("readme", {})
    # An implementation, in this package or in another one.
    assert not output.is_document_format("pdf", {"pdf": {"path": "draw.py"}})
    assert not output.is_document_format(
        "pdf", {"pdf": {"package": "//pub/feature/render/draftwright", "path": "render_draftwright.py"}}
    )
    # Everything else is a file type an implementation always writes.
    assert not output.is_document_format("svg", {})
    assert not output.is_document_format("step", {"step": {"comment": "hi"}})


def test_parameters_exclude_the_reserved_fields():
    impl = output.Implementation(
        output.EXPORT,
        "step",
        {
            "path": "s.py",
            "package": "//p",
            "pythonRequirements": [],
            "extension": "step",
            "decode": False,
            "comment": "x",
        },
    )
    assert impl.parameters == {"comment": "x"}
    assert impl.extension("brep") == "step"
    assert impl.python_version() == sandbox_versions.DEFAULT_PYTHON_VERSION
    assert impl.decode is False


def test_a_format_decodes_its_envelopes_unless_it_declares_otherwise(ctx):
    """'decode' is off for URDF alone, and nothing else may lose it silently.

    The URDF exporter is handed the assembly tree, one link per node; decoded
    geometry carries no node names, labels or separate placements to build those
    links from, so 'export_urdf.process()' rejects it outright and the export
    fails with "needs a shape or an assembly to export". It is the only built-in
    format that asks for that, so this also guards the other direction.
    """
    off = set()
    for section in output.SECTIONS:
        project = ctx.get_project(output.BUILTIN_PACKAGES[section])
        for format_name, config in project.config_obj[section].items():
            impl = output.Implementation(section, format_name, config)
            if not impl.decode:
                off.add(format_name)
    assert off == {"urdf"}


# --------------------------------------------------------------------------- #
# The meta-wrapper                                                            #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def wrapper_export():
    """Import 'wrappers/wrapper_export.py' without the sandbox around it.

    It imports 'wrapper_common', which imports 'ocp_serialize', which needs a
    CAD stack this process does not have. Only the serialization helpers of
    'wrapper_common' are stubbed out; the module under test is the real one.
    """
    wrappers = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "wrappers")

    class _Stub:
        @staticmethod
        def exception_to_str(exc):
            return None if exc is None else str(exc)

        @staticmethod
        def handle_exception(exc, script=None):
            pass

    saved = sys.modules.get("wrapper_common")
    sys.modules["wrapper_common"] = _Stub
    saved_path = list(sys.path)
    sys.path.insert(0, wrappers)
    try:
        spec = importlib.util.spec_from_file_location(
            "partcad_test_wrapper_export", os.path.join(wrappers, "wrapper_export.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = saved_path
        if saved is None:
            del sys.modules["wrapper_common"]
        else:
            sys.modules["wrapper_common"] = saved


def _script(tmp_path, body):
    path = tmp_path / "impl.py"
    path.write_text(body)
    return str(path)


def test_wrapper_runs_a_script_that_defines_process(wrapper_export, tmp_path):
    script = _script(
        tmp_path,
        "def process(path, request):\n"
        "    open(path, 'w').write(request['comment'])\n"
        "    return {'success': True, 'exception': None}\n",
    )
    out = str(tmp_path / "out.txt")
    result = wrapper_export.process(script, out, {"comment": "hello"})
    assert result == {"success": True, "exception": None}
    assert open(out).read() == "hello"


def test_wrapper_runs_a_script_that_sets_output(wrapper_export, tmp_path):
    script = _script(
        tmp_path,
        "open(path, 'w').write(request['comment'])\noutput = {'success': True}\n",
    )
    out = str(tmp_path / "out.txt")
    assert wrapper_export.process(script, out, {"comment": "hi"})["success"] is True
    assert open(out).read() == "hi"


def test_wrapper_reports_a_script_that_raises(wrapper_export, tmp_path):
    script = _script(tmp_path, "raise RuntimeError('nope')\n")
    result = wrapper_export.process(script, str(tmp_path / "out.txt"), {})
    assert result["success"] is False
    assert "nope" in result["exception"]


def test_wrapper_reports_a_script_that_reports_a_failure(wrapper_export, tmp_path):
    script = _script(tmp_path, "output = {'success': True, 'exception': 'it went wrong'}\n")
    result = wrapper_export.process(script, str(tmp_path / "out.txt"), {})
    # 'success' is not taken at face value when an exception came with it.
    assert result == {"success": False, "exception": "it went wrong"}


def test_wrapper_reports_a_script_that_produces_nothing(wrapper_export, tmp_path):
    script = _script(tmp_path, "x = 1\n")
    result = wrapper_export.process(script, str(tmp_path / "out.txt"), {})
    assert result["success"] is False
    assert "process(path, request)" in result["exception"]


# --------------------------------------------------------------------------- #
# End to end                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_step_export_carries_the_configured_comment(tmp_path):
    """The 'comment' of 'export: step:' ends up in the STEP file (needs the sandbox)."""
    context = pc.Context(EXAMPLES)
    project = context.get_project(CUSTOM_EXAMPLE)
    part = project.get_part("cube")
    path = str(tmp_path / "cube.step")
    try:
        part.render(context, "step", project, filepath=path)
    except Exception as e:
        pytest.skip("Sandbox unavailable: %s" % e)
    assert os.path.exists(path), "the STEP exporter produced no file"
    comment = "Produced by the PartCAD 'feature_export_custom' example."
    # A STEP string escapes a single quote by doubling it, so the comment the
    # example configures is in the file in that form rather than verbatim.
    assert comment.replace("'", "''") in open(path).read()


@pytest.mark.slow
def test_a_custom_implementation_writes_the_file(tmp_path):
    """The package's own STL exporter is the one that runs (needs the sandbox)."""
    context = pc.Context(EXAMPLES)
    project = context.get_project(CUSTOM_EXAMPLE)
    part = project.get_part("cube")
    path = str(tmp_path / "cube.stl")
    try:
        part.render(context, "stl", project, filepath=path)
    except Exception as e:
        pytest.skip("Sandbox unavailable: %s" % e)
    assert os.path.exists(path), "the package's STL exporter produced no file"
    first_line = open(path).readline()
    # ASCII, and named after the package's comment - neither is what the
    # built-in STL exporter would have produced.
    assert first_line.startswith("solid Produced by the PartCAD")
