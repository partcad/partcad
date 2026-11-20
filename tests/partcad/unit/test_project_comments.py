#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Comments on a package and on its objects: what the schema takes, how one is written, and what it does not touch.

The grammar of a comment is 'partcad_utils/comments.py' (tested in
'tests/partcad_utils/test_comments.py'); what is pinned here is PartCAD's side
of it -- that every kind of declaration and the package itself may carry one
('partcad.json'), that 'Project.add_comment' writes one into a 'partcad.yaml'
the way somebody would by hand, and that a comment is not what an object is
made of: writing one rebuilds nothing.
"""

import pytest
import yaml

import partcad as pc
from partcad_utils import comments as pc_comments
from partcad_utils.assy_lint import PARTCAD_SCHEMA, get_schema, validate_source

THREAD = """
      - - ref: face:12
          name: Ada Lovelace
          date: 2026-11-19 14:31:01 UTC
          text: |
            This face is **too thin** to print.

            - thicken it
            - or support it
          attachments: [photos/crack.jpg]
        - name: Charles Babbage
          date: 2026-11-19 15:02:44 UTC
          text: Thickened to 2 mm."""

EVERY_KIND = """
name: //commented
comments:
  - - ref: bracket
      name: Ada Lovelace
      date: 2026-11-19 14:31:01 UTC
      text: Release notes go in CHANGELOG.md from now on.
parts:
  bracket:
    type: basic
    cylinder: {radius: 4, height: 10}
    comments:%(thread)s
assemblies:
  frame:
    type: assy
    comments:%(thread)s
scenes:
  room:
    type: assy
    comments:%(thread)s
sketches:
  outline:
    type: basic
    circle: 5
    comments:%(thread)s
interfaces:
  mount:
    desc: a mount
    comments:%(thread)s
software:
  firmware:
    path: firmware.bin
    comments:%(thread)s
providers:
  shop:
    type: store
    comments:%(thread)s
repositories:
  catalog:
    type: basic
    comments:%(thread)s
partTypes:
  gear:
    kind: wrapper
    path: gear.py
    comments:%(thread)s
sketchTypes:
  profile:
    kind: wrapper
    path: profile.py
    comments:%(thread)s
colors:
  red:
    display: "#C91A09"
    comments:%(thread)s
materials:
  alu:
    full: Aluminium
    comments:%(thread)s
finishes:
  satin:
    desc: satin
    comments:%(thread)s
