#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for 'pc adhoc render' -- rendering a file that belongs to no package.

The rendering itself is the same machinery 'pc render' drives and is covered
there; what is new here is the ad-hoc half. Two things have to hold for it to
mean anything:

- the projections it offers are the ones PartCAD actually implements, since
  any other file type comes from a package named with '-e', and
- the formats that only mean something inside a package are refused, pointing at
  the command that does have one.

And what it takes that 'pc render' takes has to mean the same thing: a
parameter value is declared on the input with the type it is written in, a
package to read a file type from is imported into the throwaway package, and a
file nobody named is named after the input with its values, the way 'pc render'
names an instance's.

None of it needs a sandbox.
"""

import contextlib
import errno
import os
import pathlib
import stat
import sys
from pathlib import Path, PureWindowsPath

import pytest
import ruamel.yaml

import partcad as pc
from partcad import output
from partcad.adhoc import adhoc
from partcad.adhoc import render as adhoc_render
from partcad.shape import PART_EXTENSION_MAPPING, RENDER_EXTENSION_MAPPING, SERIALIZED_PART_TYPES

# What the thin CLI offers. Inlined there so it does not import the heavy
# partcad package; imported here so the copy cannot drift.
from partcad_cli.click.commands.adhoc.render.part import PART_TYPES as CLI_PART_INPUT_TYPES
from partcad_cli.click.commands.adhoc.render.part import RENDER_TYPES as CLI_PART_RENDER_TYPES
from partcad_cli.click.commands.adhoc.render.sketch import RENDER_TYPES as CLI_SKETCH_RENDER_TYPES

# --------------------------------------------------------------------------- #
# What can be written                                                         #
# --------------------------------------------------------------------------- #


def test_the_cli_offers_exactly_the_projections_that_can_be_rendered():
    assert sorted(CLI_PART_RENDER_TYPES) == sorted(adhoc_render.PART_RENDER_FORMATS)
    assert sorted(CLI_SKETCH_RENDER_TYPES) == sorted(adhoc_render.SKETCH_RENDER_FORMATS)


def test_the_projections_are_the_ones_with_a_known_extension():
    """The output type is inferred from the file name, so the two have to agree.

    'RENDER_EXTENSION_MAPPING' is what 'adhoc_render' reads in reverse to tell
    from 'out.png' which projection was asked for. A format offered but missing
    from it could be asked for by name and never inferred; one in the mapping but
    not offered would be inferred and then refused.
    """
    assert sorted(adhoc_render.PART_RENDER_FORMATS) == sorted(RENDER_EXTENSION_MAPPING)


def test_the_extensions_are_what_the_builtin_package_declares():
    """'//builtin/render' is what actually writes the files, so it decides.

    A drift here is a file written with one extension and looked for under
    another.
    """
    ctx = pc.init("examples")
    declared = output.builtin_formats(ctx, output.RENDER)
    for format_name, extension in RENDER_EXTENSION_MAPPING.items():
        assert declared[format_name]["extension"] == extension, format_name


def test_a_projection_is_still_not_a_part_type():
    """Widening the render mapping must not make 'convert()' offer a picture.

    A projection cannot be read back in as a part, which is why the render
    formats are a mapping of their own rather than an entry in the part types.
    """
    for format_name in ("png", "jpeg"):
        assert format_name not in PART_EXTENSION_MAPPING
        assert format_name not in SERIALIZED_PART_TYPES


# --------------------------------------------------------------------------- #
# What cannot be rendered ad-hoc                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("input_type", ["urdf", "assy"])
def test_an_assembly_format_is_refused_and_points_at_the_package_command(tmp_path, input_type):
    """Neither means anything without the package its contents are named in."""
    source = tmp_path / ("robot.%s" % input_type)
    source.write_text("<robot name='r'><link name='a'/></robot>")

    with pytest.raises(ValueError) as excinfo:
        adhoc_render.render_cad_file(str(source), input_type, str(tmp_path / "out.png"), "png")

    message = str(excinfo.value)
    assert "only means anything inside a package" in message
    # The advice is the render one, not the conversion one: the user asked for a
    # picture, so 'pc convert assembly' is not what they want next.
    assert "pc render" in message
    assert "Cannot render from" in message


def test_the_cli_accepts_every_part_type_as_input():
    """A projection can be made of anything PartCAD can read, including the
    scripted types it cannot write back out -- 'sdf', 'scad' and 'chili3d' are
    input-only for a conversion but perfectly renderable."""
    for input_only in ("sdf", "scad", "chili3d"):
        assert input_only in CLI_PART_INPUT_TYPES


# --------------------------------------------------------------------------- #
# What 'pc render' takes, ad hoc                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, declared",
    [
        ("true", {"type": "bool", "default": True}),
        ("False", {"type": "bool", "default": False}),
        ("12", {"type": "int", "default": 12}),
        ("-3", {"type": "int", "default": -3}),
        ("6.5", {"type": "float", "default": 6.5}),
        ("1e3", {"type": "float", "default": 1000.0}),
        ("M4", {"type": "string", "default": "M4"}),
        # Python reads these as numbers; nobody writing them means one.
        ("nan", {"type": "string", "default": "nan"}),
        ("inf", {"type": "string", "default": "inf"}),
        ("", {"type": "string", "default": ""}),
        (["10", "20.5"], {"type": "array", "default": [10, 20.5]}),
    ],
)
def test_a_value_is_declared_with_the_type_it_is_written_in(text, declared):
    assert adhoc.declare_parameter(text) == declared


def _config(tmp_path, **options):
    adhoc.generate_partcad_config(tmp_path, "build123d", tmp_path / "bracket's.py", **options)
    return ruamel.yaml.YAML(typ="safe").load((tmp_path / "partcad.yaml").read_text(encoding="utf-8"))


def test_the_throwaway_package_declares_the_input_alone_by_default(tmp_path):
    assert _config(tmp_path) == {"parts": {"input_part": {"type": "build123d", "path": str(tmp_path / "bracket's.py")}}}


def test_the_values_are_declared_on_the_input(tmp_path):
    config = _config(tmp_path, parameters={"depth": "12", "label": "M4: 'hex'"})

    assert config["parts"]["input_part"]["parameters"] == {
        "depth": {"type": "int", "default": 12},
        "label": {"type": "string", "default": "M4: 'hex'"},
    }


def test_the_package_to_read_a_file_type_from_is_imported(tmp_path):
    (tmp_path / "opts").mkdir()
    (tmp_path / "opts" / "partcad.yaml").write_text("render: {}\n", encoding="utf-8")
    dependency, name = adhoc.options_dependency(str(tmp_path / "opts"))

    config = _config(tmp_path, dependencies=dict([dependency]))

    assert name == "//options"
    assert config["dependencies"] == {"options": {"type": "local", "path": str((tmp_path / "opts").resolve())}}


def test_a_package_of_the_public_index_is_imported_the_way_pc_init_imports_the_index():
    """The same declaration as a new package's, so that the importer treats it the same way."""
    (name, declaration), package = adhoc.options_dependency("//pub/feature/render/draftwright")
    template = Path(output.__file__).parent / "template" / "init-public.yaml"
    pub = ruamel.yaml.YAML(typ="safe").load(template.read_text(encoding="utf-8"))["dependencies"]["pub"]

    assert (name, package) == ("pub", "//pub/feature/render/draftwright")
    assert declaration == pub


