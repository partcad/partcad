#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One name, one object: what a package's object names are, and how a bare name is found.

A name is one object of a package whatever its kind (see
'partcad_utils.object_names'), which is what lets a command take ``bolt``
without being told whether it is a part or an assembly. Three things are held
here: the rule itself, as both ends read it; a package that breaks it, which
keeps the name for one declaration and refuses the others; and the lookup
('Project.object_kind'), which asks what is in memory about every kind before
it asks a repository anything, and then asks the most frequent kinds first.
"""

import asyncio

import pytest

import partcad as pc
from partcad.project_external_repository import ProjectExternalRepository
from partcad_utils import object_names

# ---- the rule --------------------------------------------------------------


def test_the_kinds_are_looked_for_most_frequent_first():
    assert object_names.NAMED_KINDS == ("part", "interface", "assembly", "sketch", "scene", "software")


def test_the_kind_looked_for_first_keeps_the_name():
    found = object_names.duplicates(
        {
            "sketch": {"m3": {"type": "basic"}},
            "interface": {"m3": {}},
        }
    )
    assert found == [object_names.Duplicate("sketch", "m3", None, "interface", None)]
    assert object_names.message(found[0]) == (
        "'m3' is already the name of an interface in this package, and a name means one object of a package "
        "whatever its kind: rename one of them"
    )


def test_an_alias_is_a_name_like_any_other():
    found = object_names.duplicates(
        {
            "part": {"bolt": {"type": "step", "aliases": ["screw"]}},
            "scene": {"screw": {"type": "assy"}},
            "sketch": {"outline": {"aliases": ["bolt"]}},
        }
    )
    assert found == [
        object_names.Duplicate("sketch", "bolt", "outline", "part", None),
        object_names.Duplicate("scene", "screw", None, "part", "bolt"),
    ]
    assert "the alias 'bolt' of the sketch 'outline'" in object_names.message(found[0])
    assert "a part (an alias of 'bolt')" in object_names.message(found[1])


def test_a_parametrized_declaration_names_its_aliases_with_its_parameters():
    names = list(object_names.claimed_names({"bolt;length=10": {"aliases": ["screw"]}}))
    assert names == [("bolt;length=10", None), ("screw;length=10", "bolt;length=10")]


def test_one_kind_is_not_compared_with_itself_nor_with_a_kind_nobody_has_listed():
    # Two keys of one mapping cannot share a name, and an alias that clashes
    # with its own kind is refused as it is made ('Project.register_object').
    assert object_names.duplicates({"part": {"bolt": {"aliases": ["bolt"]}}}) == []
    # None is "not known yet", which a plugin-backed package says of a kind it
    # has not listed: it is left out rather than read as empty.
    assert object_names.duplicates({"part": None, "sketch": {"bolt": {}}}) == []


# ---- a package that breaks it ----------------------------------------------


def _package(tmp_path, text):
    (tmp_path / "partcad.yaml").write_text(text)
    return pc.Context(str(tmp_path)).get_project("//")


def test_a_package_keeps_the_name_for_the_kind_looked_for_first(tmp_path):
    project = _package(
        tmp_path,
        "sketches:\n"
        "  m3:\n"
        "    type: basic\n"
        "    circle: 1.5\n"
        "interfaces:\n"
        "  m3:\n"
        "    desc: An interface\n",
    )

    assert project.object_kind("m3") == "interface"
    # Refused, and said why, where every broken declaration is said.
    assert "already the name of an interface" in project.get_broken_object_reason("sketch", "m3")
    assert project.object_names("sketch") == []
    assert not project.declares_object("sketch", "m3")
    assert project.get_sketch("m3", quiet=True) is None


def test_a_refused_object_says_it_is_refused_rather_than_missing(tmp_path, caplog):
    project = _package(
        tmp_path,
        "sketches:\n  m3:\n    type: basic\n    circle: 1.5\ninterfaces:\n  m3:\n    desc: An interface\n",
    )

    assert project.get_sketch("m3") is None
    assert "is refused: 'm3' is already the name of an interface" in caplog.text
    assert "not found" not in caplog.text


def test_an_alias_another_kind_has_the_name_of_is_not_made(tmp_path):
    project = _package(
        tmp_path,
        "interfaces:\n"
        "  screw:\n"
        "    desc: An interface\n"
        "sketches:\n"
        "  outline:\n"
        "    type: basic\n"
        "    circle: 1.5\n"
        "    aliases: [screw, round]\n",
    )

    assert project.object_kind("screw") == "interface"
    assert project.object_kind("round") == "sketch"
    assert project.alias_declared_by("sketch", "screw") is None
    assert project.alias_declared_by("sketch", "round") == "outline"
    assert "already the name of an interface" in project.get_broken_object_reason("sketch", "screw")


def test_a_parametrized_declaration_s_refused_alias_is_not_made(tmp_path):
    """Its aliases carry its parameters, and are refused under the name they carry."""
    (tmp_path / "round.assy").write_text("links: []\n")
    project = _package(
        tmp_path,
        "assemblies:\n"
        "  'round;r=2':\n"
        "    type: assy\n"
        "    path: round.assy\n"
        "sketches:\n"
        "  'outline;r=2':\n"
        "    type: basic\n"
        "    circle: 2\n"
        "    aliases: [round]\n",
    )

    assert "already the name of an assembly" in project.get_broken_object_reason("sketch", "round;r=2")
    assert "outline;r=2" in project.sketches
    assert "round;r=2" not in project.objects("sketch")


def test_a_declaration_left_out_by_unless_takes_no_name(tmp_path):
    project = _package(
        tmp_path,
        "sketches:\n"
        "  m3:\n"
        "    type: basic\n"
        "    circle: 1.5\n"
        "interfaces:\n"
        "  m3:\n"
        "    desc: An interface for a machine nobody has\n"
        "    unless: [linux, macos, windows]\n",
    )

    assert project.object_kind("m3") == "sketch"
    assert project.get_broken_object_reason("sketch", "m3") is None


def test_adding_an_object_under_a_name_another_kind_has_is_refused(tmp_path):
    project = _package(tmp_path, "interfaces:\n  m3:\n    desc: An interface\n")
    before = (tmp_path / "partcad.yaml").read_text()

    assert project.name_taken("sketch", "m3") is not None
    assert project.name_taken("interface", "m3") is None, "a kind does not clash with itself"
    assert project.name_taken("material", "m3") is None, "a material has a namespace of its own"
    assert project.add_object_config("sketches", "m3", {"type": "basic", "circle": 1.5}) is False
    assert (tmp_path / "partcad.yaml").read_text() == before

    assert project.add_object_config("sketches", "m3-boundary", {"type": "basic", "circle": 1.5}) is True
    assert "m3-boundary" in (tmp_path / "partcad.yaml").read_text()


# ---- finding a bare name ---------------------------------------------------


EVERY_KIND = (
    "parts:\n"
    "  bolt:\n"
    "    type: step\n"
    "    path: bolt.step\n"
    "    aliases: [screw]\n"
    "    parameters:\n"
    "      length: 10.0\n"
    "interfaces:\n"
    "  thread:\n"
    "    desc: An interface\n"
    "assemblies:\n"
    "  robot:\n"
    "    type: step\n"
    "    path: robot.step\n"
    "sketches:\n"
    "  outline:\n"
    "    type: basic\n"
    "    circle: 1.5\n"
    "scenes:\n"
    "  stage:\n"
    "    type: assy\n"
    "    path: stage.assy\n"
    "software:\n"
    "  firmware:\n"
    "    path: firmware.bin\n"
)


@pytest.fixture
def every_kind(tmp_path):
    for name in ("bolt.step", "robot.step", "stage.assy", "firmware.bin"):
        (tmp_path / name).write_text("")
    return _package(tmp_path, EVERY_KIND)


@pytest.mark.parametrize(
    "name, kind",
    [
        ("bolt", "part"),
        ("bolt;length=5", "part"),
        ("screw", "part"),
        # What a STEP assembly materializes is a part, declared nowhere.
        ("robot/link", "part"),
        ("thread", "interface"),
        ("robot", "assembly"),
        ("outline", "sketch"),
        ("stage", "scene"),
        ("firmware", "software"),
        ("nothing", None),
    ],
)
def test_a_bare_name_is_found_whatever_it_is(every_kind, name, kind):
    assert every_kind.object_kind(name) == kind
    assert asyncio.run(every_kind.object_kind_async(name)) == kind


def test_a_lookup_narrowed_to_some_kinds_finds_nothing_else(every_kind):
    assert every_kind.object_kind("outline", ("part", "assembly")) is None
    assert every_kind.object_kind("robot", ("scene", "assembly")) == "assembly"


def test_the_context_finds_a_name_in_the_package_it_names(every_kind):
    assert every_kind.ctx.get_object_kind("//:robot") == "assembly"
    assert every_kind.ctx.get_object_kind("robot") == "assembly"


# ---- a package a plugin serves: the cheap questions first -------------------


class FakeRepository:
    """Stands in for a repository plugin, and records what it is asked."""

    def __init__(self, data):
        self.data = data
        self.keys = []

    async def get_data(self, key):
        self.keys.append(key)
        return self.data.get(key)


def _repository(data):
    ctx = pc.Context("examples")
    repo = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", config_obj={})
    fake = FakeRepository(data)
    repo._repository = fake
    return repo, fake


def test_what_is_in_memory_answers_before_anything_is_fetched():
    """A sketch already listed is found before a part is asked after, though parts are asked first."""
    repo, fake = _repository({})
    repo._object_configs["sketch"] = {"outline": {"type": "basic", "circle": 1.5}}

    assert repo.object_kind("outline") == "sketch"
    assert fake.keys == []


def test_the_slow_questions_are_asked_most_frequent_kind_first():
    repo, fake = _repository({"objects/interface/thread": {"desc": "An interface"}})

    assert repo.object_kind("thread") == "interface"
    # The part first -- the one object, then the kind it might be listed in --
    # and the interface after it; nothing is asked about any later kind.
    assert fake.keys == ["objects/part/thread", "objects/part", "objects/interface/thread"]


def test_a_part_costs_the_one_round_trip_it_costs_when_the_kind_is_said():
    repo, fake = _repository({"objects/part/bolt": {"type": "step", "path": "bolt.step"}})

    assert repo.object_kind("bolt") == "part"
    assert fake.keys == ["objects/part/bolt"]


def test_the_awaited_lookup_asks_what_the_synchronous_one_does():
    repo, fake = _repository({"objects/scene/stage": {"type": "assy", "path": "stage.assy"}})

    assert asyncio.run(repo.object_kind_async("stage")) == "scene"
    assert fake.keys[-1] == "objects/scene/stage"
    assert fake.keys.index("objects/part/stage") < fake.keys.index("objects/sketch/stage")


def test_a_kind_listed_later_can_take_a_name_from_one_listed_earlier():
    repo, _ = _repository(
        {
            "objects/sketch": {"m3": {"type": "basic", "circle": 1.5}},
            "objects/interface": {"m3": {"desc": "An interface"}},
        }
    )

    assert list(repo.object_configs("sketch")) == ["m3"]
    assert list(repo.object_configs("interface")) == ["m3"]
    # The interface is looked for first, so it keeps the name, whichever kind
    # the package happened to list first.
    assert repo.object_configs("sketch") == {}
    assert repo.object_config("sketch", "m3") is None
    assert repo.object_kind("m3") == "interface"


def test_an_alias_refused_as_its_kind_is_listed_is_not_indexed():
    """The alias index is built from the refusals listing the kind made, not from those before it."""
    repo, _ = _repository(
        {
            "objects/interface": {"thread": {"desc": "An interface"}},
            "objects/sketch": {"outline": {"type": "basic", "circle": 1.5, "aliases": ["thread"]}},
        }
    )

    assert list(repo.object_configs("interface")) == ["thread"]
    # Listing the sketches is what refuses the alias, and the index is built
    # by that same call.
    assert repo.alias_declared_by("sketch", "thread") is None
    assert repo.object_kind("thread") == "interface"
