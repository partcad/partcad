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
import re
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


def _builtin_function(section, script_name, function_name, also=()):
    """One function out of a built-in implementation, without its imports.

    Same reason as the test above parses instead of importing: these scripts
    import a CAD stack this process does not have. Compiling the single
    function definition gives a callable to test the arithmetic in.

    'also' names the other top-level definitions it needs -- a sibling function
    it calls, a constant it reads -- which are compiled into the same namespace,
    in the order the file has them.
    """
    script = os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[section]], script_name)
    tree = ast.parse(open(script).read(), filename=script)
    wanted = set(also) | {function_name}

    def names_of(node):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            return {node.name}
        if isinstance(node, ast.Assign):
            return {target.id for target in node.targets if isinstance(target, ast.Name)}
        return set()

    body = [node for node in tree.body if names_of(node) & wanted]
    namespace = {"DEFAULT_SIZE": 512, "math": math, "re": re}
    exec(compile(ast.Module(body=body, type_ignores=[]), script, "exec"), namespace)
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


def test_every_built_in_package_validates_against_partcads_own_schema():
    """Whatever PartCAD's own tooling writes has to pass PartCAD's own checks.

    The built-in packages are ordinary packages -- that is the whole point of
    them -- so nothing exempts them from the schema every other 'partcad.yaml'
    is held to, and nothing else checks them: `pc lint` walks a *user's*
    package, and these are never in one's dependency tree.

    It bites in an unobvious place. A parameter value has to be spellable in an
    instance name ("scene;subject_offset=..."), where ',', ';' and '=' are the
    separators, so the schema refuses a string default that carries one -- and a
    PartCAD location written the usual way is nothing but those characters. The
    built-in scene's offset parameter is spelled the way it is because of this,
    and this is what says so.
    """
    import jsonschema

    from partcad.lint.all import get_partcad_schema

    schema = get_partcad_schema()
    for package, path in output.BUILTIN_PATHS.items():
        config = yaml.safe_load(open(os.path.join(path, "partcad.yaml")))
        try:
            jsonschema.validate(config, schema)
        except jsonschema.ValidationError as e:
            raise AssertionError("%s does not validate: %s" % (package, e.message)) from e


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
    for section, where, requirements in _builtin_requirements():
        for requirement in requirements:
            distribution = sandbox_versions.distribution_name(requirement)
            assert distribution in known, "%s: unknown requirement %s" % (where, requirement)
            assert requirement == known[distribution], "%s: %s" % (where, requirement)
            seen.add(distribution)
    assert seen == set(known), "unused pin(s): %s" % (set(known) - seen)


def _builtin_requirements():
    """Every 'pythonRequirements' list in the built-in packages.

    A file type declares what its own script needs; the package declares what
    the scripts share, which is also what a file type another package declares
    against one of those scripts gets (see '//builtin/render'). Both are
    installed into the sandbox, so both are pins that can drift.
    """
    for section in output.SECTIONS:
        config = yaml.safe_load(open(os.path.join(BUILTIN_DIR, section, "partcad.yaml")))
        yield section, section, config.get("pythonRequirements") or []
        for format_name, format_config in config[section].items():
            yield section, format_name, format_config.get("pythonRequirements") or []


def test_cadquery_ocp_is_reasserted_after_build123d():
    """Installing build123d replaces OCP, so the pin has to come after it."""
    for _section, where, requirements in _builtin_requirements():
        if sandbox_versions.BUILD123D in requirements:
            assert requirements[-1] == sandbox_versions.CADQUERY_OCP, where


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
    # 'reproducible' is among them because '//builtin/export' declares it on
    # every file type -- see 'test_every_builtin_file_type_declares_reproducible'.
    assert impl.parameters == {"write_pcurves": True, "precision_mode": 0, "reproducible": False}


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


