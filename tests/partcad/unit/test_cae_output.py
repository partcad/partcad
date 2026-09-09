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
from partcad.test.cae import CaeTest

EXAMPLES = "examples"


@pytest.fixture(scope="module")
def ctx():
    """A context over the shipped examples, for the questions about `//builtin`."""
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

PACKAGE = textwrap.dedent("""
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
      nothing:
        # Declared without an 'extension:', which an analysis has no default for:
        # a misconfigured plugin, as opposed to a missing one.
        path: solve.py
    """)


@pytest.fixture
def package(tmp_path, monkeypatch):
    """A package that implements 'fea' itself, so nothing has to be fetched."""
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "solve.py").write_text("def process(path, request):\n    return {'success': True}\n")
    # Not read by anything here: a part is resolved from its declaration, and
    # the geometry is only built when something asks for it.
    (tmp_path / "bracket.step").write_text("")
    ctx = pc.Context(str(tmp_path))
    # Pointed at the package's own implementation, because `CaeTest` now fails a
    # part whose plugin does not resolve -- and the shipped default names the
    # public CalculiX package, which is not here. A test that is about
    # resolution overrides this again.
    monkeypatch.setattr(ctx.user_config, "cae_fea_implementation", "//cae-test:fea")
    return ctx


def _bracket(package):
    """The one part of the fixture package, which declares an `fea:` section."""
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
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//cae-test:fea")
    part = _bracket(package)
    project, format_name = part._analysis_implementation(package, cae.FEA, None)
    assert (project.name, format_name) == ("//cae-test", "fea")


def test_the_default_comes_from_the_context_and_not_the_process(package, monkeypatch):
    """A daemon builds its context from the *caller's* configuration.

    Its own is whatever the environment held when something first started it, so
    reading the process-wide singleton here would run the analysis under the
    daemon's default while `cae.defaults` -- which the IDE pre-fills its field
    from -- reported the caller's. The two would disagree silently, and the
    field would name a solver that did not run.
    """
    from partcad_utils.user_config import user_config as process_wide

    monkeypatch.setattr(process_wide, "cae_fea_implementation", "//wrong:fea")
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//cae-test:fea")

    part = _bracket(package)
    project, _format_name = part._analysis_implementation(package, cae.FEA, None)
    assert project.name == "//cae-test"


def test_an_implementation_may_be_named_for_one_run(package):
    """What `pc cae fea --implementation` and the IDE's field both do."""
    part = _bracket(package)
    project, format_name = part._analysis_implementation(package, cae.FEA, "//cae-test:plot")
    assert (project.name, format_name) == ("//cae-test", "plot")


def test_a_package_on_its_own_means_the_analysis_of_that_package(package):
    """The spelling a package publishing one implementation per analysis gets."""
    part = _bracket(package)
    project, format_name = part._analysis_implementation(package, cae.FEA, "//cae-test")
    assert (project.name, format_name) == ("//cae-test", "fea")


def test_a_missing_implementation_package_says_which_one(package):
    """A package nobody declared as a dependency is named, not just refused."""
    part = _bracket(package)
    with pytest.raises(Exception, match="//nowhere"):
        part._analysis_implementation(package, cae.FEA, "//nowhere:fea")


def test_an_implementation_package_that_did_not_load_says_so(package, monkeypatch):
    """A package that failed to load is reported as that, not as a bad declaration.

    A broken package is not None -- it resolves, carrying an empty configuration
    -- so without this guard the next thing to go wrong is 'analysis_getopts'
    reporting that the implementation declared no 'extension:', which sends the
    reader to look at a file that was never read. A git dependency that could
    not be fetched is what this looks like in practice, and is the common case
    by a distance.
    """
    project = package.get_project("//cae-test")
    monkeypatch.setattr(project, "broken", True)
    part = _bracket(package)
    with pytest.raises(Exception, match="did not load"):
        part._analysis_implementation(package, cae.FEA, "//cae-test:fea")


