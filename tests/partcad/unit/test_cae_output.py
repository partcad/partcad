#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the `cae:` section: how an analysis picks its implementation.

`cae:` is an output section of the same shape as `export:` and `render:` and is
resolved by the same code, which is the point of it - and also the risk. Two
things have to stay true and are what is checked here:

* a `cae:` file type is **not** an output format. `pc render -t fea` must not
  find it, and it must not fall back to a render implementation.
* the implementation comes from the user configuration by default, is named as
  `<package>:<file type>`, and the file it writes is named after the analysis as
  well as the object - `bracket.fea.vtu`, because a part has as many results as
  it has analyses.

No solver and no sandbox: everything here stops at the point where the script
would be run.
"""

import importlib.util
import os
import sys
import textwrap

import pytest

import partcad as pc
from partcad import cae, output

EXAMPLES = "examples"


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(EXAMPLES)


# --------------------------------------------------------------------------- #
# The section is its own                                                      #
# --------------------------------------------------------------------------- #


def test_cae_is_not_an_output_section():
    """'pc export'/'pc render' must not offer an analysis as a file type."""
    assert output.CAE not in output.SECTIONS
    assert output.CAE in output.ALL_SECTIONS


def test_cae_has_no_fallback_section():
    """An export implementation cannot stand in for a solver, or the reverse."""
    assert output.config_sections(output.CAE) == (output.CAE,)
    assert output.CAE not in output.config_sections(output.EXPORT)
    assert output.CAE not in output.config_sections(output.RENDER)


def test_cae_has_no_builtin_package(ctx):
    """PartCAD ships no solver, so there is no bottom layer for 'cae:'.

    Asked of the two functions that used to index 'BUILTIN_PACKAGES' directly:
    a KeyError here is what a user would have seen instead of "no implementation
    is configured".
    """
    assert output.CAE not in output.BUILTIN_PACKAGES
    assert output.builtin_project(ctx, output.CAE) is None
    assert output.builtin_formats(ctx, output.CAE) == {}


def test_an_analysis_is_not_a_known_output_format(ctx):
    """'fea' is not something 'pc render -t' or 'pc export -t' can name."""
    assert output.section_of(ctx, cae.FEA) is None
    assert cae.FEA not in output.all_formats(ctx)


# --------------------------------------------------------------------------- #
# Resolving an implementation                                                 #
# --------------------------------------------------------------------------- #

PACKAGE = textwrap.dedent(
    """
    name: //cae-test
    parts:
      bracket:
        type: step
        path: bracket.step
        fea:
          fix:
            - m3-screw
          load:
            hook: 5 kg
    cae:
      fea:
        path: solve.py
        extension: vtu
        iterations: 3
      plot:
        path: solve.py
        extension: png
    """
)


@pytest.fixture
def package(tmp_path):
    """A package that implements 'fea' itself, so nothing has to be fetched."""
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "solve.py").write_text("def process(path, request):\n    return {'success': True}\n")
    # Not read by anything here: a part is resolved from its declaration, and
    # the geometry is only built when something asks for it.
    (tmp_path / "bracket.step").write_text("")
    return pc.Context(str(tmp_path))


def _bracket(package):
    part = package.get_part(":bracket")
    assert part is not None
    return part


def test_the_analysis_names_the_file_as_well_as_the_object(package):
    """'bracket.fea.vtu': a part has as many results as it has analyses."""
    part = _bracket(package)
    impl, filepath = part.analysis_getopts(package, cae.FEA, cae.FEA, package.get_project("//cae-test"))
    assert os.path.basename(filepath) == "bracket.fea.vtu"
    assert impl.section == output.CAE
    # Everything that is not implementation or output plumbing reaches the
    # script as a parameter, exactly as it does for an export format.
    assert impl.parameters["iterations"] == 3


def test_the_file_type_need_not_be_named_after_the_analysis(package):
    """What the file is named after is the analysis; the type only picks a script.

    A user who points 'caeFeaImplementation' at '<package>:plot' is choosing an
    implementation, not renaming their results.
    """
    part = _bracket(package)
    _impl, filepath = part.analysis_getopts(package, cae.FEA, "plot", package.get_project("//cae-test"))
    assert os.path.basename(filepath) == "bracket.fea.png"


def test_an_implementation_that_says_no_extension_is_refused(package, tmp_path):
    """Which format an analysis writes is the implementation's to state.

    Guessing on its behalf would put a name on a file whose contents are
    something else, which is worse than saying so.
    """
    without = PACKAGE.replace("    extension: vtu\n", "")
    assert without != PACKAGE
    (tmp_path / "partcad.yaml").write_text(without)
    context = pc.Context(str(tmp_path))
    part = context.get_part(":bracket")
    with pytest.raises(Exception, match="extension"):
        part.analysis_getopts(context, cae.FEA, cae.FEA, context.get_project("//cae-test"))


def test_the_default_implementation_comes_from_the_user_configuration(package, monkeypatch):
    """'pc cae fea :bracket' works in a package that says nothing about solvers."""
    from partcad_utils.user_config import user_config

    monkeypatch.setattr(user_config, "cae_fea_implementation", "//cae-test:fea", raising=False)
    part = _bracket(package)
    project, format_name = part._analysis_implementation(package, cae.FEA, None)
    assert (project.name, format_name) == ("//cae-test", "fea")


def test_an_implementation_may_be_named_for_one_run(package):
    part = _bracket(package)
    project, format_name = part._analysis_implementation(package, cae.FEA, "//cae-test:plot")
    assert (project.name, format_name) == ("//cae-test", "plot")


def test_a_package_on_its_own_means_the_analysis_of_that_package(package):
    """The spelling a package publishing one implementation per analysis gets."""
    part = _bracket(package)
    project, format_name = part._analysis_implementation(package, cae.FEA, "//cae-test")
    assert (project.name, format_name) == ("//cae-test", "fea")


def test_a_missing_implementation_package_says_which_one(package):
    part = _bracket(package)
    with pytest.raises(Exception, match="//nowhere"):
        part._analysis_implementation(package, cae.FEA, "//nowhere:fea")


def test_the_part_declaration_is_read_as_boundary_conditions(package):
    part = _bracket(package)
    config = cae.config_of(part, cae.FEA)
    assert config.fixtures == {"m3-screw": [cae.EVERY_INSTANCE]}
    assert config.loads["hook"][cae.EVERY_INSTANCE] == pytest.approx(5 * cae.GRAVITY)
    # The other analysis is simply not declared, which is not an error.
    assert cae.config_of(part, cae.CFD) is None


def test_analysing_what_declares_nothing_says_so(package):
    """The sentence the CLI prints and the IDE's tab shows, in one place."""
    import asyncio

    part = _bracket(package)
    with pytest.raises(cae.CaeConfigError, match="declares no 'cfd:' section"):
        asyncio.run(part.analyze_async(package, cae.CFD))