def test_a_format_may_name_the_package_that_implements_it(ctx):
    """'pc export -t <package>:<type>' is how an implementation elsewhere is reached.

    The same answer '--options-package' gives, asked for in the file type itself.
    It exists because there are file types no package can reach any other way:
    nothing in '//builtin/export' writes MJCF or SDFormat, so a scene asked for
    one has nothing to resolve unless the plugin that implements it is named.
    """
    project, part = _part(ctx, "//produce_part_step", "bolt")

    impl, _ = part.output_getopts(ctx, CUSTOM_EXAMPLE + ":stl", project)
    assert impl.script == "export_stl_commented.py"
    assert impl.config["package"] == ctx.get_project(CUSTOM_EXAMPLE).name
    assert impl.parameters["comment"].startswith("Produced by")


def test_naming_a_package_leaves_the_file_named_after_the_bare_type(ctx):
    """The package path says where to resolve; it is not part of the file type."""
    project, part = _part(ctx, "//produce_part_step", "bolt")

    impl, filepath = part.output_getopts(ctx, CUSTOM_EXAMPLE + ":stl", project)
    assert impl.format_name == "stl"
    assert os.path.basename(filepath) == "bolt.stl"


def test_a_named_package_is_still_re_tuned_by_the_caller(ctx):
    """Naming somebody else's exporter does not hand it their parameters as well.

    The named package is a layer above the built-in one and below the caller,
    which is what keeps a parameter the caller sets -- and, for the same reason,
    where the file goes -- the caller's to decide.
    """
    project, part = _part(ctx, "//produce_part_step", "bolt")
    part.config["export"] = {"stl": {"comment": "from the shape"}}
    try:
        impl, _ = part.output_getopts(ctx, CUSTOM_EXAMPLE + ":stl", project)
        assert impl.script == "export_stl_commented.py"
        assert impl.parameters["comment"] == "from the shape"
    finally:
        del part.config["export"]


def test_a_format_naming_a_package_that_is_not_there_says_which_package(ctx):
    project, part = _part(ctx, "//produce_part_step", "bolt")
    with pytest.raises(Exception) as caught:
        part.output_getopts(ctx, "//no_such_package:stl", project)
    assert "//no_such_package" in str(caught.value)


def test_splitting_a_format_leaves_a_bare_name_alone():
    """Every file type that names no package, which is nearly all of them."""
    assert output.split_format("//here", "stl") == ("stl", None)
    assert output.split_format("//here", None) == (None, None)
    assert output.split_format("//here", "//there:stl") == ("stl", "//there")
    # Relative to the package that asked, the way every other resource path is.
    assert output.split_format("//here", "sibling:stl") == ("stl", "//here/sibling")


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


def test_a_name_with_a_slash_names_a_file_in_a_sub_directory():
    """'a/b' is the file 'b' in the directory 'a', spelled for this filesystem.

    Which is the only thing it can be: no filesystem takes a '/' in a file name,
    so the alternative to a sub-directory is not a flat file called 'a/b.step'
    but no file at all.
    """
    assert output.name_to_path("bolt", ".step") == "bolt.step"
    assert output.name_to_path("robot/base_link", ".step").split(os.sep) == ["robot", "base_link.step"]
    assert output.name_to_path("world/robot/base_link", ".step").split(os.sep) == [
        "world",
        "robot",
        "base_link.step",
    ]

    # The suffix belongs to the file and to nothing above it: an analysis writes
    # '<part>.<analysis>.<extension>' (see 'Shape.analysis_getopts').
    assert output.name_to_path("robot/base_link", ".fea.vtu").split(os.sep) == ["robot", "base_link.fea.vtu"]

    # The separator in a *name* is '/' whatever the platform, and none of it
    # survives into the path: a directory called 'robot/base_link' is not
    # something Windows could read back, which is what makes the tree the same
    # one there as here.