def test_the_cache_key_follows_the_implementations_own_options(package, tmp_path, monkeypatch):
    """A solver parameter is part of the question, so it has to move the key.

    Most of what a solver is told comes from the *implementing* package's
    defaults rather than from the object's own `cae:` section, so a key built
    from the object's section alone would answer a re-tuned mesh size with the
    verdict from before it was re-tuned.
    """
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//cae-test:fea")
    before = CaeTest(cae.FEA).cache_key_suffix(package, _bracket(package))

    (tmp_path / "partcad.yaml").write_text(PACKAGE.replace("iterations: 3", "iterations: 9"))
    retuned = pc.Context(str(tmp_path))
    retuned.user_config.cae_fea_implementation = "//cae-test:fea"
    after = CaeTest(cae.FEA).cache_key_suffix(retuned, retuned.get_part(":bracket"))

    assert before and after and before != after


def test_the_cache_key_is_its_own_when_the_implementation_does_not_resolve(package, monkeypatch):
    """An unresolved implementation is its own answer and must not borrow a real one's key."""
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//nowhere:fea")
    key = CaeTest(cae.FEA).cache_key_suffix(package, _bracket(package))
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//cae-test:fea")
    assert key != CaeTest(cae.FEA).cache_key_suffix(package, _bracket(package))


def test_the_part_declaration_is_read_as_boundary_conditions(package):
    """The `fea:` section of a real package reaches `partcad.cae` intact."""
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
# The check `pc test` runs                                                    #
# --------------------------------------------------------------------------- #
#
# `CaeTest` has one verdict -- "did the analysis say anything?" -- and three
# ways of not reaching it, which are different failures and have to read as
# different sentences. None of them needs a solver: what runs the analysis is
# `Shape.analyze_async`, and every branch below is what the check does with what
# that returned or raised.


@pytest.fixture(autouse=True)
def a_container_runtime(monkeypatch):
    """Every check below runs as if this machine had one, unless it says not to.

    `CaeTest` has one excuse for not failing an analysis that produced no
    answer, and it is the absence of a container runtime (see
    `CaeTest._verdict`). Left to the real answer, every test here would assert
    the strict contract on a machine with Docker and the lenient one on a
    machine without -- which is the failure a contract test exists to catch,
    applied to itself.
    """
    from partcad import runtime as pc_runtime

    monkeypatch.setattr(pc_runtime, "docker_available", lambda: True)


def _no_container_runtime(monkeypatch, ctx=None, sandbox="venv"):
    """The one machine that is excused, for the tests that are about it.

    The sandbox is pinned too, and not as a formality: `remote` runs the
    implementation in a container on another machine, so it counts as a
    container runtime however little Docker this host has.
    """
    from partcad import runtime as pc_runtime

    monkeypatch.setattr(pc_runtime, "docker_available", lambda: False)
    if ctx is not None:
        monkeypatch.setattr(ctx.user_config, "python_sandbox", sandbox)


def _analysis(part, monkeypatch, result=None, error=None):
    """Stand in for the solver: hand the check a result, or raise at it."""

    async def analyze_async(ctx, analysis, **kwargs):
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(part, "analyze_async", analyze_async)


def test_the_check_passes_a_part_whose_analysis_found_nothing(package, monkeypatch):
    """An empty findings array is the pass. That is the whole verdict."""
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, result={"findings": [], "filepath": "bracket.fea.vtu"})
    assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_PASSED


def test_the_check_fails_a_part_whose_analysis_reported_something(package, monkeypatch, caplog):
    """A finding is the failure, and the report says what was found."""
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, result={"findings": [{"message": "too thin", "severity": "error"}]})
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "too thin" in caplog.text


def test_a_part_that_declares_nothing_is_not_checked(package, monkeypatch):
    """`cfd:` is undeclared on this part, so the CFD check has nothing to say.

    Passing rather than failing is the point: a `pc test -r` over a package tree
    would otherwise fail every bolt in it for not asking to be analysed.
    """
    import asyncio

    part = _bracket(package)

    async def never(*args, **kwargs):
        raise AssertionError("the analysis must not be run for an undeclared section")

    monkeypatch.setattr(part, "analyze_async", never)
    assert asyncio.run(CaeTest(cae.CFD).test([], package, part)) is CaeTest.TEST_PASSED


