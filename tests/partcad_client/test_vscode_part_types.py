#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The VS Code extension's "Add part" types, held to the ones `pc add part` takes.

'ide/vscode/src/partTypes.ts' is the extension's one copy of which part types
there are and which files each one is stored in. The extension is a JSON-RPC
client with no Python in it, so it cannot import the tables it copies; this
reads the TypeScript and fails when it disagrees with them -- the way the
viewer's tabs are held to 'partcad_ide_client.protocol.VIEWER_TABS'.

What a disagreement costs is quiet either way: a type `pc add part` takes and
the picker does not offer is one a user of the editor has no way to add, and an
extension the dialog does not list is a file the dialog hides.
"""

import os
import re

from partcad_cli.click.commands.add.part import PART_KINDS
from partcad_client import object_types

PART_TYPES_TS = os.path.join(os.path.dirname(__file__), "..", "..", "ide", "vscode", "src", "partTypes.ts")

# The scripts the picker offers start from a template ('examples.ts'), which
# is what it offers a script type for; 'sdf' has none, so it is added with
# `pc add part sdf` and not from the picker.
NOT_OFFERED = {"sdf"}

# Scripts are '.py' files whatever library they use, so the file says nothing of
# which type it is: the extension is not one the type tables would name.
SCRIPT_EXTENSIONS = {"cadquery": ["py"], "build123d": ["py"], "sdf": ["py"], "scad": ["scad"], "chili3d": ["chili"]}

# The one type whose part is read from another extension than PartCAD writes it
# in: 'pc export -t gltf' writes '.json', and a 'gltf' part is '<name>.gltf'
# ('part_factory_gltf') or a '.glb'.
READ_FROM = {"gltf": "gltf"}


def _choices():
    """'PART_TYPE_CHOICES' as 'partTypes.ts' writes it, read off the source, in order."""
    with open(PART_TYPES_TS, encoding="utf-8") as f:
        source = f.read()
    block = re.search(r"export const PART_TYPE_CHOICES[^=]*= \[(.*?)\n\];", source, re.S)
    assert block, "PART_TYPE_CHOICES is not where this test looks for it in %s" % PART_TYPES_TS
    choices = []
    for line in block.group(1).strip().splitlines():
        entry = re.fullmatch(
            r"\s*\{ label: '([^']+)', kind: '([^']+)', extensions: \[([^\]]*)\](, template: true)? \},",
            line,
        )
        assert entry, "Not one entry on one line, as this test reads them: %r" % line
        label, kind, extensions, template = entry.groups()
        choices.append(
            {
                "label": label,
                "kind": kind,
                "extensions": re.findall(r"'([^']+)'", extensions),
                "template": bool(template),
            }
        )
    return choices


def test_every_type_pc_add_part_takes_is_offered():
    offered = [choice["kind"] for choice in _choices()]
    assert len(offered) == len(set(offered)), "A type is offered twice"
    assert set(offered) == set(PART_KINDS) - NOT_OFFERED


def test_the_native_cad_formats_are_offered():
    """The part types PartCAD ships as declarations, each a file of its application's own."""
    offered = {choice["kind"] for choice in _choices() if not choice["template"]}
    assert set(object_types.BUILTIN_PART_TYPE_EXTENSION) <= offered


def test_each_type_is_chosen_from_every_extension_it_is_stored_in():
    """'.igs' as well as '.iges', and the four extensions of an ACIS body."""
    for choice in _choices():
        kind = choice["kind"]
        if kind in SCRIPT_EXTENSIONS:
            assert choice["extensions"] == SCRIPT_EXTENSIONS[kind], kind
            continue
        own = READ_FROM.get(kind) or object_types.BUILTIN_PART_TYPE_EXTENSION.get(kind)
        own = own or object_types.PART_TYPE_EXTENSION[kind]
        others = sorted(alias for alias, aliased in object_types.EXTENSION_ALIASES.items() if aliased == kind)
        expected = list(dict.fromkeys([own] + others))
        assert choice["extensions"] == expected, kind
        for extension in choice["extensions"]:
            assert kind in object_types.types_of_extension(extension), (kind, extension)


def test_the_extension_a_type_declares_is_spelled_as_it_declares_it():
    """'FCStd', 'SLDPRT', 'CATPart': the spelling the default file name is written in comes first."""
    by_kind = {choice["kind"]: choice for choice in _choices()}
    for kind, extension in object_types.BUILTIN_PART_TYPE_EXTENSION.items():
        assert by_kind[kind]["extensions"][0] == extension, kind


def test_only_scripts_are_started_from_a_template():
    for choice in _choices():
        assert choice["template"] == (choice["kind"] in SCRIPT_EXTENSIONS), choice["kind"]