def test_the_output_path_of_a_name_with_a_slash_is_in_a_sub_directory(ctx, tmp_path):
    """A part declared as '<dir>/<part>' is written into '<dir>'.

    'examples/feature_import' declares its STEP parts that way, and a part a
    STEP assembly or a URDF materializes is named that way whether the package
    spelled it out or not.
    """
    project, part = _part(ctx, "//feature_import", "AeroAssembly_assy_example/AeroFrame_Cap")

    _, path = part.output_getopts(ctx, "step", project)
    assert path == os.path.join(project.config_dir, "AeroAssembly_assy_example", "AeroFrame_Cap.step")

    # An output directory is where the sub-directory goes, not something it
    # replaces.
    _, path = part.output_getopts(ctx, "step", project, output_dir=str(tmp_path))
    assert path == os.path.join(str(tmp_path), "AeroAssembly_assy_example", "AeroFrame_Cap.step")

    # A file the caller named is that file, '/' in the object's name or not.
    explicit = str(tmp_path / "somewhere.step")
    _, path = part.output_getopts(ctx, "step", project, filepath=explicit)
    assert path == explicit


def test_the_sub_directories_a_name_asks_for_are_created(ctx, tmp_path):
    """A part declared as '<dir>/<part>' gets the directory its name asks for."""
    target = os.path.join(str(tmp_path), "robot", "base_link.step")
    ctx.ensure_dirs_for_file(target)
    assert os.path.isdir(os.path.dirname(target))

    deeper = os.path.join(str(tmp_path), "world", "robot", "base_link.step")
    ctx.ensure_dirs_for_file(deeper)
    assert os.path.isdir(os.path.dirname(deeper))


def test_the_directory_the_output_lands_in_is_created_too(ctx, tmp_path):
    """The whole path, not the half of it the object's name is responsible for.

    Creation used to stop below the directory the *user* had named -- an
    output directory, a 'prefix' -- and leave that one to '--create-dirs'. The
    flag is gone, so the whole path a resolved file name asks for is made on
    the way to writing it.
    """
    missing = os.path.join(str(tmp_path), "nowhere", "robot", "base_link.step")
    ctx.ensure_dirs_for_file(missing)
    assert os.path.isdir(os.path.dirname(missing))

    # A name that asks for no directory of its own still lands somewhere.
    plain = os.path.join(str(tmp_path), "elsewhere", "bolt.step")
    ctx.ensure_dirs_for_file(plain)
    assert os.path.isdir(os.path.dirname(plain))

    # And a directory that is already there is not an error.
    ctx.ensure_dirs_for_file(plain)
    assert os.path.isdir(os.path.dirname(plain))


def test_a_file_with_no_directory_in_its_name_asks_for_nothing(ctx):
    """A bare file name is a file in the current directory; there is nothing to make."""
    ctx.ensure_dirs_for_file("bolt.step")


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


class _ImplementingPackage:
    """A package that ships an output implementation, as the resolution reads it."""

    def __init__(self, name="//pub/feature/render/draftwright", declared=None, section_obj=None):
        self.name = name
        self.python_version_declared = declared
        self.config_obj = {output.RENDER: section_obj} if section_obj is not None else {}


def test_the_sandbox_comes_from_the_package_that_wrote_the_implementation():
    """Which Python runs a script, and what is installed on it, is its author's.

    A package that draws with somebody else's renderer is a caller. It may be a
    package of STEP files with no Python of its own at all, and it has never
    heard of what that script imports - so the interpreter and the requirements
    are read where they are known, beside the script.
    """
    config = {"package": "//pub/feature/render/draftwright", "path": "render_draftwright.py"}

    # Declared by the implementing package, for everything it implements...
    impl = output.Implementation(output.RENDER, "pdf", config, _ImplementingPackage(declared="3.13"))
    assert impl.python_version() == "3.13"
    assert impl.python_requirements == []

    # ...or on the file type, in that same package.
    project = _ImplementingPackage(
        section_obj={
            "pdf": {
                "path": "render_draftwright.py",
                "pythonVersion": "3.12",
                "pythonRequirements": ["ezdxf==1.4.4"],
            }
        }
    )
    impl = output.Implementation(output.RENDER, "pdf", config, project)
    assert impl.python_version() == "3.12"
    assert impl.python_requirements == ["ezdxf==1.4.4"]

    # Nothing declared anywhere: a fixed default, not the interpreter PartCAD
    # happens to be running on, and nothing to install.
    impl = output.Implementation(output.RENDER, "pdf", config, _ImplementingPackage())
    assert impl.python_version() == sandbox_versions.DEFAULT_PYTHON_VERSION
    assert impl.python_requirements == []