def test_an_analysis_that_could_not_run_fails(package, monkeypatch, caplog):
    """A plugin that was asked and did not deliver has failed.

    Not a skip. A skip says the question does not apply here; this question
    applies -- the part asked it by declaring `fea:` -- and went unanswered.
    Calling that a pass reports a part as checked when nothing checked it, which
    is how a CFD implementation that never converges stayed green.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "could not be run" in caplog.text
    assert "ccx: not found" in caplog.text


def test_a_sandbox_that_would_not_start_fails_and_names_both_remedies(package, monkeypatch, caplog):
    """`SandboxUnavailable` on a machine that has a container runtime.

    An image that cannot be pulled, or one that will not start, reaches this
    check as the same exception the absence of a runtime does -- and here a
    runtime answers, so it is not that. Something is wrong that somebody can
    fix, and the part asked a question and got no answer.

    What the reader is owed is both ways out, because either fixes it and only
    they know which is easier where they are. The machine with no runtime at all
    is below, and is the one skip this check accepts.
    """
    import asyncio

    from partcad import runtime as pc_runtime

    part = _bracket(package)
    _analysis(part, monkeypatch, error=pc_runtime.SandboxUnavailable("no container runtime is available here"))

    test_ctx = {}
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part, test_ctx)) is CaeTest.TEST_FAILED

    assert "no container runtime is available here" in caplog.text
    assert "start a container runtime" in caplog.text
    assert "install what this implementation needs" in caplog.text
    # Still not remembered: starting a container runtime changes no cache key,
    # so a remembered verdict would outlive its reason.
    assert test_ctx.get(CaeTest.NOT_CACHEABLE) is True


def test_a_missing_solver_fails_the_same_way(package, monkeypatch, caplog):
    """The two used to be opposites; now they are one answer with two remedies.

    Both leave the analysis unrun, and under the current contract that is what
    decides it: the part asked a question and nothing answered.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED


def test_only_the_missing_runtime_carries_the_remedy(package, monkeypatch, caplog):
    """A solver the implementation could not find is the implementation's to explain.

    PartCAD adds the two-remedy line only where it knows both apply -- which is
    where the implementation never ran and so said nothing at all. Adding it to
    every failure would tell somebody whose mesher crashed to start Docker.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    with caplog.at_level("ERROR"):
        asyncio.run(CaeTest(cae.FEA).test([], package, part))

    assert "start a container runtime" not in caplog.text


def test_the_failure_names_the_implementation_and_the_platform(package, monkeypatch, caplog):
    """ "Not installed" is a puzzle; the same sentence with a machine is an answer.

    The reasons an analysis does not run need different actions -- install a
    solver, use another machine, fix the package -- and only the implementation
    knows which. So its sentence is relayed verbatim, and what PartCAD adds is
    the two things it cannot know it is missing: who was asked, and where.
    """
    import asyncio
    import platform

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("gmsh has no wheel for this platform"))
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED

    assert "//cae-test:fea" in caplog.text
    assert platform.machine() in caplog.text
    assert platform.system() in caplog.text
    assert "gmsh has no wheel for this platform" in caplog.text


def test_a_failure_that_may_be_the_machine_is_not_remembered(package, monkeypatch):
    """A verdict that turned on the machine must not outlive the machine.

    The cache key describes the *question* -- the shape, the boundary
    conditions, the implementation and its options -- and nothing in it
    describes whether a solver is installed, because a test cannot know what its
    implementation needs. So installing CalculiX changes no key, and a cached
    failure would go on failing a part that now analyses perfectly well, in
    hundredths of a second, without going near the solver that is now there.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))

    test_ctx = {}
    assert asyncio.run(CaeTest(cae.FEA).test([], package, part, test_ctx)) is CaeTest.TEST_FAILED
    assert test_ctx.get(CaeTest.NOT_CACHEABLE) is True


