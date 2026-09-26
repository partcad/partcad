#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the `cam:` section: how a route picks its implementation.

`cam:` is an output section of the same shape as `export:` and `render:` and is
resolved by the same code, which is the point of it - and also the risk. What is
checked here is that it stays its own section and resolves the way it says it
does:

* a `cam:` file type is **not** an output format. `pc render -t gcode` must not
  find it, and it must not fall back to a render implementation.
* unlike `cae:`, it has a built-in package, and the shipped default names it.
* the implementation comes from the user configuration by default, is named as
  `<package>:<file type>`, and the file it writes is named after the object
  alone - `panel.nc`, because an object has one route at a time.

No machine and no sandbox: everything here stops at the point where the script
would be run.
"""

import asyncio
import os
import textwrap

import pytest

import partcad as pc
from partcad import cam, output

EXAMPLES = "examples"


@pytest.fixture(scope="module")
def ctx():
    """A context over the shipped examples, for the questions about `//builtin`."""
    return pc.Context(EXAMPLES)


# --------------------------------------------------------------------------- #
# The section is its own                                                      #
# --------------------------------------------------------------------------- #


def test_cam_is_not_an_output_section():
    """'pc export'/'pc render' must not offer a route as a file type."""
    assert output.CAM not in output.SECTIONS
    assert output.CAM in output.ALL_SECTIONS


def test_cam_is_not_an_analysis_either():
    """A route makes the object; an analysis reports on one. Nothing may confuse them."""
    assert output.CAM not in output.ANALYSIS_SECTIONS
    assert output.CAE not in output.MANUFACTURING_SECTIONS


def test_cam_has_no_fallback_section():
    """A render implementation cannot stand in for a post-processor, or the reverse."""
    assert output.config_sections(output.CAM) == (output.CAM,)
    assert output.CAM not in output.config_sections(output.EXPORT)
    assert output.CAM not in output.config_sections(output.RENDER)


def test_a_route_is_not_a_known_output_format(ctx):
    """'gcode' is not something 'pc render -t' or 'pc export -t' can name."""
    assert output.section_of(ctx, "gcode") is None
    assert "gcode" not in output.all_formats(ctx)


# --------------------------------------------------------------------------- #
# Unlike an analysis, PartCAD ships one                                       #
# --------------------------------------------------------------------------- #


def test_cam_has_a_builtin_package(ctx):
    """A route is arithmetic on the object's own outline, so it ships here.

    This is the one place `cam:` and `cae:` genuinely differ, and it is what
    makes `pc cam` work in a package that says nothing about machines.
    """
    assert output.BUILTIN_PACKAGES[output.CAM] == "//builtin/cam"
    assert output.builtin_project(ctx, output.CAM) is not None
    assert "gcode" in output.builtin_formats(ctx, output.CAM)


def test_the_builtin_route_declares_what_it_writes(ctx):
    """An implementation that does not say is a bug in that package.

    There is no default extension for a route to fall back on -- what a
    controller reads is the implementation's decision -- so the shipped one has
    to state it.
    """
    gcode = output.builtin_formats(ctx, output.CAM)["gcode"]
    assert gcode["extension"] == "nc"
    assert gcode["path"] == "cam_gcode.py"


def test_the_builtin_route_declares_no_tool(ctx):
    """The one parameter that cannot be guessed from the part is not defaulted.

    Every other parameter has a defensible default; a route produced against a
    cutter diameter nobody chose is wrong by exactly the amount nobody noticed.
    """
    assert "tool" not in output.builtin_formats(ctx, output.CAM)["gcode"]


def test_the_default_implementation_is_the_builtin_one(ctx):
    assert ctx.user_config.cam_implementation == "//builtin/cam:gcode"


# --------------------------------------------------------------------------- #
# Resolving an implementation                                                 #
# --------------------------------------------------------------------------- #

PACKAGE = textwrap.dedent("""
    name: //cam-test
    parts:
      stock:
        type: step
        path: panel.step
      panel:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 6 mm
          depth: 18 mm
      lid:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 3 mm
          implementation: //cam-test:router
      plain:
        type: step
        path: panel.step
      broken:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: six millimetres
      burned:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 6 mm
          depth: 18 mm
          laser:
            kerf: 0.15
      burned_upward:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 6 mm
          depth: 18 mm
          laser:
            kerf: 0.15
            toolAxis: +Z
      two_machines:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 6 mm
          depth: 18 mm
          laser:
            kerf: 0.15
          drill:
            peck: 3
    cam:
      gcode:
        feed: 2400
        depth_per_pass: 3
      router:
        path: route.py
        extension: tap
        feed: 900
      nothing:
        # Declared without an 'extension:', which a route has no default for: a
        # misconfigured plugin, as opposed to a missing one.
        path: route.py
    """)


@pytest.fixture
def package(tmp_path):
    """A package that declares a route implementation of its own."""
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "route.py").write_text("def process(path, request):\n    return {'success': True}\n")
    # Not read by anything here: a part is resolved from its declaration, and
    # the geometry is only built when something asks for it.
    (tmp_path / "panel.step").write_text("")
    return pc.Context(str(tmp_path))


def _part(package, name):
    part = package.get_part(":" + name)
    assert part is not None
    return part


def test_a_route_is_named_after_the_object_alone(package):
    """'panel.nc', not 'panel.cam.nc': an object has one route at a time.

    The extension already says what the file is, which is what separates this
    from an analysis -- a part has as many results as it has analyses, so those
    carry the analysis in the name.
    """
    part = _part(package, "panel")
    impl, filepath = part.cam_getopts(package, "gcode", package.get_project("//cam-test"))
    assert os.path.basename(filepath) == "panel.nc"
    assert impl.section == output.CAM


def test_the_package_layer_re_tunes_the_builtin_one(package):
    """What a package sets under its own `cam:` covers every object in it.

    The built-in package is the bottom layer, so a package that changes one
    parameter keeps the built-in implementation for everything else -- which is
    the whole reason a route is configured as an output file type.
    """
    part = _part(package, "panel")
    impl, _ = part.cam_getopts(package, "gcode", package.get_project("//cam-test"))
    assert impl.parameters["feed"] == 2400
    assert impl.parameters["safe_z"] == 5
    assert impl.script == "cam_gcode.py"


def test_an_implementation_that_does_not_say_what_it_writes_is_refused(package):
    part = _part(package, "panel")
    with pytest.raises(Exception) as raised:
        part.cam_getopts(package, "nothing", package.get_project("//cam-test"))
    assert "extension" in str(raised.value)


def test_the_object_outranks_the_user_configuration(package):
    """An object naming an implementation is saying which machine it was written for."""
    part = _part(package, "lid")
    config = cam.config_of(part)
    assert config.implementation == "//cam-test:router"
    options_project, format_name = part._route_implementation(package, None, declared=config.implementation)
    assert (options_project.name, format_name) == ("//cam-test", "router")


def test_the_command_line_outranks_the_object(package):
    """'-i' is the most specific thing anybody said, so it wins."""
    part = _part(package, "lid")
    options_project, format_name = part._route_implementation(package, "//cam-test:gcode", declared="//cam-test:router")
    assert (options_project.name, format_name) == ("//cam-test", "gcode")


def test_a_package_on_its_own_means_its_gcode(package):
    """What a package publishing one route implementation is most likely to call it."""
    part = _part(package, "panel")
    options_project, format_name = part._route_implementation(package, "//cam-test")
    assert (options_project.name, format_name) == ("//cam-test", "gcode")


def test_an_implementation_in_a_package_that_is_not_there_says_so(package):
    part = _part(package, "panel")
    with pytest.raises(Exception) as raised:
        part._route_implementation(package, "//nowhere:gcode")
    assert "is not found" in str(raised.value)


def test_an_unresolvable_implementation_fails_only_the_object_it_is_on(package):
    """It reaches `route_async`'s caller as a `CamConfigError`, and that is what
    keeps it from costing the rest of the package its routes.

    A package-level run gathers every object's outcome and re-raises anything it
    does not recognise as an answer. So while resolution happened *outside* the
    block that gives failures their type, one object naming an implementation
    that is not installed aborted the whole request and discarded the routes
    already produced for every other object in the package.
    """
    part = _part(package, "panel")
    with pytest.raises(pc.cam.CamConfigError) as raised:
        asyncio.run(part.route_async(package, implementation="//nowhere:gcode"))
    message = str(raised.value)
    # Named against the object, so a package-wide run says which one it was.
    assert "cam-test:panel" in message
    assert "could not be resolved" in message


# --------------------------------------------------------------------------- #
# Which objects a package-level run visits                                    #
# --------------------------------------------------------------------------- #


def test_a_package_run_visits_the_objects_that_declare_a_section(package):
    """The `cam:` section is the opt-in, and the whole of it.

    `broken` is in the list although its section cannot be read: deciding what
    to visit must not raise on one object's mistake, or a package where one
    part has a typo produces no routes at all instead of nineteen and a report.
    That is why `cam.declared_config()` exists beside `config_of()`.

    `two_machines` is in it for the same reason and a second one: naming the
    machine unreadably is refused by `route_async`, not by the enumeration --
    so it is visited, and it reports.
    """
    project = package.get_project("//cam-test")
    routable = asyncio.run(project.routable_shapes_async())
    assert sorted(shape.name for shape in routable) == [
        "broken",
        "burned",
        "burned_upward",
        "lid",
        "panel",
        "two_machines",
    ]


def test_an_object_asked_for_by_name_is_visited_whatever_it_declares(package):
    """The refusal belongs to `route_async()`, which says which object and which section.

    Naming an object is asking about that object; coming back with nothing would
    make `pc cam :plain` look exactly like a route that went somewhere the user
    did not notice.
    """
    project = package.get_project("//cam-test")
    routable = asyncio.run(project.routable_shapes_async(parts=["plain"]))
    assert [shape.name for shape in routable] == ["plain"]


def test_a_broken_section_is_reported_against_the_object_it_is_on(package):
    """A run over a package prints one line per object, so each needs an address.

    "'cam: tool:' is not a length" against forty parts is a sentence with no
    address on it. `partcad.cam` deliberately knows nothing about shapes, so the
    naming happens where the object is known -- once, on the way out of
    `route_async()`.
    """
    part = _part(package, "broken")
    with pytest.raises(cam.CamConfigError) as raised:
        asyncio.run(part.route_async(package))
    message = str(raised.value)
    assert message.startswith("//cam-test:broken: ")
    assert "is not a length" in message


def test_an_object_with_no_section_says_so_by_name(package):
    """Naming an object is asking about it, so "nothing to route" names it back."""
    part = _part(package, "plain")
    with pytest.raises(cam.CamConfigError) as raised:
        asyncio.run(part.route_async(package))
    assert "//cam-test:plain says nothing about being cut" in str(raised.value)


# --------------------------------------------------------------------------- #
# The `cam` check `pc test` runs                                              #
# --------------------------------------------------------------------------- #
#
# `CamTest` asks one question -- produce the route, and see whether one comes
# back -- so what is worth testing is the three ways that can end and the cache
# key that decides when it is asked again. The route itself is
# `test_cam_gcode.py`'s subject; here `route_async` is replaced, because what
# this check does with an answer is the whole of it.


def _cam_check():
    from partcad.test.cam import CamTest

    return CamTest()


def test_the_check_is_selected_by_its_own_name():
    """`pc test -f` filters by name prefix, and nothing else starts with `cam`.

    It is the half of the rename that makes the split usable: `-f
    manufacturability` selects that check and its seven siblings, `-f cam`
    selects this one alone.
    """
    from partcad.test.all import tests as all_tests

    names = [test.name for test in all_tests(4)]
    assert "cam" in names
    assert [name for name in names if name.startswith("cam")] == ["cam"]
    assert sorted(name for name in names if name.startswith("manufacturability")) == [
        "manufacturability",
        "manufacturability-additive",
        "manufacturability-cut",
        "manufacturability-drill",
        "manufacturability-forming",
        "manufacturability-laser",
        "manufacturability-sheet-metal",
        "manufacturability-subtractive",
    ]


def test_an_object_that_declares_nothing_is_not_this_check_s_business(package):
    """Declaring `cam:` is how a user says "check this one".

    Without that, `pc test -r` over a package tree would start a CAD sandbox for
    every bolt in it, and a bolt has no outline a machine could follow.
    """
    check = _cam_check()
    part = _part(package, "plain")
    assert check._config(part) is None
    assert asyncio.run(check.test([], package, part)) is check.TEST_PASSED
    # Nothing was asked, so there is nothing to remember about it either.
    assert asyncio.run(check.cache_key_suffix(package, part)) == ""


def test_a_malformed_section_fails_the_object_rather_than_crashing(package):
    """The object asked to be cut and got the request wrong, which is a failure
    of the package -- said here so a user finds out without running `pc cam`."""
    check = _cam_check()
    part = _part(package, "broken")
    assert asyncio.run(check.test([], package, part)) is check.TEST_FAILED


def test_a_malformed_section_gets_a_cache_key_of_its_own(package):
    """Correcting it has to produce a fresh run rather than the failure of what
    it replaced."""
    check = _cam_check()
    broken = asyncio.run(check.cache_key_suffix(package, _part(package, "broken")))
    good = asyncio.run(check.cache_key_suffix(package, _part(package, "panel")))
    assert broken.startswith(".malformed=")
    assert good.startswith(".cam=")
    assert broken != good


def test_two_different_jobs_are_two_different_questions(package):
    """An object whose tool has just been halved must not be answered with the
    verdict on the old one -- and the job does not move `shape.hash`."""
    check = _cam_check()
    panel = asyncio.run(check.cache_key_suffix(package, _part(package, "panel")))
    lid = asyncio.run(check.cache_key_suffix(package, _part(package, "lid")))
    assert panel != lid


def test_a_route_that_was_written_is_the_one_way_to_pass(package, monkeypatch):
    check = _cam_check()
    part = _part(package, "panel")

    async def _routed(self, ctx, **kwargs):
        # Into a directory of the check's own, which it removes afterwards.
        assert os.path.isdir(kwargs["output_dir"])
        return {"filepath": os.path.join(kwargs["output_dir"], "panel.nc"), "stats": {"paths": 1}}

    monkeypatch.setattr(pc.shape.Shape, "route_async", _routed)
    assert asyncio.run(check.test([], package, part)) is check.TEST_PASSED


def test_an_implementation_that_was_asked_and_did_not_answer_has_failed(package, monkeypatch):
    """Not a skip: a skip says the question does not apply here, and an object
    that declares `cam:` has asked one."""
    check = _cam_check()
    part = _part(package, "panel")

    async def _blew_up(self, ctx, **kwargs):
        raise Exception("the tool is bigger than the hole")

    monkeypatch.setattr(pc.shape.Shape, "route_async", _blew_up)
    test_ctx = {}
    assert asyncio.run(check.test([], package, part, test_ctx)) is check.TEST_FAILED
    # Nothing in the key describes the machine, so this verdict is not kept.
    assert test_ctx[check.NOT_CACHEABLE] is True


def test_a_sandbox_that_could_not_be_built_skips_rather_than_fails(package, monkeypatch):
    """The one verdict that would be about this machine rather than the object:
    there is no arrangement under which the implementation could have run."""
    from partcad import runtime as pc_runtime

    check = _cam_check()
    part = _part(package, "panel")

    async def _no_sandbox(self, ctx, **kwargs):
        raise pc_runtime.SandboxUnavailable("no conda, no venv, no docker")

    monkeypatch.setattr(pc.shape.Shape, "route_async", _no_sandbox)
    test_ctx = {}
    result = asyncio.run(check.test([], package, part, test_ctx))
    assert result is not check.TEST_FAILED
    # Not remembered: installing what the machine lacked changes no cache key,
    # so a remembered skip would outlive its reason.
    assert test_ctx[check.NOT_CACHEABLE] is True


def test_the_route_a_check_produced_is_not_left_beside_the_package(package, monkeypatch):
    """It would be indistinguishable from the one `pc cam` writes -- checked in
    by accident, or read as current long after the part moved on."""
    check = _cam_check()
    part = _part(package, "panel")
    seen = {}

    async def _routed(self, ctx, **kwargs):
        seen["output_dir"] = kwargs["output_dir"]
        return {"filepath": os.path.join(kwargs["output_dir"], "panel.nc"), "stats": {}}

    monkeypatch.setattr(pc.shape.Shape, "route_async", _routed)
    asyncio.run(check.test([], package, part))

    assert seen["output_dir"] not in (None, "")
    assert not os.path.exists(seen["output_dir"]), "the check's temporary directory outlived it"


#
# Which machine the route is for
#


def test_a_part_that_named_no_machine_puts_nothing_in_the_request(package):
    """The case that must stay exactly as it was.

    An implementation handed no machine writes what it has always written, so a
    part with no `manufacturing:` section at all is untouched by any of this.
    A `subtractive` part that named no machine is a different case: it gets the
    undeclared CNC, which is what it always meant, and `_orient` is the identity
    for its `-Z` so the bytes are the same either way.
    """
    assert _part(package, "plain")._route_machine_data() == {}


def test_the_machine_a_part_named_reaches_the_request(package):
    """The whole of what a declared machine contributes: kind, axis, options."""
    data = _part(package, "burned")._route_machine_data()
    assert data["machine"] == "laser"
    assert data["tool_axis"] == "-Z"
    assert data["kerf"] == 0.15


def test_a_part_naming_two_machines_is_asked_which_one(package):
    """They are alternatives, so there is a choice and nobody else can make it.

    Defaulting would be the one outcome worse than refusing: a program for a
    machine the user did not pick, written in the format of one they did not
    ask for. The sentence names what there is to choose between.
    """
    with pytest.raises(cam.CamConfigError) as raised:
        cam.config_of(_part(package, "two_machines"))
    message = str(raised.value)
    assert "chosen" in message
    assert "laser" in message and "drill" in message


def test_either_alternative_can_be_asked_for_by_name(package):
    """Each names its own machine and carries its own parameters."""
    part = _part(package, "two_machines")
    assert part._route_machine_data("laser")["machine"] == "laser"
    assert part._route_machine_data("laser")["kerf"] == pytest.approx(0.15)
    assert part._route_machine_data("drill")["machine"] == "drill"
    # The shared scope reaches both; the machine's own scope is its alone.
    assert cam.config_of(part, "drill").values["peck"] == pytest.approx(3.0)
    assert cam.config_of(part, "laser").values["diameter"] == pytest.approx(6.0)


def test_a_machine_the_part_does_not_name_is_refused(package):
    with pytest.raises(cam.CamConfigError) as raised:
        cam.config_of(_part(package, "two_machines"), "cnc")
    assert "not made on a 'cnc'" in str(raised.value)


def test_the_refusal_is_named_with_the_object_it_is_about(package, monkeypatch):
    """`route_async` already wraps this, which is why it is raised bare.

    A run over a package reports one line per object, so the sentence has to
    carry an address -- see `_cam_config_error`.
    """
    part = _part(package, "two_machines")

    with pytest.raises(cam.CamConfigError) as raised:
        asyncio.run(part.route_async(package))
    message = str(raised.value)
    assert message.startswith("//cam-test:two_machines: ")
    assert "chosen" in message


def test_the_machine_is_in_the_cam_checks_cache_key(package):
    """Moving a part from a router to a laser is a different program.

    `manufacturing:` is one of the keys a shape's hash deliberately leaves out,
    so without this the laser part is handed the pass the router route earned
    and the laser route is never produced at all.
    """
    check = _cam_check()
    routed = asyncio.run(check.cache_key_suffix(package, _part(package, "panel")))
    burned = asyncio.run(check.cache_key_suffix(package, _part(package, "burned")))
    assert routed and burned and routed != burned


def test_the_tool_axis_is_in_the_cam_checks_cache_key(package):
    """The same solid cut from the other side is the other program."""
    check = _cam_check()
    down = asyncio.run(check.cache_key_suffix(package, _part(package, "burned")))
    up = asyncio.run(check.cache_key_suffix(package, _part(package, "burned_upward")))
    assert down and up and down != up


def test_an_unreadable_machine_keys_on_its_own_error(package):
    """A refusal is a verdict, and correcting it has to produce a fresh run."""
    check = _cam_check()
    confused = asyncio.run(check.cache_key_suffix(package, _part(package, "two_machines")))
    burned = asyncio.run(check.cache_key_suffix(package, _part(package, "burned")))
    assert confused and confused != burned


def test_two_alternatives_written_into_one_directory_get_two_files(package, tmp_path, monkeypatch):
    """`-O routes` must not resolve both machines to one path.

    `cam_getopts()` reads an existing directory as the *output directory* and
    derives the filename from the object -- the same filename whichever machine
    was asked for. So a suffix applied only when no path was given at all left
    `pc cam -O routes -m laser` and `-m cnc` pointing at one file, and since a
    route deletes the path before writing it, the second one silently replaced
    the first while the run reported two.

    Stopped at the point the path is settled: what is under test is the name,
    and running the implementation would need a sandbox this test has no use for.
    """
    part = _part(package, "two_machines")
    seen = []

    def _record(path):
        seen.append(path)
        raise RuntimeError("stop here")

    monkeypatch.setattr(package, "ensure_dirs_for_file", _record)
    target = tmp_path / "routes"
    target.mkdir()

    for machine in ("laser", "drill"):
        with pytest.raises(Exception):
            asyncio.run(part.route_async(package, filepath=str(target), machine=machine))

    assert [os.path.basename(path) for path in seen] == ["two_machines.laser.nc", "two_machines.drill.nc"]
    assert len(set(seen)) == 2


def test_a_path_the_caller_named_is_the_path_it_gets(package, tmp_path, monkeypatch):
    """The other side of it: a file named explicitly is not renamed under the caller.

    `-O` names a directory and PartCAD chooses the filename in it; a `filepath`
    naming a *file* is the caller having chosen already, and a machine suffix
    there would be PartCAD overruling them.
    """
    part = _part(package, "two_machines")
    seen = []

    def _record(path):
        seen.append(path)
        raise RuntimeError("stop here")

    monkeypatch.setattr(package, "ensure_dirs_for_file", _record)
    named = str(tmp_path / "whatever.nc")

    with pytest.raises(Exception):
        asyncio.run(part.route_async(package, filepath=named, machine="laser"))
    assert seen == [named]