# --------------------------------------------------------------------------- #
# A package name, or a directory                                              #
# --------------------------------------------------------------------------- #


# The modules a look at the disk passes through on its way from the code under
# test to the operating system ('pathlib' is a package from 3.13 on).
_PATH_MODULES = {"os", "posixpath", "ntpath", "genericpath", "pathlib"}


def _called_by_the_code_under_test():
    """Whether the call being intercepted was made by 'adhoc', directly or through pathlib or 'os.path'.

    And not by anything else in the process: these replace functions everybody
    shares -- 'os.stat', pathlib's -- and the obvious other caller is not a
    thread but a tracer. Coverage looks up the file of a function the first
    time it sees it called, with 'os.path.realpath', in the thread that called
    it; in a fresh xdist worker that function can be 'options_dependency'
    itself, called under the guard. Told apart by module name rather than by
    where a file is: in a virtual environment the standard library's
    'platstdlib' is the one that holds 'site-packages'.
    """
    frame = sys._getframe(2)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if module == adhoc.__name__:
            return True
        if module.split(".")[0] not in _PATH_MODULES:
            return False
        frame = frame.f_back
    return False


def _for_the_code_under_test(patch, owner, name, replacement):
    """Replace 'owner.name' for calls '_called_by_the_code_under_test'; every other caller gets the original."""
    original = getattr(owner, name)

    def dispatch(*args, **kwargs):
        """The replacement for the code under test, and the original for everything else."""
        if _called_by_the_code_under_test():
            return replacement(*args, **kwargs)
        return original(*args, **kwargs)

    patch.setattr(owner, name, dispatch)