def test_a_calling_package_does_not_configure_the_implementations_sandbox():
    """What a caller says about the environment is not read at all.

    Not overridden, not warned about - never consulted. There is nothing to warn
    about: a package asking for a drawing is not making a claim about somebody
    else's interpreter, and the layered options carry these keys only because
    every field of a file type is layered the same way.
    """
    caller_says = {
        "package": "//pub/feature/render/draftwright",
        "path": "render_draftwright.py",
        "pythonVersion": "3.10",
        "pythonRequirements": ["build123d==0.11.1"],
    }
    impl = output.Implementation(output.RENDER, "pdf", caller_says, _ImplementingPackage(declared="3.13"))
    assert impl.python_version() == "3.13"
    assert impl.python_requirements == []

    # ...including when the implementing package has nothing to say either.
    impl = output.Implementation(output.RENDER, "pdf", caller_says, _ImplementingPackage())
    assert impl.python_version() == sandbox_versions.DEFAULT_PYTHON_VERSION
    assert impl.python_requirements == []


def test_the_builtin_implementations_still_get_their_own_requirements(ctx):
    """The rule is not a special case: '//builtin' is an implementing package too."""
    project, part = _part(ctx, "//produce_part_step", "bolt")
    impl, _ = part.output_getopts(ctx, "step", project)
    impl.project = ctx.get_project(output.BUILTIN_PACKAGES[output.EXPORT])
    assert impl.python_version() == sandbox_versions.DEFAULT_PYTHON_VERSION
    assert "cadquery-ocp==%s" % sandbox_versions.CADQUERY_OCP.split("==")[1] in impl.python_requirements


def test_a_format_decodes_its_envelopes_unless_it_declares_otherwise(ctx):
    """'decode' is off for the tree exporter, and it may not lose it silently.

    The URDF exporter is handed the assembly tree, one link per node; decoded
    geometry carries no node names, labels or separate placements to build those
    from, so it rejects it outright and the export fails with "needs a shape or
    an assembly to export". It is the only built-in format that asks for that --
    the engine scene exporters that also did are their plugins' now -- so this
    guards the other direction too.
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
def test_a_package_renders_a_file_type_named_in_another_package(tmp_path):
    """A bulk render honours a 'package:format' name (needs the sandbox).

    The list of file types a package renders is what that package and the
    built-in ones declare, and a type named by its full path is in neither -
    being somewhere else is the whole reason for spelling it that way. Filtered
    against that list, 'pc export -t <package>:<type>' reported success and
    wrote nothing at all.
    """
    context = pc.Context(EXAMPLES)
    project = context.get_project("//produce_part_step")
    named = ctx_relative_format(context)
    try:
        asyncio.run(project.render_async(parts=["bolt"], format=named, output_dir=str(tmp_path)))
    except Exception as e:
        pytest.skip("Sandbox unavailable: %s" % e)

    written = str(tmp_path / "bolt.stl")
    assert os.path.exists(written), "nothing was written for '%s'" % named
    # The other package's implementation, not the built-in one: ASCII, and named
    # after that package's comment.
    assert open(written).readline().startswith("solid Produced by the PartCAD")


def ctx_relative_format(context):
    """'<package>:stl', spelled the way a package's own configuration would."""
    return "%s:stl" % context.get_project(CUSTOM_EXAMPLE).name


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


