#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading 'partcad.yaml' so that an int keeps the text it was written as.

'partcad.yaml' is YAML 1.1, which types an unquoted value by what it looks
like, and an int is where that loses something PartCAD needs: a git
dependency's 'revision:' and 'track:' name a commit, a tag or a branch, and
'875940244746' (an abbreviated commit id), '1_000' (a branch: git allows the
underscore), '0123', '0x1f' and '1:30' are all ints to YAML -- 875940244746,
1000, 83, 31 and 90. 'str()' gives the first one back; for every other one it
gives a different name, and a different name is a different branch.

So the loader here reads an int whose text is not its own decimal text as a
'SpelledInt': the same int, which everything else goes on using as one --
arithmetic, comparison, 'isinstance', 'str()', JSON, the cache hash -- with the
text it was written as beside it, for the readers to which the spelling is the
value ('spelling()'). An int written as its decimal text stays a plain int,
which is nearly every int there is, so a configuration with no such spelling in
it reads exactly as it did.

Ints only. A float is refused by those readers instead, with the fix named
(see 'project_factory_git.ref_text'): keeping its text would make one of these
out of every dimension written '0.50', and a value refused with the fix named
is not a wrong value. A bool ('on', 'yes') has no subclass to carry anything.

It is here rather than in 'partcad' because 'lint_context' reads 'partcad.yaml'
as PartCAD reads it too.
"""

import ruamel.yaml.representer
import yaml

_INT_TAG = "tag:yaml.org,2002:int"


class SpelledInt(int):
    """An int, and in 'text' the text it was written as, which is not its decimal text."""

    def __new__(cls, value: int, text: str):
        self = super().__new__(cls, value)
        self.text = text
        return self

    def __reduce__(self):
        # A copy (copy.deepcopy, pickle) is the same int, spelled the same way.
        return (SpelledInt, (int(self), self.text))


def spelling(value) -> str:
    """The text a scalar was written as in 'partcad.yaml', as far as it can be told.

    Exact for a string and for an int read by 'load()'. Not for a float, a bool
    or a date, which come back as Python spells them.
    """
    return value.text if isinstance(value, SpelledInt) else str(value)


class Loader(yaml.SafeLoader):
    """PyYAML's safe loader, with an int written other than as its decimal text read as a 'SpelledInt'."""

    def construct_yaml_int(self, node):
        value = super().construct_yaml_int(node)
        if node.value == str(value):
            return value
        return SpelledInt(value, node.value)


Loader.add_constructor(_INT_TAG, Loader.construct_yaml_int)


def load(text):
    """'text', a 'partcad.yaml' once it is rendered, read the way PartCAD reads it."""
    return yaml.load(text, Loader=Loader)


def _represent(representer, data):
    return representer.represent_scalar(_INT_TAG, data.text)


# Written back the way it was read. A value read from 'partcad.yaml' can be
# written out again -- 'Project' puts a part's declaration back into the file
# with ruamel -- and to either library this is a type it does not know, which
# it refuses rather than writes as the int.
for _representer in (
    yaml.representer.SafeRepresenter,
    yaml.representer.Representer,
    yaml.SafeDumper,
    yaml.Dumper,
    ruamel.yaml.representer.SafeRepresenter,
    ruamel.yaml.representer.Representer,
    ruamel.yaml.representer.RoundTripRepresenter,
):
    _representer.add_representer(SpelledInt, _represent)