@contextlib.contextmanager
def _no_disk(monkeypatch):
    """Fail loudly on anything that would look at a file, a directory or a share.

    Every way 'options_dependency' could ask: pathlib's methods, which on 3.10
    to 3.13 go through 'Path.stat', and the 'os' functions they call on 3.14
    ('os.path.isdir' and 'os.path.isfile', which on Windows are 'nt' builtins
    that never reach 'os.stat'). A context of its own rather than the test's
    'monkeypatch', so that it covers the one call and nothing after it.
    """

    def touched(*args, **kwargs):
        raise AssertionError("looked on disk, or on the network: %r" % (args,))

    with monkeypatch.context() as patch:
        for name in ("stat", "lstat", "exists", "is_dir", "is_file", "resolve", "absolute", "iterdir"):
            _for_the_code_under_test(patch, pathlib.Path, name, touched)
        for name in ("stat", "lstat", "scandir", "listdir"):
            _for_the_code_under_test(patch, os, name, touched)
        for name in ("exists", "isdir", "isfile", "realpath"):
            _for_the_code_under_test(patch, os.path, name, touched)
        yield


def _stat_result(mode):
    """What 'os.stat' answers for a file of 'mode' ('stat.S_IFDIR', 'stat.S_IFREG'), the rest of it zeroes."""
    return os.stat_result((mode | 0o755,) + (0,) * 9)


@contextlib.contextmanager
def _fake_disk(monkeypatch, *packages, failing=None, error=None):
    """A disk holding a package directory at each of 'packages' and nothing else; yields what was asked of it.

    Asked the way 'options_dependency' asks, with 'Path.stat', which answers
    what the operating system does: the file, or 'FileNotFoundError'. Or, for
    the path 'failing', 'error' -- what a directory the user may not read, or a
    share that went away, answers instead.
    """
    asked = []

    def stat_of(self, *args, **kwargs):
        """The directory or 'partcad.yaml' this disk holds at 'self', or the error the OS would raise."""
        asked.append(str(self))
        if failing is not None and str(self) == str(failing):
            raise error
        if str(self) in packages:
            return _stat_result(stat.S_IFDIR)
        if self.name == "partcad.yaml" and str(self.parent) in packages:
            return _stat_result(stat.S_IFREG)
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(self))

    with monkeypatch.context() as patch:
        _for_the_code_under_test(patch, pathlib.Path, "stat", stat_of)
        _for_the_code_under_test(patch, pathlib.Path, "resolve", lambda self, *args, **kwargs: self)
        yield asked


@pytest.mark.parametrize("named", ["//elsewhere/render", "//elsewhere", "//", "//pubs/render"])
def test_a_package_an_ad_hoc_render_cannot_reach_is_refused(monkeypatch, named):
    """'//' is how PartCAD names a package, and one outside the public index has no workspace to be found in.

    Refused for what the name is, without looking for it: the same text is a
    path as well, and on Windows '//elsewhere/render' is a network share --
    looking for it asks the network for a server called 'elsewhere', which can
    be slow, can fail ('[WinError 64] The specified network name is no longer
    available' did, on a CI runner), and can even succeed. So the refusal is
    the same on every machine only if nothing is looked at, and that is what is
    asserted, not merely that it is refused.
    """
    with _no_disk(monkeypatch):
        with pytest.raises(adhoc.AdhocUsageError) as excinfo:
            adhoc.options_dependency(named)

    message = str(excinfo.value)
    assert "'%s'" % named in message
    assert "//pub/" in message
    assert "is a package" in message


@pytest.mark.parametrize("named", ["//pub", "//pub/feature/render/draftwright"])
def test_a_package_of_the_public_index_is_reached_by_name_alone(monkeypatch, named):
    """The other half of the same rule: what is in the index is never looked for on disk either."""
    with _no_disk(monkeypatch):
        (dependency, _), package = adhoc.options_dependency(named)

    assert (dependency, package) == ("pub", named)


def test_a_package_name_is_not_read_as_the_directory_it_spells(monkeypatch, tmp_path):
    """A package directory written with a leading '//' is a package name, even where the OS would find the directory.

    POSIX leaves a leading '//' to the implementation, and Linux and macOS read
    '//tmp/x' as '/tmp/x': before the name was told apart by its spelling, this
    imported the directory on those systems, and asked the network for it on
    Windows -- one name meaning three things depending on where it ran.
    """
    package = tmp_path / "opts"
    package.mkdir()
    (package / "partcad.yaml").write_text("render: {}\n", encoding="utf-8")
    spelled = "//" + package.as_posix().lstrip("/")
    if os.name == "posix":
        # What makes the case worth having: the OS would have found it.
        assert os.path.samefile(spelled, package)

    with _no_disk(monkeypatch):
        with pytest.raises(adhoc.AdhocUsageError):
            adhoc.options_dependency(spelled)