# --------------------------------------------------------------------------- #
# 'reproducible'                                                              #
# --------------------------------------------------------------------------- #


def test_every_builtin_file_type_declares_reproducible(ctx):
    """All of them, in both sections, and all of them 'false'.

    Declared even on the exporters that write the same bytes either way. It is a
    field of the protocol rather than one format's parameter, and a file type
    that left it out would be one where a package reading '//builtin' as the
    reference could reasonably conclude that the word means nothing here.
    """
    for section in output.SECTIONS:
        project = ctx.get_project(output.BUILTIN_PACKAGES[section])
        for format_name, config in project.config_obj[section].items():
            assert output.REPRODUCIBLE_KEY in config, "%s:%s" % (section, format_name)
            assert config[output.REPRODUCIBLE_KEY] is False, "%s:%s" % (section, format_name)


def test_reproducible_is_a_parameter_and_not_a_reserved_field():
    """It has to reach the implementation, which is what reserving it would stop."""
    impl = output.Implementation(output.RENDER, "svg", {"path": "s.py", "reproducible": True})
    assert impl.parameters == {"reproducible": True}
    assert impl.reproducible is True
    assert output.REPRODUCIBLE_KEY not in output.RESERVED_KEYS


def test_reproducible_defaults_to_false_when_nothing_declares_it():
    assert output.Implementation(output.RENDER, "svg", {}).reproducible is False
    assert output.Implementation(output.EXPORT, "step", {"comment": "x"}).reproducible is False


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, True),
        (False, False),
        (None, False),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("1", True),
        ("false", False),
        ("False", False),
        ("no", False),
        ("0", False),
        ("", False),
    ],
)
def test_a_flag_is_read_the_same_however_a_caller_spelled_it(value, expected):
    """YAML hands back a bool; the CLI and JSON-RPC hand back what they parsed.

    A 'reproducible' that arrived as the string "false" and was read as true is
    the silent kind of wrong: what it turns off is a guarantee nobody checks
    until the bytes move.
    """
    assert output.as_flag(value) is expected


@pytest.mark.parametrize("value", [0, 1, 2, "maybe", [], {}, 1.5])
def test_a_flag_that_is_not_a_flag_is_refused(value):
    with pytest.raises(ValueError, match="must be true or false"):
        output.as_flag(value)


def test_the_flag_reaches_the_request_of_every_implementation():
    """Set by '_run_implementation_locked', whatever the caller put in.

    The point of it is that an implementation never has to ask whether the key
    is there, so this covers the request that declared nothing as much as the
    one that did.
    """
    recorded = []

    class _Impl:
        decode = True
        container = None
        format_name = "svg"
        project = None

        def __init__(self, reproducible):
            self.reproducible = reproducible

    class _Fake:
        name = "part"
        project_name = "//pkg"

        _run_implementation_locked = pc.shape.Shape._run_implementation_locked

        def error(self, message):  # pragma: no cover - not reached here
            raise AssertionError(message)

    def _serialize(request):
        recorded.append(dict(request))
        raise _Stop()

    class _Stop(Exception):
        pass

    original = pc.shape.shape_envelope.serialize
    pc.shape.shape_envelope.serialize = _serialize
    try:
        for declared, request, expected in (
            (False, {}, False),
            (True, {}, True),
            # What the layered configuration produced, which is already in the
            # request by the time it gets here, wins over the implementation's
            # own reading of it -- that is where a command-line override lands.
            (False, {"reproducible": True}, True),
            (True, {"reproducible": False}, False),
            # ...and is coerced on the way through.
            (False, {"reproducible": "true"}, True),
        ):
            with pytest.raises(_Stop):
                asyncio.run(_Fake()._run_implementation_locked(None, _Impl(declared), "s.py", request, "/tmp/out.svg"))
            assert recorded[-1][output.REPRODUCIBLE_KEY] is expected
    finally:
        pc.shape.shape_envelope.serialize = original


