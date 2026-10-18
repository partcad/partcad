#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Writing a dependency's 'revision:' into 'partcad.yaml', and nothing else.

'pc update' moves each tracked dependency's pin to where its branch is now, and
the pin lives in a file somebody wrote by hand: with comments, with an order of
their choosing, and as a Jinja2 template that PartCAD renders before it is YAML
at all. Loading it into a YAML library and dumping it again would put back
whatever that library thinks the file should look like - and a template is not
YAML until it is rendered, so a '{% if %}' line would not survive the trip.

So the edit is made on the text, and is the smallest one there is: the value of
an existing 'revision:' line is replaced, or a 'revision:' line is added right
under the 'track:' it belongs to. Every other byte stays where it was. Where the
declaration is not written in a way that makes that edit unambiguous - an entry
in flow style, one declared twice by two branches of a template, a revision that
is itself a template expression - the file is left alone and the reason comes
back, so the caller can say what to write by hand rather than write something
that is wrong.

What is written is a value 'partcad.yaml' reads back as the text it is. The file
is read as YAML 1.1, where an unquoted value is typed by what it looks like: a
commit id is hex, and one made of decimal digits alone is read as an int.
PartCAD keeps the text of such an int (see 'partcad_utils.config_yaml'), but
PartCAD is not the file's only reader: 'pc lint' holds it to the schema, which
says a revision is a string. So a value that would not be read back as itself is
quoted, and every other is written plain, as it always was.
"""

import re
import typing

import yaml

from partcad_utils import config_yaml

_TOP_LEVEL_SECTION = "dependencies"

# 'key:' with whatever follows it, the key optionally quoted. A dependency name
# is '[a-zA-Z0-9_/.-]+' (see the schema), so a key never holds a colon or a quote.
_KEY_RE = re.compile(r"""^(?P<indent>[ ]*)(?P<quote>["']?)(?P<key>[^"':#\s][^"':#]*?)(?P=quote)[ \t]*:(?P<rest>.*)$""")

# What may follow a key that opens a block: nothing, or a comment.
_OPENS_BLOCK_RE = re.compile(r"^[ \t]*(#.*)?$")

# A 'revision:' line, split into what is kept and the value that is replaced.
_REVISION_RE = re.compile(
    r"""^(?P<head>[ ]*(?P<quote>["']?)revision(?P=quote)[ \t]*:[ \t]*)(?P<value>[^#\r\n]*?)(?P<tail>[ \t]+#[^\r\n]*)?(?P<eol>\r?\n)?$"""
)


def plain_reads_back(value: str) -> bool:
    """Whether 'value', written unquoted, is read back from 'partcad.yaml' as this very text.

    The question is put to the reader 'partcad.yaml' is read with
    ('config_yaml.load', see 'ProjectLocal') rather than to a list of what looks
    numeric, so the two cannot disagree. An int it keeps the text of is still
    an int, and not this text.
    """
    try:
        return config_yaml.load("value: %s" % value) == {"value": value}
    except yaml.YAMLError:
        return False


def yaml_scalar(value: str) -> str:
    """'value' as it has to be written for 'partcad.yaml' to read it back as this text.

    Plain where that is already so, which is every commit id with a hex letter
    in it; single-quoted where it is not, as in "revision: '875940244746...'".
    """
    if plain_reads_back(value):
        return value
    return "'%s'" % value.replace("'", "''")


def _eol(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _skippable(line: str) -> bool:
    """A line that says nothing about the structure: blank, a comment, or template logic."""
    stripped = line.strip()
    return not stripped or stripped.startswith(("#", "{%", "{#"))


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _key(line: str) -> typing.Optional[re.Match]:
    return _KEY_RE.match(line.rstrip("\r\n"))


def _block_end(lines: list[str], start: int, parent_indent: int) -> int:
    """The index just past the block of lines below 'start' that are indented deeper than its key."""
    end = start + 1
    while end < len(lines):
        if not _skippable(lines[end]) and _indent(lines[end]) <= parent_indent:
            break
        end += 1
    return end


def _children(lines: list[str], start: int, end: int) -> list[tuple[int, re.Match]]:
    """The keys one level below the key at 'start', as (line index, match)."""
    child_indent = None
    children = []
    for index in range(start + 1, end):
        if _skippable(lines[index]):
            continue
        indent = _indent(lines[index])
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        match = _key(lines[index])
        if match is not None:
            children.append((index, match))
    return children


def _opens_block(match: re.Match) -> bool:
    return bool(_OPENS_BLOCK_RE.match(match.group("rest")))


def set_dependency_revision(config_path: str, dependency: str, revision: str) -> typing.Optional[str]:
    """Make 'dependency' in 'config_path' say 'revision: <revision>'.

    Returns None once the file says so (including when it already did), or why
    it was left alone.
    """
    with open(config_path, "r", encoding="utf-8", newline="") as f:
        lines = f.read().splitlines(keepends=True)

    sections = [
        index
        for index, line in enumerate(lines)
        if not _skippable(line)
        and _indent(line) == 0
        and (match := _key(line)) is not None
        and match.group("key") == _TOP_LEVEL_SECTION
    ]
    if len(sections) != 1:
        return "there is no single top-level '%s:' section to find it in" % _TOP_LEVEL_SECTION
    section = sections[0]
    if not _opens_block(_key(lines[section])):
        return "the '%s:' section is not written in block style" % _TOP_LEVEL_SECTION
    section_end = _block_end(lines, section, 0)

    entries = [
        (index, match) for index, match in _children(lines, section, section_end) if match.group("key") == dependency
    ]
    if not entries:
        return "it is not written out as an entry of the '%s:' section" % _TOP_LEVEL_SECTION
    if len(entries) > 1:
        return "it is declared %d times (a template choosing between them?)" % len(entries)
    entry, entry_match = entries[0]
    if not _opens_block(entry_match):
        return "its declaration is not written in block style"
    entry_indent = len(entry_match.group("indent"))
    entry_end = _block_end(lines, entry, entry_indent)

    fields = {}
    for index, match in _children(lines, entry, entry_end):
        fields.setdefault(match.group("key"), []).append(index)
    if len(fields.get("revision", [])) > 1 or len(fields.get("track", [])) > 1:
        return "its 'revision:' or 'track:' is written more than once"

    if "revision" in fields:
        index = fields["revision"][0]
        match = _REVISION_RE.match(lines[index])
        if match is None:
            return "its 'revision:' line is not a plain value"
        value = match.group("value").strip()
        if "{{" in value or "{%" in value:
            return "its 'revision:' is a template expression"
        # Quoted the way it was quoted, if it was; if not, quoted only if a
        # plain value would not be read back as itself.
        quote = value[0] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else ""
        if value.strip("'\"") == revision and (quote or plain_reads_back(revision)):
            return None
        lines[index] = "%s%s%s%s" % (
            match.group("head"),
            "%s%s%s" % (quote, revision, quote) if quote else yaml_scalar(revision),
            match.group("tail") or "",
            match.group("eol") or "",
        )
    elif "track" in fields:
        index = fields["track"][0]
        line = lines[index]
        eol = _eol(line)
        if not eol:
            # The last line of a file with no newline at its end.
            eol = "\n"
            lines[index] = line + eol
        lines.insert(index + 1, "%srevision: %s%s" % (" " * _indent(line), yaml_scalar(revision), eol))
    else:
        return "its 'track:' is not written out in it"

    with open(config_path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    return None