def test_a_directory_on_a_network_share_is_a_directory_when_written_as_windows_writes_it(monkeypatch):
    """A package kept on a share is a package on this machine, so '\\\\server\\share\\...' is looked at.

    It is also what 'os.path.abspath' makes of a relative '-e drawing' typed in
    a working directory on a share, which the CLI sends absolute. The
    forward-slash spelling of that same share -- one location to Windows, as
    'PureWindowsPath' says -- is PartCAD's spelling of a package name, and is
    refused unlooked-at, even with a package at the share it would mean.
    """
    backslashes, slashes = r"\\server\share\drawing", "//server/share/drawing"
    assert PureWindowsPath(backslashes) == PureWindowsPath(slashes)
    assert PureWindowsPath(slashes).drive == r"\\server\share"

    with _fake_disk(monkeypatch, backslashes) as asked:
        dependency, package = adhoc.options_dependency(backslashes)
    assert dependency == ("options", {"type": "local", "path": backslashes})
    assert package == "//options"
    assert backslashes in asked

    with _fake_disk(monkeypatch, backslashes, slashes) as asked:
        with pytest.raises(adhoc.AdhocUsageError):
            adhoc.options_dependency(slashes)
    assert asked == []


# Relative as a client speaking the protocol may send it, and absolute as the CLI does.
@pytest.mark.parametrize("named", ["no/such/directory", "{tmp}/missing"])
def test_a_directory_that_is_not_there_is_refused(tmp_path, named):
    """Anything not spelled as a package is a directory, looked for, and refused when it holds none."""
    with pytest.raises(adhoc.AdhocUsageError) as excinfo:
        adhoc.options_dependency(named.format(tmp=tmp_path))

    assert "//pub/" in str(excinfo.value)


@pytest.mark.parametrize("failing", ["directory", "partcad.yaml"])
@pytest.mark.parametrize(
    "error",
    [
        PermissionError(errno.EACCES, "Permission denied"),
        # What a share that drops the connection raises on Windows: winerror 64,
        # which Python maps to EINVAL -- not "absent", so not "no package here".
        OSError(errno.EINVAL, "The specified network name is no longer available"),
    ],
    ids=["permission", "network"],
)
def test_a_directory_that_cannot_be_looked_at_is_refused_with_the_reason(monkeypatch, tmp_path, failing, error):
    """A usage error that says why, rather than a traceback out of the render or a refusal that does not.

    Whichever of the two looks fails: at the directory, or at the
    'partcad.yaml' in it. Asserted against 'Path.stat', what the code asks,
    which raises what the operating system answers on every Python -- where
    'Path.is_dir' and 'Path.is_file' answer False for any error from 3.14 on,
    and asking them would have refused this with no reason given.
    """
    directory = tmp_path / "drawing"
    path = directory if failing == "directory" else directory / "partcad.yaml"

    with _fake_disk(monkeypatch, str(directory), failing=path, error=error) as asked:
        with pytest.raises(adhoc.AdhocUsageError) as excinfo:
            adhoc.options_dependency(str(directory))

    assert str(path) in asked
    assert excinfo.value.__cause__ is error
    assert str(error) in str(excinfo.value)
    assert "//pub/" in str(excinfo.value)


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0,
    reason="needs a directory this process may not read: POSIX permissions, which root is exempt from",
)
def test_a_directory_the_user_may_not_read_is_refused_with_the_reason(tmp_path):
    """The case above as the operating system really answers it, with no Python in between taking it apart.

    A package directory whose permissions let nobody in: looking for its
    'partcad.yaml' is 'Permission denied', which is the reason given -- on
    every Python, including those whose 'Path.is_file' would have answered
    False for it and had it refused as an empty directory.
    """
    directory = tmp_path / "drawing"
    directory.mkdir()
    (directory / "partcad.yaml").write_text("render: {}\n", encoding="utf-8")
    directory.chmod(0)
    try:
        # What the test needs is a directory this process cannot read, and
        # not being root is only the usual way to have one: a process with
        # CAP_DAC_OVERRIDE, or a filesystem that ignores permissions, reads
        # through mode 0 all the same, and then there is nothing to refuse.
        try:
            (directory / "partcad.yaml").stat()
        except PermissionError:
            pass
        else:
            pytest.skip("this process reads a directory whatever its permissions say")
        with pytest.raises(adhoc.AdhocUsageError) as excinfo:
            adhoc.options_dependency(str(directory))
    finally:
        directory.chmod(0o755)

    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert "could not be looked at" in str(excinfo.value)