# --------------------------------------------------------------------------- #
# The user configuration                                                      #
# --------------------------------------------------------------------------- #


def test_the_defaults_name_the_public_calculix_package():
    from partcad_utils.user_config import DEFAULT_CAE_IMPLEMENTATIONS, user_config

    assert set(DEFAULT_CAE_IMPLEMENTATIONS) == set(cae.ANALYSES)
    for analysis in cae.ANALYSES:
        assert DEFAULT_CAE_IMPLEMENTATIONS[analysis].endswith(":" + analysis)
        assert user_config.cae_implementation(analysis)


def test_an_unknown_analysis_has_no_configured_implementation():
    from partcad_utils.user_config import user_config

    with pytest.raises(ValueError):
        user_config.cae_implementation("thermal")


# --------------------------------------------------------------------------- #
# The meta-wrapper carries the findings back                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def wrapper_export():
    """Import 'wrappers/wrapper_export.py' without the sandbox around it.

    Same fixture as 'test_output.py' uses, and for the same reason: the module
    imports 'wrapper_common', which needs a CAD stack this process does not
    have. Only that import is stubbed; the wrapper under test is the real one.
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
            "partcad_test_cae_wrapper_export", os.path.join(wrappers, "wrapper_export.py")
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
    path = tmp_path / "solve.py"
    path.write_text(body)
    return str(path)


def test_the_wrapper_carries_findings_back(wrapper_export, tmp_path):
    """An analysis has two outputs, and only one of them is the file."""
    script = _script(
        tmp_path,
        "def process(path, request):\n"
        "    open(path, 'w').write(request['analysis'])\n"
        "    return {'success': True, 'findings': [{'message': 'too thin', 'severity': 'error'}]}\n",
    )
    out = str(tmp_path / "out.glb")
    result = wrapper_export.process(script, out, {"analysis": "fea"})
    assert result["success"] is True
    assert result["findings"] == [{"message": "too thin", "severity": "error"}]
    assert open(out).read() == "fea"


def test_no_findings_is_a_pass_and_carries_nothing(wrapper_export, tmp_path):
    """An empty array does not travel: 'normalize_findings' answers [] anyway."""
    script = _script(tmp_path, "def process(path, request):\n    return {'success': True, 'findings': []}\n")
    result = wrapper_export.process(script, str(tmp_path / "out.glb"), {})
    assert "findings" not in result
    assert cae.normalize_findings(result.get("findings")) == []


def test_an_export_implementation_never_reports_findings(wrapper_export, tmp_path):
    """The key is meaningless outside 'cae:', and must not appear on its own."""
    script = _script(tmp_path, "def process(path, request):\n    return {'success': True}\n")
    result = wrapper_export.process(script, str(tmp_path / "out.step"), {})
    assert set(result) == {"success", "exception"}