def test_a_real_verdict_is_remembered(package, monkeypatch):
    """The opt-out is for the unrun analysis alone: one that ran is cacheable.

    Running a solver is the expensive thing `pc test`'s cache exists for, so a
    run that produced an answer -- pass or fail -- has to stay cacheable.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, result={"findings": [], "filepath": "bracket.fea.glb"})
    clean = {}
    assert asyncio.run(CaeTest(cae.FEA).test([], package, part, clean)) is CaeTest.TEST_PASSED
    assert CaeTest.NOT_CACHEABLE not in clean

    part = _bracket(package)
    _analysis(part, monkeypatch, result={"findings": [{"message": "too thin", "severity": "error"}]})
    found = {}
    assert asyncio.run(CaeTest(cae.FEA).test([], package, part, found)) is CaeTest.TEST_FAILED
    assert CaeTest.NOT_CACHEABLE not in found


def test_a_plugin_that_does_not_resolve_fails_the_check(package, monkeypatch, caplog):
    """A named implementation that is not there is wrong everywhere, not here.

    Both ways of not analysing a part fail now, but they are still different
    failures and must read differently: a plugin that cannot be *resolved* --
    not a dependency, misspelt, a package that did not load -- is a fact about
    the configuration, true on every machine, and no amount of installing fixes
    it. It must say which name did not resolve, and it must not start an
    analysis to find out.
    """
    import asyncio

    part = _bracket(package)
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//nowhere:fea")

    async def never(*args, **kwargs):
        raise AssertionError("the analysis must not be started when its plugin is missing")

    monkeypatch.setattr(part, "analyze_async", never)
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "could not be resolved" in caplog.text
    assert "//nowhere" in caplog.text


def test_a_plugin_that_says_nothing_about_its_output_fails_the_check(package, monkeypatch, caplog):
    """A misconfigured plugin is the other half of it, and fails for the same reason.

    The package resolves, and declares a file type that does not say what file it
    writes. An analysis has no default extension to fall back on -- 3D field or
    2D plot is the implementation's decision -- so this is a bug in that package,
    which is not something the machine running `pc test` can mend.
    """
    import asyncio

    part = _bracket(package)
    # 'nothing' is declared with no 'extension:'; see PACKAGE above.
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//cae-test:nothing")
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "could not be resolved" in caplog.text


def test_a_part_may_name_the_plugin_it_was_written_against(package, monkeypatch):
    """`implementation:` on the part outranks the user configuration.

    A part that declares one is saying which solver its numbers were produced
    with, which is a property of the part. It is how a package can ship a working
    analysis without every reader first pointing `caeFeaImplementation`
    somewhere.
    """
    part = _bracket(package)
    monkeypatch.setattr(package.user_config, "cae_fea_implementation", "//nowhere:fea")
    monkeypatch.setitem(part.config["fea"], "implementation", "//cae-test:fea")

    project, format_name = part._analysis_implementation(
        package, cae.FEA, declared=cae.config_of(part, cae.FEA).implementation
    )
    assert project.name == "//cae-test"
    assert format_name == cae.FEA


def test_the_command_line_still_outranks_the_part(package, monkeypatch):
    """'-i' is about this run, so it wins over what the part was written with."""
    part = _bracket(package)
    monkeypatch.setitem(part.config["fea"], "implementation", "//nowhere:fea")
    project, format_name = part._analysis_implementation(
        package, cae.FEA, "//cae-test:plot", declared=cae.config_of(part, cae.FEA).implementation
    )
    assert project.name == "//cae-test"
    assert format_name == "plot"


# --------------------------------------------------------------------------- #
# A relative name belongs to whoever said it                                  #
# --------------------------------------------------------------------------- #
#
# The tree below is the one `pc test -r` walks: a root package, a package under
# it holding the part, and the plugin that package imported. The context is
# created for the root, so the *current* package is the root and not the part's
# -- which is the whole point. `pc test -r --package //pub/examples/partcad` runs
# in exactly that arrangement, and a part deep in the tree that names its plugin
# relatively has to resolve it from where it is rather than from where the
# command was run.

NESTED_ROOT = textwrap.dedent("""
    name: //cae-test
    dependencies:
      pkg:
        type: local
        path: pkg
    """)

NESTED_PACKAGE = textwrap.dedent("""
    dependencies:
      plugin:
        type: local
        path: plugin
    parts:
      bracket:
        type: step
        path: bracket.step
        fea:
          implementation: plugin:fea
          fix:
            - m3-screw
          load:
            hook: 5 kg
    """)

NESTED_PLUGIN = textwrap.dedent("""
    cae:
      fea:
        path: solve.py
        extension: vtu
    """)


@pytest.fixture
def nested(tmp_path):
    """A part one package down, naming a plugin one package further down."""
    (tmp_path / "partcad.yaml").write_text(NESTED_ROOT)
    pkg = tmp_path / "pkg"
    plugin = pkg / "plugin"
    plugin.mkdir(parents=True)
    (pkg / "partcad.yaml").write_text(NESTED_PACKAGE)
    (pkg / "bracket.step").write_text("")
    (plugin / "partcad.yaml").write_text(NESTED_PLUGIN)
    (plugin / "solve.py").write_text("def process(path, request):\n    return {'success': True}\n")

    ctx = pc.Context(str(tmp_path))
    # The premise, asserted rather than assumed: the command is being run at the
    # root, so nothing here resolves 'plugin' by accident.
    assert ctx.get_current_project_path() == "//cae-test"
    part = ctx.get_part("//cae-test/pkg:bracket")
    assert part is not None
    return ctx, part


def test_a_relative_plugin_resolves_against_the_package_that_named_it(nested):
    """'implementation: plugin:fea' means the 'plugin' *that package* imported.

    Resolving it against the current package instead makes the same declaration
    mean different things depending on which directory the command was run from,
    and means nothing at all under 'pc test -r' over a tree -- which runs with
    the tree's root current and every part one or more packages below it.
    """
    ctx, part = nested
    project, format_name = part._analysis_implementation(
        ctx, cae.FEA, declared=cae.config_of(part, cae.FEA).implementation
    )
    assert project.name == "//cae-test/pkg/plugin"
    assert format_name == "fea"


def test_the_check_resolves_a_relative_plugin_from_a_tree_root(nested, monkeypatch):
    """The same thing through 'pc test', which is where it was found.

    A plugin that does not resolve is a failure now, so this is the difference
    between 'Examples (PartCAD)' green and 'Examples (PartCAD)' red.
    """
    import asyncio

    ctx, part = nested
    _analysis(part, monkeypatch, result={"findings": []})
    assert asyncio.run(CaeTest(cae.FEA).test([], ctx, part)) is CaeTest.TEST_PASSED


ROOT_ONLY_PACKAGE = textwrap.dedent("""
    dependencies:
      plugin:
        type: local
        path: plugin
    parts:
      bracket:
        type: step
        path: bracket.step
        fea:
          implementation: plugin:fea
          fix:
            - m3-screw
          load:
            hook: 5 kg
    """)


def test_a_relative_plugin_resolves_from_an_unnamed_root_package(tmp_path):
    """The root package declares no name of its own, so it is called '//'.

    Every package 'pc init' creates is this package, which makes it the shape a
    first relative 'implementation:' is most likely written in -- and the one
    where the name is built by joining onto something that already ends in the
    separator.
    """
    (tmp_path / "partcad.yaml").write_text(ROOT_ONLY_PACKAGE)
    (tmp_path / "bracket.step").write_text("")
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "partcad.yaml").write_text(NESTED_PLUGIN)
    (plugin / "solve.py").write_text("def process(path, request):\n    return {'success': True}\n")

    ctx = pc.Context(str(tmp_path))
    assert ctx.name == "//"
    part = ctx.get_part(":bracket")
    assert part is not None and part.project_name == "//"

    project, _format_name = part._analysis_implementation(
        ctx, cae.FEA, declared=cae.config_of(part, cae.FEA).implementation
    )
    assert project.name == "//plugin"


def test_a_relative_name_on_the_command_line_is_still_the_user_s(nested):
    """'-i plugin:fea' is a name the user typed, so it means what they can see.

    Falling back to the part's package would be convenient exactly once and
    wrong afterwards: 'pc cae fea -i x:fea' would name a different 'x' for every
    part in the run, and the one the user meant for none of them.
    """
    ctx, part = nested
    with pytest.raises(Exception, match="//cae-test/plugin"):
        part._analysis_implementation(ctx, cae.FEA, "plugin:fea", declared=cae.config_of(part, cae.FEA).implementation)


def test_the_cache_key_follows_the_plugin_the_part_names(package, monkeypatch):
    """Re-pointing a part at another solver is a different question.

    The key is built from what the run *is*, and 'implementation:' is part of
    that: two solvers are two answers, and the verdict on one must not be handed
    back for the other.
    """
    part = _bracket(package)
    before = CaeTest(cae.FEA).cache_key_suffix(package, part)
    monkeypatch.setitem(part.config["fea"], "implementation", "//cae-test:plot")
    assert CaeTest(cae.FEA).cache_key_suffix(package, part) != before


def test_a_configuration_error_from_the_analysis_reads_as_one(package, monkeypatch, caplog):
    """Not every bad declaration is caught before the analysis starts.

    `analyze_async` re-reads the section and resolves the implementation, so it
    raises `CaeConfigError` of its own -- and that is a failure of the package,
    not a machine that could not run a solver. The two read differently.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=cae.CaeConfigError("'fea:' names no load"))
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "names no load" in caplog.text
    assert "could not be run" not in caplog.text