def test_a_symlink_loop_met_while_resolving_is_refused_with_the_reason(monkeypatch, tmp_path):
    """Up to Python 3.12 'Path.resolve' says "symlink loop" with 'RuntimeError', not 'OSError'.

    It is asked last, once 'stat' has found the package, so a loop there is one
    made in between; it is still a usage error with its reason, not a traceback.
    """
    directory = tmp_path / "drawing"
    error = RuntimeError("Symlink loop from %r" % str(directory))

    def loops(self, *args, **kwargs):
        """'Path.resolve' as Python 3.10 to 3.12 answer a symlink loop."""
        raise error

    with _fake_disk(monkeypatch, str(directory)):
        with monkeypatch.context() as patch:
            _for_the_code_under_test(patch, pathlib.Path, "resolve", loops)
            with pytest.raises(adhoc.AdhocUsageError) as excinfo:
                adhoc.options_dependency(str(directory))

    assert excinfo.value.__cause__ is error
    assert "Symlink loop" in str(excinfo.value)


def test_a_directory_with_no_package_in_it_is_refused(tmp_path):
    with pytest.raises(adhoc.AdhocUsageError):
        adhoc.options_dependency(str(tmp_path))


def test_no_package_imports_nothing():
    assert adhoc.options_dependency(None) == (None, None)


@pytest.mark.parametrize(
    "parameters, extension, name",
    [
        (None, ".svg", "bracket.svg"),
        ({"depth": "12", "hole": "6.5"}, ".svg", "bracket_depth_12_hole_6.5.svg"),
        # Sorted by name, as 'pc render' writes an instance's, whatever order they came in.
        ({"hole": "6.5", "depth": "12"}, ".thin.svg", "bracket_depth_12_hole_6.5.thin.svg"),
        ({"medium": "//pub/std:air"}, ".png", "bracket_medium_pub_std_air.png"),
    ],
)
def test_a_file_nobody_named_is_named_after_the_input_and_its_values(tmp_path, parameters, extension, name):
    assert adhoc.default_output_name(tmp_path / "bracket.py", parameters, extension) == name


def test_the_values_are_written_into_a_name_as_pc_render_writes_them():
    """One rule for both: what an object's instance is called on disk, and what an ad-hoc file of it is."""
    values = {"length": "10", "size": "M4"}
    assert output.name_to_segments("bolt;length=10,size=M4") == ["bolt" + output.values_in_file_name(values)]
    assert output.values_in_file_name({}) == ""
    assert output.values_in_file_name(values) == "_length_10_size_M4"


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_file_an_output_was_for_is_named_after_the_input(tmp_path):
    staging, destination = tmp_path / "staging", tmp_path / "out"
    destination.mkdir()
    _write(staging / "input_part.thin.svg", "<svg/>")

    delivered = adhoc.deliver(staging, destination, "input_part", tmp_path / "bracket.py", {"depth": "12"})

    assert delivered == str(destination / "bracket_depth_12.thin.svg")
    assert (destination / "bracket_depth_12.thin.svg").read_text(encoding="utf-8") == "<svg/>"


def test_what_an_output_wrote_beside_its_file_goes_with_it(tmp_path):
    """A URDF and the meshes it names: the meshes keep the names and the paths it names them by."""
    staging, destination = tmp_path / "staging", tmp_path / "out"
    destination.mkdir()
    _write(staging / "input_part.urdf", "<robot/>")
    _write(staging / "meshes" / "link_0.stl")
    _write(staging / "input_part_link_1.stl")

    delivered = adhoc.deliver(staging, destination, "input_part", tmp_path / "arm.step")

    assert delivered == str(destination / "arm.urdf")
    assert sorted(str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()) == sorted(
        ["arm.urdf", str(Path("meshes") / "link_0.stl"), "input_part_link_1.stl"]
    )


def test_nothing_written_is_nothing_delivered(tmp_path):
    (tmp_path / "staging").mkdir()
    assert adhoc.deliver(tmp_path / "staging", tmp_path, "input_part", tmp_path / "bracket.py") is None
