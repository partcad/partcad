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

import typing

import ruamel.yaml.representer
import yaml
import yaml.constructor
import yaml.scanner

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
    """'text', a 'partcad.yaml' once it is rendered, read the way PartCAD reads it.

    A failure that is YAML reading an unquoted '>', '|' or '!' as syntax is raised
    with the fix named (see 'explain').
    """
    try:
        return yaml.load(text, Loader=Loader)
    except yaml.MarkedYAMLError as e:
        hint = explain(e)
        if hint is not None and e.problem and hint not in e.problem:
            e.problem = "%s (%s)" % (e.problem, hint)
        raise


# What a value has to be quoted for, said once: a requirement such as '>0' or
# '!0' is the common case, but anything else written the same way is too.
QUOTING_HINT = (
    "YAML reads a value that starts with '>' or '|' as the header of a block of text, and one that starts with "
    "'!' as a tag: quote it, as in \"mass: '>0'\""
)


def explain(error) -> typing.Optional[str]:
    """What to do about a YAML error that an unquoted leading '>', '|' or '!' caused, or None for any other.

    These are the three characters a value written as PartCAD reads it -- a
    comparison of a requirement ('>0', '>=1,<10', '!0'), a parameter's text --
    most often starts with and YAML does not: '>' and '|' open a block scalar,
    whose header then has to end the line, and '!' is a tag nothing defines.
    YAML is right to refuse them; what it says is only not what to do about it.
    """
    problem = "%s %s" % (getattr(error, "context", "") or "", getattr(error, "problem", "") or "")
    if isinstance(error, yaml.scanner.ScannerError) and "block scalar" in problem:
        return QUOTING_HINT
    if isinstance(error, yaml.constructor.ConstructorError) and "for the tag '!" in problem and "'!!" not in problem:
        return QUOTING_HINT
    return None


def empty_block_scalars(text: str) -> list:
    """Every '>5' or '|2' YAML read as an empty block of text: [(line, column, header)], 0-based.

    The one way an unquoted comparison is not refused but *misread*: a '>' or a
    '|' followed by a digit is a block scalar header with an indentation
    indicator, and the block it opens is empty when the next line is not
    indented further -- so 'mass: >5' reads as 'mass: ""', with nothing said.
    A block scalar that is empty because nothing was written under it is
    reported too: an empty value written as a block is not something anybody
    means. Nothing is reported for a document that does not parse.
    """
    try:
        root = yaml.compose(text, Loader=Loader)
    except Exception:  # pylint: disable=broad-except
        return []
    return empty_block_scalars_of(root)


def empty_block_scalars_of(root) -> list:
    """'empty_block_scalars' of a document already composed: [(line, column, header)], 0-based."""
    found = []
    stack = [root] if root is not None else []
    while stack:
        node = stack.pop()
        if isinstance(node, yaml.ScalarNode):
            if node.style in (">", "|") and node.value == "":
                mark = node.start_mark
                buffer = getattr(mark, "buffer", None) or ""
                pointer = getattr(mark, "pointer", 0) or 0
                line = buffer[pointer:].split("\n", 1)[0].rstrip("\0")
                found.append((mark.line, mark.column, line.split(" #", 1)[0].strip() or node.style))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
        elif isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                stack.extend((key, value))
    found.sort()
    return found


# What 'empty_block_scalars' finds is reported as, wherever it is reported.
def misread_block(header: str) -> str:
    """Why a value written '>5' is not the text '>5', and what to write instead."""
    return (
        "YAML reads '%s' here as the header of an empty block of text, so the value is empty, not '%s': quote it"
        " ('%s')" % (header, header, header)
    )


def scalar(text: str):
    """One value typed on its own -- a word on the command line, a field of a form -- read as YAML reads it.

    The same text, written as a value in 'partcad.yaml', is read as this: '5' is
    the number, 'true' the boolean, 'null' (and nothing at all) no value, '[1, 2]'
    a list, and "'5'" the string. So a value means one thing wherever it is typed.

    Except for what can only be a misreading of a value typed on its own: text
    YAML cannot read ('>0', '!0', '>=1,<10'), and text it would read as an
    empty block of text ('>5', see 'empty_block_scalars'), is the text itself.
    In a document those are mistakes to be refused with the fix named ('load');
    here there is no document to be mistaken about, and the value is all there
    is.
    """
    if not isinstance(text, str):
        return text
    try:
        node = yaml.compose(text, Loader=Loader)
        if isinstance(node, yaml.ScalarNode) and node.style in (">", "|"):
            return text
        return yaml.load(text, Loader=Loader)
    except yaml.YAMLError:
        return text


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