def test_a_malformed_section_fails_the_check_with_its_own_sentence(package, monkeypatch, caplog):
    """A package that got the declaration wrong hears why, from `pc test` too."""
    import asyncio

    part = _bracket(package)
    part.config["fea"] = {"load": {"hook": "5 bananas"}}
    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "bananas" in caplog.text


def test_the_cache_key_of_a_malformed_section_is_its_own(package):
    """Correcting the declaration has to re-run, not re-read the old failure."""
    part = _bracket(package)
    good = CaeTest(cae.FEA).cache_key_suffix(package, part)
    part.config["fea"] = {"load": {"hook": "5 bananas"}}
    broken = CaeTest(cae.FEA).cache_key_suffix(package, part)
    assert broken.startswith(".malformed=")
    assert broken != good


def test_an_undeclared_analysis_adds_nothing_to_the_cache_key(package):
    """A shape this check does not apply to keeps the key it already had."""
    assert CaeTest(cae.CFD).cache_key_suffix(package, _bracket(package)) == ""


def test_only_a_part_is_analysed(package):
    """An assembly's members each carry their own conditions; the whole has none."""

    class NotAPart:
        """Anything that is not a `Part` -- an assembly, a sketch, a scene."""

    assert CaeTest(cae.FEA).cache_key_suffix(package, NotAPart()) == ""


