#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An int in 'partcad.yaml' keeps the text it was written as, and is an int to everything else.

'track: 1_000' is the branch '1_000', which YAML 1.1 reads as the int 1000:
what is pinned down here is that the text is still there when a reader that
needs it asks ('spelling'), and that it is still there after everything a
configuration goes through on its way -- a copy, a pickle, a write back into
the file -- while JSON, the wrapper protocol and the daemon's answers carry the
plain number they always did.
"""

import copy
import io
import json
import pickle

import pytest
import ruamel.yaml
import yaml

from partcad_utils import config_yaml, framing, lint_context
from partcad_utils.config_yaml import SpelledInt, spelling

# (written, the int YAML 1.1 reads it as)
SPELLED = [
    ("1_000", 1000),
    ("0123", 0o123),
    ("0x1f", 0x1F),
    ("0b101", 0b101),
    ("1:30", 90),
    ("+5", 5),
]
# An int written as its decimal text, which is a plain int as it always was.
PLAIN = ["875940244746", "2024", "5", "-3", "0"]


@pytest.mark.parametrize("written, value", SPELLED)
def test_an_int_spelled_otherwise_keeps_its_text(written, value):
    read = config_yaml.load("track: %s\n" % written)["track"]
    assert isinstance(read, SpelledInt) and read == value
    assert spelling(read) == written
    # Next to the text, it is the int: nothing else has to know.
    assert isinstance(read, int) and read + 1 == value + 1 and hash(read) == hash(value)
    assert str(read) == str(value) and "%d" % read == str(value)


@pytest.mark.parametrize("written", PLAIN)
def test_an_int_spelled_as_its_decimal_text_is_a_plain_int(written):
    read = config_yaml.load("revision: %s\n" % written)["revision"]
    assert type(read) is int
    assert spelling(read) == written


@pytest.mark.parametrize("written", ["'1_000'", "1.10", "on", "abc1234", "1e10", "0189abcdef", "~"])
def test_everything_else_is_read_as_safe_load_reads_it(written):
    text = "value: %s\n" % written
    assert config_yaml.load(text) == yaml.safe_load(text)
    assert not isinstance(config_yaml.load(text)["value"], SpelledInt)


def test_the_loader_is_still_safe():
    with pytest.raises(yaml.constructor.ConstructorError):
        config_yaml.load("value: !!python/object/apply:os.system ['true']\n")


def config():
    return config_yaml.load("dependencies:\n  dep:\n    type: git\n    track: 1_000\n    revision: 0123\n")


@pytest.mark.parametrize(
    "copied",
    [copy.deepcopy, copy.copy, lambda c: pickle.loads(pickle.dumps(c)), lambda c: {**c}],
    ids=["deepcopy", "copy", "pickle", "merged"],
)
def test_the_text_survives_a_copy(copied):
    dep = copied(config())["dependencies"]["dep"]
    assert spelling(dep["track"]) == "1_000"
    assert spelling(dep["revision"]) == "0123"


def test_json_carries_the_number():
    """The daemon's answers and the wrapper protocol are JSON, which has one way to write an int."""
    plain = {"dependencies": {"dep": {"type": "git", "track": 1000, "revision": 83}}}
    assert json.dumps(config()) == json.dumps(plain)
    stream = io.BytesIO()
    framing.write_message(stream, config())
    stream.seek(0)
    assert framing.read_message(stream) == plain


def test_pyyaml_writes_it_back_as_it_was_written():
    text = yaml.safe_dump(config(), sort_keys=False)
    assert "track: 1_000\n" in text and "revision: 0123\n" in text
    assert config_yaml.load(text) == config()
    assert spelling(config_yaml.load(text)["dependencies"]["dep"]["track"]) == "1_000"


def test_ruamel_writes_it_back_as_it_was_written():
    """'Project.set_part_config' and its siblings put declarations read from the file back into it with ruamel."""
    document = ruamel.yaml.YAML().load("dependencies:\n  dep:\n    type: git\n")
    document["dependencies"]["dep"].update(config()["dependencies"]["dep"])
    out = io.StringIO()
    ruamel.yaml.YAML().dump(document, out)
    assert "track: 1_000\n" in out.getvalue() and "revision: 0123\n" in out.getvalue()
    dep = config_yaml.load(out.getvalue())["dependencies"]["dep"]
    assert (spelling(dep["track"]), spelling(dep["revision"])) == ("1_000", "0123")


def test_lint_context_reads_the_file_as_partcad_does(tmp_path):
    (tmp_path / "partcad.yaml").write_text("dependencies:\n  dep:\n    type: git\n    track: 1_000\n")
    read = lint_context._load(str(tmp_path / "partcad.yaml"), [str(tmp_path)])
    assert spelling(read["dependencies"]["dep"]["track"]) == "1_000"
