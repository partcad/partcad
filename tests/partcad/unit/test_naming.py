#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How a PartCAD name becomes a name a file format accepts, and back: 'wrappers/naming.py'.

The transcoder on rules made up for the purpose, then the rules the core
declares itself -- URDF's, beside its exporter, and a file name's -- and the URDF
export of a scene whose bodies have names URDF has to write differently. The
MJCF and SDFormat rules are their plugins', and are tested there.
"""

import os
import re
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "export"))
import export_urdf  # noqa: E402
import kinematics  # noqa: E402
import naming  # noqa: E402

# A format of the narrow kind: ASCII and three punctuation marks, one reserved
# name and one reserved pattern, as SDFormat's are.
NARROW = naming.Rules(
    "Narrow",
    allowed=re.compile(r"[A-Za-z0-9_.-]"),
    forbidden=("..",),
    reserved=("world",),
    reserved_patterns=(r"__.*__",),
)


def test_a_valid_name_is_its_own_internal_name():
    names = naming.Transcoder(NARROW)
    for name in ("cube", "cube-2", "_private", "a.b", "Shoulder_Pan"):
        assert names.claim(name) == name
    assert names.renamed() == []
    # The whole of what an XML attribute can carry, for a format that restricts nothing more.
    anything = naming.Transcoder(naming.Rules("Anything"))
    assert anything.claim("//pub/x:y z;w=1") == "//pub/x:y z;w=1"
    assert anything.claim("колесо") == "колесо"


def test_characters_the_format_does_not_allow_become_one_underscore_each_run():
    assert naming.transcode(NARROW, "//pub/examples:logo") == "pub_examples_logo"
    assert naming.transcode(NARROW, "a b\tc") == "a_b_c"
    assert naming.transcode(NARROW, "a::b") == "a_b"
    # Only what this put there comes off the ends; a name's own underscore stays.
    assert naming.transcode(NARROW, "_x_") == "_x_"
    assert naming.transcode(NARROW, " x ") == "x"
    # A forbidden substring of allowed characters goes too.
    assert naming.transcode(NARROW, "a..b") == "a_b"
    # Nothing left is the fallback.
    assert naming.transcode(NARROW, "//", "link") == "link"
    assert naming.transcode(NARROW, None, "link") == "link"
    # Control characters are never written, whatever the format allows.
    assert naming.transcode(naming.Rules("Anything"), "a\nb") == "a_b"


def test_a_reserved_name_is_told_apart_like_a_taken_one():
    names = naming.Transcoder(NARROW)
    assert names.claim("world", "body") == "world-2"
    assert names.claim("__model__", "body") == "__model__-2"
    assert not NARROW.valid("world") and not NARROW.valid("__x__")
    assert NARROW.valid("world-2") and NARROW.valid("__x")
    # The format's own use of the name is the exporter's to take.
    assert names.reserve("world") == "world"
    assert names.renamed() == [("body", "world", "world-2"), ("body", "__model__", "__model__-2")]


def test_two_names_that_become_one_are_told_apart_in_the_order_they_are_claimed():
    names = naming.Transcoder(NARROW)
    assert [names.claim("a b"), names.claim("a:b"), names.claim("a_b")] == ["a_b", "a_b-2", "a_b-3"]
    # 'a_b' was valid and still lost: it was claimed last.
    assert names.partcad("a_b-3") == "a_b"


def test_a_name_is_the_same_each_time_it_is_asked_for_and_kinds_are_apart():
    names = naming.Transcoder(NARROW)
    assert names.claim("hinge", "body") == "hinge"
    assert names.claim("hinge", "joint") == "hinge-2"
    assert names.claim("hinge", "body") == "hinge"
    assert names.internal("hinge", "joint") == "hinge-2"
    assert names.internal("nothing", "joint") is None
    assert names.mapping() == {"body": {"hinge": "hinge"}, "joint": {"hinge": "hinge-2"}}


def test_a_derived_name_yields_to_a_partcad_name_claimed_before_it():
    names = naming.Transcoder(NARROW)
    names.claim_all(["cube", "cube_link"], "body")
    assert names.derive("cube_link") == "cube_link-2"
    # Derived names are fresh every time and stand for no PartCAD name.
    assert names.derive("cube_link") == "cube_link-3"
    assert names.partcad("cube_link-2") is None
    assert names.internal("cube_link", "body") == "cube_link"


def test_a_name_given_back_can_be_taken_again():
    names = naming.Transcoder(NARROW)
    taken = names.claim("empty", "body")
    names.release(taken)
    assert names.internal("empty", "body") is None and names.mapping() == {}
    assert names.derive("empty") == "empty"


def test_a_long_name_is_cut_and_still_told_apart():
    short = naming.Rules("Short", allowed=re.compile(r"[a-z_-]"), max_length=5)
    names = naming.Transcoder(short)
    assert [names.claim("abcdefgh"), names.claim("abcdexyz"), names.claim("ab")] == ["abcde", "abc-2", "ab"]
    assert all(len(name) <= 5 for name in names.mapping()[""].values())


def test_a_namespace_too_short_for_another_suffix_says_so_rather_than_overrun():
    names = naming.Transcoder(naming.Rules("Two", allowed=re.compile(r"[a-z_-]"), max_length=2))
    assert [names.claim("a")] + [names.derive("a") for _ in range(8)] == ["a"] + ["-%d" % n for n in range(2, 10)]
    with pytest.raises(ValueError):
        # '-10' is three characters, and every shorter name 'a' could become is taken.
        names.derive("a")


@pytest.mark.parametrize("rules", [dict(forbidden=("_",)), dict(forbidden=("",)), dict(allowed=re.compile(r"[a-z-]"))])
def test_rules_that_no_mended_name_could_meet_are_refused(rules):
    with pytest.raises(ValueError):
        naming.Rules("Impossible", **rules)


def test_a_format_that_ignores_case_has_cube_and_cube_as_one_name():
    names = naming.Transcoder(naming.Rules("Folded", case_sensitive=False, reserved=("World",)))
    assert [names.claim("Cube"), names.claim("cube"), names.claim("WORLD")] == ["Cube", "cube-2", "WORLD-2"]


def test_the_same_names_in_the_same_order_are_the_same_names():
    def run():
        names = naming.Transcoder(NARROW)
        out = [names.claim(name, "body") for name in ("world", "a b", "a_b", "x", "x")]
        out.append(names.derive("x"))
        return out, names.mapping()

    assert run() == run()


def test_a_separator_the_format_cannot_hold_is_refused():
    with pytest.raises(ValueError):
        naming.Transcoder(naming.Rules("Letters", allowed=re.compile(r"[a-z]")))


def test_a_file_name_answers_to_every_filesystem_it_may_be_copied_to():
    meshes = naming.Transcoder(naming.FILE_NAMES, "_", 1)
    # Windows and macOS do not tell these two apart, and Windows keeps 'con'.
    assert [meshes.derive("Cube"), meshes.derive("cube"), meshes.derive("con"), meshes.derive("com1.part")] == [
        "Cube",
        "cube_1",
        "con_1",
        "com1_part",
    ]
    assert meshes.derive("wrist/1") == "wrist_1"
    assert len(meshes.derive("x" * 300)) == naming.FILE_NAMES.max_length


def test_the_sidecar_is_written_beside_the_file_and_read_back(tmp_path):
    path = tmp_path / "scene.xml"
    written = naming.write_sidecar(
        str(path),
        "mjcf",
        {"body": {"world": "world-2"}},
        {"world": {"path": ["world-2"]}},
        {"swing": {"path": ["swing"], "joint": "swing", "start": 30.0}},
    )
    assert written == str(path) + ".names.json" == naming.sidecar_path(str(path))
    read = naming.read_sidecar(str(path))
    assert read["format"] == "mjcf" and read["names"] == {"body": {"world": "world-2"}}
    # An entry is open: a key a later exporter adds is carried, not refused.
    assert read["joints"]["swing"]["start"] == 30.0
    assert naming.read_sidecar(str(tmp_path / "other.xml")) is None
    (tmp_path / "bad.xml.names.json").write_text("{not json", encoding="utf-8")
    assert naming.read_sidecar(str(tmp_path / "bad.xml")) is None
    (tmp_path / "new.xml.names.json").write_text('{"version": 99}', encoding="utf-8")
    assert naming.read_sidecar(str(tmp_path / "new.xml")) is None


#
# URDF's rules, which the core declares beside its exporter
#


def test_an_export_without_a_sidecar_leaves_none_from_an_earlier_one(tmp_path):
    path = tmp_path / "scene.xml"
    naming.write_sidecar(path, "mjcf", {"body": {"a b": "a_b"}})
    naming.remove_sidecar(path)
    assert naming.read_sidecar(path) is None
    naming.remove_sidecar(path)  # and having none is no failure


def test_urdf_reserves_the_world_and_what_sdformat_reserves():
    rules = export_urdf.URDF_NAMES
    assert [rules.valid(name) for name in ("world", "__model__", "a b", "a/b", "base_link", "leg-2")] == [
        False,
        False,
        False,
        False,
        True,
        True,
    ]


def _scene(*labels):
    return {
        "name": "pkg:room",
        "label": "world",
        "kind": "scene",
        "assembly": [
            {"name": "pkg:%d" % index, "label": label, "kind": "part", "brep": b"%d" % index}
            for index, label in enumerate(labels)
        ],
    }


def test_a_urdf_body_called_world_is_written_under_another_name_and_said_to_be():
    planned = export_urdf.Planner(kinematics.bodies(_scene("world", "cube", "a b"))).plan()
    links = [link.name for link in planned.links]
    # The URDF's own 'world', which every free body hangs off, keeps the name.
    assert links == ["world", "world-2", "cube", "a_b"]
    assert [(joint.parent, joint.child) for joint in planned.joints] == [
        ("world", "world-2"),
        ("world", "cube"),
        ("world", "a_b"),
    ]
    (said,) = [warning for warning in planned.warnings if "does not accept" in warning]
    assert "'world' as 'world-2'" in said and "'a b' as 'a_b'" in said and "'cube'" not in said


def test_a_massless_link_yields_its_name_to_a_body_called_that():
    """A chain's massless link is '<joint>_link1', unless a body somebody named that has it."""
    import urdf_common

    from .test_kinematics import Y, Z, free

    joint = {"name": "j", "parent": "base", "child": "j_link1", "steps": [free("turn", Z), free("turn", Y)]}
    tree = {
        "name": "pkg:rig",
        "label": "rig",
        "kind": "assembly",
        "assembly": [
            {"name": "pkg:base", "label": "base", "kind": "part", "brep": b"b"},
            {
                "name": "pkg:arm",
                "label": "j_link1",
                "kind": "part",
                "brep": b"a",
                "location": urdf_common.to_packed(kinematics.Joint(joint).location()),
                "joint": joint,
            },
        ],
    }
    planned = export_urdf.Planner(kinematics.bodies(tree), {"composites": "massless"}).plan()
    assert [(link.name, link.massless) for link in planned.links] == [
        ("base", False),
        ("j_link1-2", True),
        ("j_link1", False),
    ]