# --------------------------------------------------------------------------- #
# The user configuration                                                      #
# --------------------------------------------------------------------------- #


def test_the_defaults_name_the_public_calculix_package():
    """Every analysis has a default, and each names its own file type."""
    from partcad_utils.user_config import DEFAULT_CAE_IMPLEMENTATIONS, user_config

    assert set(DEFAULT_CAE_IMPLEMENTATIONS) == set(cae.ANALYSES)
    for analysis in cae.ANALYSES:
        assert DEFAULT_CAE_IMPLEMENTATIONS[analysis].endswith(":" + analysis)
        assert user_config.cae_implementation(analysis)


def test_an_unknown_analysis_has_no_configured_implementation():
    """Asked about an analysis PartCAD does not run, the configuration says so."""
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
            """The half of `wrapper_common` the wrapper needs, without the CAD stack."""
            return None if exc is None else str(exc)

        @staticmethod
        def handle_exception(exc, script=None):
            """Swallowed here: the real one logs into the sandbox's own channel."""

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
    """An implementation script on disk, for the meta-wrapper to run."""
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


# --------------------------------------------------------------------------- #
# What a failure says, and who says it                                        #
# --------------------------------------------------------------------------- #


def _run_raises(part, monkeypatch, error):
    """Make the part's analysis fail where the implementation would run.

    Patched at `_analysis_run_async` rather than at `analyze_async`, because
    `analyze_async` is the thing under test: it is where the failure is turned
    into the report every caller prints.
    """

    async def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(part, "_analysis_run_async", run)