""" % {"thread": THREAD}


def test_every_kind_of_declaration_and_the_package_itself_may_carry_comments():
    assert validate_source(EVERY_KIND, get_schema(PARTCAD_SCHEMA)) == []


@pytest.mark.parametrize(
    "comments",
    [
        # A thread is a list of comments, not a comment.
        "comments:\n  - name: Ada\n    date: 2026-11-19 14:31:01 UTC\n    text: x\n",
        # Who, when and what are not optional.
        "comments:\n  - - name: Ada\n      text: x\n",
        # A date is UTC to the second, as it is written.
        "comments:\n  - - name: Ada\n      date: 2026-11-19T14:31:01Z\n      text: x\n",
        # And a comment is nothing else.
        "comments:\n  - - name: Ada\n      date: 2026-11-19 14:31:01 UTC\n      text: x\n      likes: 3\n",
        # A thread has a comment in it.
        "comments:\n  - []\n",
    ],
)
def test_what_is_not_a_thread_of_comments_is_a_finding(comments):
    assert validate_source(comments, get_schema(PARTCAD_SCHEMA)) != []


def _package(tmp_path, text):
    (tmp_path / "partcad.yaml").write_text(text)
    return pc.Context(str(tmp_path)).get_project("//")


def _read(tmp_path):
    return yaml.safe_load((tmp_path / "partcad.yaml").read_text())


ADA = pc_comments.entry("Ada Lovelace", "Too thin.", ref="face:12", when="2026-11-19 14:31:01 UTC")


def test_a_comment_starts_a_thread_and_a_reply_joins_it(tmp_path):
    project = _package(
        tmp_path,
        "# The package's own words are kept.\nparts:\n  bracket:\n    type: basic  # a cylinder\n"
        "    cylinder: {radius: 4, height: 10}\n",
    )
    assert project.add_comment("part", "bracket", ADA) == 0
    reply = pc_comments.entry(
        "Charles Babbage", "Thickened:\n\n- to 2 mm", ref="face:12", when="2026-11-19 15:02:44 UTC"
    )
    assert project.add_comment("part", "bracket", reply, thread=0) == 0
    assert project.add_comment("part", "bracket", pc_comments.entry("Grace", "And this?")) == 1
    # A reply that does not say what it is about is about what its thread is.
    unsaid = pc_comments.entry("Grace", "Agreed.")
    assert project.add_comment("part", "bracket", unsaid, thread=0) == 0
    assert unsaid["ref"] == "face:12"

    text = (tmp_path / "partcad.yaml").read_text()
    assert "# The package's own words are kept." in text
    assert "type: basic  # a cylinder" in text
    # A comment of more than one line is written the way somebody would by hand.
    assert "text: |" in text
    threads = pc_comments.threads(_read(tmp_path)["parts"]["bracket"])
    assert [[entry["name"] for entry in thread] for thread in threads] == [
        ["Ada Lovelace", "Charles Babbage", "Grace"],
        ["Grace"],
    ]
    assert [entry.get("ref") for entry in threads[0]] == ["face:12"] * 3
    assert "ref" not in threads[1][0]
    assert threads[0][1]["text"] == "Thickened:\n\n- to 2 mm"
    # The date reads back as the text it was written as, not as a timestamp.
    assert threads[0][0]["date"] == "2026-11-19 14:31:01 UTC"
    assert _read(tmp_path)["parts"]["bracket"]["comments"][0][0]["date"] == "2026-11-19 14:31:01 UTC"
    # And the package reads it back, as an object's declaration.
    ctx = pc.Context(str(tmp_path))
    assert len(pc_comments.threads(ctx.get_project("//").object_config("part", "bracket"))) == 2


def test_the_package_itself_is_commented_on_at_the_top(tmp_path):
    project = _package(tmp_path, "parts: {}\n")
    assert project.add_comment(None, None, ADA) == 0
    assert pc_comments.threads(_read(tmp_path))[0][0]["text"] == "Too thin."


@pytest.mark.parametrize(
    "kind, section, declaration, expanded",
    [
        ("part", "parts", "//pub/std:bolt", {"type": "alias", "source": "//pub/std:bolt"}),
        ("interface", "interfaces", "m3-thru", {"alias": "m3-thru"}),
        ("color", "colors", "'#C91A09'", {"display": "#C91A09"}),
        ("material", "materials", "Polylactic Acid", {"full": "Polylactic Acid"}),
        ("software", "software", "firmware.bin", {"path": "firmware.bin"}),
        ("part", "parts", "", {}),
    ],
)
def test_a_declaration_in_its_short_form_is_written_out_first(tmp_path, kind, section, declaration, expanded):
    project = _package(tmp_path, "%s:\n  thing: %s\n" % (section, declaration))
    project.add_comment(kind, "thing", ADA)
    written = _read(tmp_path)[section]["thing"]
    assert {key: value for key, value in written.items() if key != "comments"} == expanded
    assert len(written["comments"]) == 1


def test_nowhere_to_write_it_is_refused_with_nothing_written(tmp_path):
    project = _package(tmp_path, "parts:\n  bracket:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n")
    before = (tmp_path / "partcad.yaml").read_text()
    with pytest.raises(ValueError, match="not declared"):
        project.add_comment("part", "elsewhere", ADA)
    with pytest.raises(ValueError, match="no thread 3"):
        project.add_comment("part", "bracket", ADA, thread=3)
    assert (tmp_path / "partcad.yaml").read_text() == before


def test_a_template_is_not_written_into(tmp_path):
    project = _package(
        tmp_path, "parts:\n  bracket:\n    type: basic\n    cylinder: {radius: {{ 2 * 2 }}, height: 10}\n"
    )
    with pytest.raises(ValueError, match="Jinja2 template"):
        project.add_comment("part", "bracket", ADA)


def test_a_comment_rebuilds_nothing(tmp_path):
    declaration = "parts:\n  bracket:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n"
    plain, commented = tmp_path / "plain", tmp_path / "commented"
    plain.mkdir()
    commented.mkdir()
    (plain / "partcad.yaml").write_text(declaration)
    (commented / "partcad.yaml").write_text(declaration)
    _package(commented, declaration).add_comment("part", "bracket", ADA)
    keys = [pc.Context(str(path)).get_part("bracket").hash.get() for path in (plain, commented)]
    assert keys[0] is not None
    assert keys[0] == keys[1]


@pytest.mark.parametrize("said", ["yes", "off", "0123", "1e3", "null", "- thicken it", "~", "2026-11-19", "> 5"])
def test_a_comment_reads_back_as_the_text_it_was_whatever_yaml_11_makes_of_it(tmp_path, said):
    """ruamel writes YAML 1.2 and PartCAD reads YAML 1.1, where 'yes' is true and '0123' is 83."""
    project = _package(tmp_path, "parts:\n  bracket:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n")
    project.add_comment("part", "bracket", pc_comments.entry("No", said, ref="link#2"))
    from partcad_utils import config_yaml

    (comment,) = config_yaml.load((tmp_path / "partcad.yaml").read_text())["parts"]["bracket"]["comments"][0]
    assert (comment["name"], comment["text"], comment["ref"]) == ("No", said, "link#2")
    assert pc_comments.threads(pc.Context(str(tmp_path)).get_project("//").object_config("part", "bracket")) == [
        [{"ref": "link#2", "name": "No", "date": comment["date"], "text": said}]
    ]


@pytest.mark.parametrize(
    "said", [{"text": "Compare {{ with the previous revision"}, {"name": "{% raw"}, {"attachments": ["a{#b.png"]}]
)
def test_what_the_file_would_render_as_a_template_is_refused_with_nothing_written(tmp_path, said):
    """'partcad.yaml' is read as a Jinja2 template, and one holding '{{' is a file no edit writes into again."""
    project = _package(tmp_path, "parts:\n  bracket:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n")
    before = (tmp_path / "partcad.yaml").read_text()
    with pytest.raises(ValueError, match="Jinja2 template"):
        project.add_comment("part", "bracket", {**ADA, **said})
    assert (tmp_path / "partcad.yaml").read_text() == before


@pytest.mark.parametrize(
    "declarations",
    [
        # One declaration, two names: the comment would be on both.
        "  bracket: &shared\n    type: basic\n    cylinder: {radius: 4, height: 10}\n  copy: *shared\n",
        # Two declarations, one list of threads.
        "  bracket:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n    comments: &said []\n"
        "  copy:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n    comments: *said\n",
    ],
)
def test_what_an_anchor_shares_is_not_written_into(tmp_path, declarations):
    project = _package(tmp_path, "parts:\n" + declarations)
    before = (tmp_path / "partcad.yaml").read_text()
    with pytest.raises(ValueError, match="YAML anchor"):
        project.add_comment("part", "bracket", ADA)
    assert (tmp_path / "partcad.yaml").read_text() == before


def test_an_unshared_declaration_beside_an_anchor_is_written_into(tmp_path):
    project = _package(
        tmp_path,
        "parts:\n  bracket: &shared\n    type: basic\n    cylinder: {radius: 4, height: 10}\n  copy: *shared\n"
        "  bolt:\n    type: basic\n    cylinder: {radius: 1, height: 10}\n",
    )
    assert project.add_comment("part", "bolt", ADA) == 0


def test_a_reply_is_written_only_where_its_thread_still_starts_as_it_did(tmp_path):
    """A thread is named by its position, and one removed before it moves it up."""
    project = _package(tmp_path, "parts:\n  bracket:\n    type: basic\n    cylinder: {radius: 4, height: 10}\n")
    first = pc_comments.entry("Ada Lovelace", "First.", when="2026-11-19 14:31:01 UTC")
    second = pc_comments.entry("Charles Babbage", "Second.", when="2026-11-19 15:02:44 UTC")
    project.add_comment("part", "bracket", first)
    project.add_comment("part", "bracket", second)
    reply = pc_comments.entry("Grace", "Agreed.")
    assert project.add_comment("part", "bracket", dict(reply), thread=1, answering=dict(second)) == 1
    before = (tmp_path / "partcad.yaml").read_text()
    with pytest.raises(ValueError, match="no longer the thread"):
        project.add_comment("part", "bracket", dict(reply), thread=0, answering=dict(second))
    assert (tmp_path / "partcad.yaml").read_text() == before


@pytest.mark.parametrize(
    "section, kind, short", [("colors", "color", "'#C91A09'"), ("materials", "material", "Aluminium 6061")]
)
def test_a_comment_on_a_short_form_judges_nothing_that_uses_it_again(tmp_path, section, kind, short):
    """Writing the first comment on 'red: "#C91A09"' writes the mapping it stands for: the same declaration."""
    from partcad import cmf

    def digest():
        return cmf._declarations_digest(pc.Context(str(tmp_path)), "//")

    _package(tmp_path, "%s:\n  thing: %s\n" % (section, short))
    before = digest()
    pc.Context(str(tmp_path)).get_project("//").add_comment(kind, "thing", ADA)
    assert "comments" in _read(tmp_path)[section]["thing"]
    assert digest() == before
    # What it is, changed, still changes it.
    (tmp_path / "partcad.yaml").write_text(
        (tmp_path / "partcad.yaml").read_text().replace(short.strip("'"), short.strip("'") + "0")
    )
    assert digest() != before