def test_the_svg_renderer_rounds_every_number_to_the_precision_it_claims():
    """What 'reproducible' settles besides the choice of algorithm.

    The three cases here are measured ones: a stroke width and an arc rotation
    that two machines computed a last bit apart, and a coordinate that is zero
    on both but signed on one. None is visible at any zoom and each is a diff
    every time the drawing is produced somewhere new.
    """
    canonical = _builtin_function(output.RENDER, "render_svg.py", "_canonical_number")

    # A number that differs below the precision is written the same either way.
    assert canonical("0.03189439769248931", 10) == canonical("0.0318943976924893", 10) == "0.0318943977"
    # An angle of half a femtodegree is no rotation at all.
    assert canonical("5.660461030554823e-16", 10) == "0.0"
    assert canonical("-5.021204581828495e-16", 10) == "0.0"
    # Negative zero is zero.
    assert canonical("-0.0", 10) == "0.0"
    assert canonical("-0.00000000001", 10) == "0.0"
    # A coordinate already within the precision is left where it was.
    assert canonical("-8.1649658093", 10) == "-8.1649658093"
    assert canonical("10.0", 10) == "10.0"
    # An integer is a count or a name -- a colour channel, an arc flag, the
    # '2000' of the SVG namespace URL -- and is never a measurement here.
    assert canonical("64", 10) == "64"
    assert canonical("-1", 10) == "-1"
    assert canonical("2000", 10) == "2000"


def test_a_reproducible_drawing_is_normalized_and_an_ordinary_one_is_not(tmp_path):
    """The rounding is what 'reproducible' asks for and not what a render does.

    A drawing nobody has to diff is left exactly as build123d wrote it: the
    rounding costs a pass over the file, and every digit it removes was one the
    file type did not claim to have.
    """
    normalize = _builtin_function(output.RENDER, "render_svg.py", "_normalize", also=("_NUMBER", "_canonical_number"))

    drawn = (
        '<svg width="444.40500673690001mm" version="1.1" xmlns="http://www.w3.org/2000/svg">\n'
        '  <g stroke="rgb(64,192,64)" stroke-width="0.03189439769248931">\n'
        '    <line x1="-0.0" y1="-8.1649658093" />\n'
        '    <path d="M 10.0,5.576189073395618 A 10.0,5.0 5.660461030554823e-16 0,1 1.0,2.0" />\n'
        "  </g>\n"
        "</svg>\n"
    )
    path = tmp_path / "drawing.svg"
    path.write_text(drawn, encoding="utf-8")
    normalize(str(path), 10)
    written = path.read_text(encoding="utf-8")

    assert 'stroke-width="0.0318943977"' in written
    assert 'x1="0.0"' in written
    assert "A 10.0,5.0 0.0 0,1 1.0,2.0" in written
    assert 'width="444.4050067369mm"' in written
    # Untouched: the colour channels, the version, the namespace, the flags.
    assert 'stroke="rgb(64,192,64)"' in written
    assert 'version="1.1"' in written
    assert 'xmlns="http://www.w3.org/2000/svg"' in written
    # Idempotent, which is what makes it safe to run over a drawing twice.
    normalize(str(path), 10)
    assert path.read_text(encoding="utf-8") == written


def test_the_dxf_renderer_writes_fixed_metadata_only_when_asked():
    """'reproducible' used to be on by default here, and here alone.

    That made 'dxf' the one file type where the word meant something different
    from what it means everywhere else. The DXF example asks for it explicitly
    now, like every other drawing in this repository that is checked in.
    """
    script = os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]], "render_dxf.py")
    tree = ast.parse(open(script).read(), filename=script)
    convert = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "convert_svg_to_dxf"
    )
    assert ast.literal_eval(convert.args.defaults[-1]) is False