def test_the_command_is_told_what_the_check_is_told(package, monkeypatch):
    """One report, written where the implementation's name is known.

    `pc test` used to compose this and `pc cae fea` did not, so a user who ran
    the command instead of the check was told less about the same machine. It is
    written once now, in `analyze_async`, and both of them print it.
    """
    import asyncio

    part = _bracket(package)
    _run_raises(part, monkeypatch, Exception("ccx: not found"))

    with pytest.raises(cae.CaeFailed) as raised:
        asyncio.run(part.analyze_async(package, cae.FEA))

    report = str(raised.value)
    # What it said,
    assert "ccx: not found" in report
    # which implementation was asked,
    assert "//cae-test:fea" in report
    # and which machine it did not work on.
    assert "platform:" in report


def test_the_check_prints_that_report_rather_than_writing_its_own(package, monkeypatch, caplog):
    """`pc test` reports what `analyze_async` wrote, and does not wrap it twice."""
    import asyncio

    part = _bracket(package)
    _run_raises(part, monkeypatch, Exception("ccx: not found"))

    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_FAILED
    assert "ccx: not found" in caplog.text
    assert "platform:" in caplog.text
    # Once. Two reports of one failure is what wrapping in both places gives.
    assert caplog.text.count("could not be run by") == 1


def test_no_container_runtime_reaches_the_check_as_itself(package, monkeypatch):
    """The type is what the check reads, even though the verdict is now the same.

    `CaeTest` tells "the implementation could not do it" from "the thing that
    runs implementations is not here" by the exception's type, and attaches the
    two-remedy line to the second. Wrapping this one in a report on the way up
    would lose that and leave the reader one way out of two.
    """
    import asyncio

    from partcad import runtime as pc_runtime

    part = _bracket(package)
    _run_raises(part, monkeypatch, pc_runtime.SandboxUnavailable("no container runtime is available here"))

    with pytest.raises(pc_runtime.SandboxUnavailable):
        asyncio.run(part.analyze_async(package, cae.FEA))


def test_a_malformed_section_stays_a_configuration_error(package, monkeypatch):
    """A part to be edited, not a machine to be equipped: a different answer."""
    import asyncio

    part = _bracket(package)
    _run_raises(part, monkeypatch, cae.CaeConfigError("'load:' names no port"))

    with pytest.raises(cae.CaeConfigError):
        asyncio.run(part.analyze_async(package, cae.FEA))


# --------------------------------------------------------------------------- #
# The one excuse: a machine with no container runtime                         #
# --------------------------------------------------------------------------- #


# Written as a replacement rather than a second literal so that the two packages
# cannot drift: what this fixture is about is the one added line.
CONTAINERISED = PACKAGE.replace(
    "  fea:\n    path: solve.py\n",
    "  fea:\n    path: solve.py\n    dockerImage: ghcr.io/example/solver:1\n",
)
assert "dockerImage" in CONTAINERISED, "the substitution above no longer matches PACKAGE"


@pytest.fixture
def containerised(tmp_path, monkeypatch):
    """The same package, whose `fea:` names the image it runs best in."""
    (tmp_path / "partcad.yaml").write_text(CONTAINERISED)
    (tmp_path / "solve.py").write_text("def process(path, request):\n    return {'success': True}\n")
    (tmp_path / "bracket.step").write_text("")
    ctx = pc.Context(str(tmp_path))
    monkeypatch.setattr(ctx.user_config, "cae_fea_implementation", "//cae-test:fea")
    return ctx


def test_the_declaration_reaches_the_implementation(containerised):
    """The fixture is only worth anything if the image is actually read.

    It is read before anything is materialized, too, which is the case that was
    broken: `analysis_getopts` used to build the implementation without the
    package that declares it, so every `dockerImage` read this early was `None`.
    """
    project = containerised.get_project("//cae-test")
    impl, _ = _bracket(containerised).analysis_getopts(
        containerised, cae.FEA, cae.FEA, project, options_project=project
    )
    assert impl.docker_image == "ghcr.io/example/solver:1"


def test_no_container_runtime_is_a_skip(package, monkeypatch, caplog):
    """Nothing here could have given the implementation what it needs.

    A container is how an implementation brings what pip cannot install -- a
    solver, a mesher, the shared libraries under them -- and nothing else
    PartCAD has can. Where there is no container runtime, no arrangement would
    have run this, so the question was never really put.

    It is not silent. The warning carries the whole dysfunction report -- what
    was asked, what it said, which platform -- because a skip that said less than
    a failure would be a way of not finding out.
    """
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    _no_container_runtime(monkeypatch, package)

    test_ctx = {}
    with caplog.at_level("WARNING"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part, test_ctx)) is CaeTest.TEST_PASSED

    assert "Test skipped" in caplog.text
    assert "ccx: not found" in caplog.text
    assert "no container runtime on this machine" in caplog.text
    # Nothing about the machine belongs in the cache: starting a runtime changes
    # no cache key, so a remembered skip would outlive its reason.
    assert test_ctx.get(CaeTest.NOT_CACHEABLE) is True


def test_a_skip_is_never_logged_as_an_error(package, monkeypatch, caplog):
    """`pc test` exits non-zero on a logged error, and this run succeeded."""
    import asyncio

    part = _bracket(package)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    _no_container_runtime(monkeypatch, package)

    with caplog.at_level("DEBUG"):
        asyncio.run(CaeTest(cae.FEA).test([], package, part))

    assert not [record for record in caplog.records if record.levelname == "ERROR"]


def test_the_skip_names_the_image_when_the_implementation_named_one(containerised, monkeypatch, caplog):
    """Which image would have carried it is the next thing the reader asks.

    The declaration does not decide the verdict -- an implementation is free to
    say nothing about containers and still need a solver -- but where there is
    one it belongs in the message.
    """
    import asyncio

    part = _bracket(containerised)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    _no_container_runtime(monkeypatch, containerised)

    with caplog.at_level("WARNING"):
        assert asyncio.run(CaeTest(cae.FEA).test([], containerised, part)) is CaeTest.TEST_PASSED
    assert "ghcr.io/example/solver:1" in caplog.text


def test_a_container_runtime_that_is_here_leaves_no_excuse(containerised, monkeypatch, caplog):
    """An image that will not pull, or a solver missing from it, is a failure.

    This is the half that makes the skip narrow enough to be worth having, and
    the half continuous integration sees: a runner has a container runtime, so
    every one of these is a failure there. Once a runtime answers, what is left
    is something somebody can fix -- and those are exactly the failures a
    plugin's own CI exists to catch.
    """
    import asyncio

    part = _bracket(containerised)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))

    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], containerised, part)) is CaeTest.TEST_FAILED
    assert "ccx: not found" in caplog.text


def test_a_missing_runtime_is_a_skip_for_the_sandbox_failure_too(package, monkeypatch, caplog):
    """ "The sandbox would not start" and "the solver was missing from it".

    Two ways of arriving at the same place, and they used to be answered in two
    branches that could drift apart. Both go through `_verdict` now, so a machine
    is either equipped or it is not, whichever symptom it showed.
    """
    import asyncio

    from partcad import runtime as pc_runtime

    part = _bracket(package)
    _analysis(part, monkeypatch, error=pc_runtime.SandboxUnavailable("no container runtime is available here"))
    _no_container_runtime(monkeypatch, package)

    with caplog.at_level("WARNING"):
        assert asyncio.run(CaeTest(cae.FEA).test([], package, part)) is CaeTest.TEST_PASSED
    assert "start a container runtime" in caplog.text


def test_a_remote_sandbox_is_a_container_runtime(containerised, monkeypatch, caplog):
    """`pythonSandbox: remote` needs no daemon here, and has one over there.

    The implementation ran in a container; it just was not this machine's. So
    the one excuse does not apply, and reading the local daemon -- which such a
    host may perfectly well not have -- would have excused a real failure on
    every part of every package it builds.
    """
    import asyncio

    part = _bracket(containerised)
    _analysis(part, monkeypatch, error=Exception("ccx: not found"))
    _no_container_runtime(monkeypatch, containerised, sandbox="remote")

    with caplog.at_level("ERROR"):
        assert asyncio.run(CaeTest(cae.FEA).test([], containerised, part)) is CaeTest.TEST_FAILED
    assert "ccx: not found" in caplog.text
