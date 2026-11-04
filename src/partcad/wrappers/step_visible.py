#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A STEP file as it shows: what it declares invisible left out, before OpenCASCADE reads it.

ISO 10303-46 lets a file keep geometry it does not display. An ``INVISIBILITY``
names what is hidden -- a representation item directly, a ``STYLED_ITEM``
(hiding the item it styles), or a ``PRESENTATION_LAYER_ASSIGNMENT`` (hiding every
item on the layer) -- and the item stays in the representation that lists it, so
a reader that does not look sees it as an ordinary body:

    #20 = MANIFOLD_SOLID_BREP('', #19);
    #30 = ADVANCED_BREP_SHAPE_REPRESENTATION('', (#10, #20), #5);
    #40 = INVISIBILITY((#20));

OpenCASCADE applies an invisibility to the colour tool of an XCAF document, and
only for some of those forms; its plain reader, and every tree walk built on the
shapes it transfers, applies none. A native CAD file converted to STEP keeps the
bodies its author hid -- a tool body, the version before a change -- exactly that
way, and a part read from it is the document as it was *shown*, not everything
the document kept. So the hidden items are taken out of the item lists of the
representations that hold them, in a copy, and what OpenCASCADE reads is the
file with nothing hidden in it.

Nothing else changes: the records stay where they are, an item no
representation lists any more is simply never transferred, and a file that hides
nothing is read as it is, without a copy.

Runs inside the sandbox, so it uses nothing but the standard library.
"""

import contextlib
import os
import re
import tempfile

import step_repair

KEYWORD = b"INVISIBILITY"

# A simple entity instance, up to its opening parenthesis. A complex instance
# '#n = (A(...) B(...))' has no name before its list and is never matched, which
# is right: neither an invisibility nor a shape representation is written as one.
RECORD = re.compile(r"#(\d+)\s*=\s*([A-Z][A-Z0-9_]*)\s*\(")
REFERENCE = re.compile(r"#(\d+)")


def _records(text):
    """'{id: (entity, [parameter text, ...], (start, end))}' for every simple instance.

    'start' and 'end' bound the parameter list, its parentheses excluded.
    """
    records = {}
    for match in RECORD.finditer(text):
        commas, end = step_repair.top_level_commas(text, match.end())
        bounds = [match.end()] + [comma + 1 for comma in commas] + [end + 1]
        parameters = [text[bounds[i] : bounds[i + 1] - 1] for i in range(len(bounds) - 1)]
        records[int(match.group(1))] = (match.group(2), parameters, (match.end(), end))
    return records


def _references(parameter):
    return [int(found) for found in REFERENCE.findall(parameter)]


def hidden_items(records):
    """The ids of the representation items 'records' declares invisible."""
    hidden = set()
    for entity, parameters, _bounds in records.values():
        if entity != "INVISIBILITY" or not parameters:
            continue
        for target in _references(parameters[0]):
            target_entity, target_parameters, _ = records.get(target, (None, [], None))
            if target_entity == "STYLED_ITEM" and len(target_parameters) >= 3:
                # name, styles, item
                hidden.update(_references(target_parameters[2]))
            elif target_entity == "PRESENTATION_LAYER_ASSIGNMENT" and len(target_parameters) >= 3:
                # name, description, assigned items
                hidden.update(_references(target_parameters[2]))
            elif target_entity is not None:
                hidden.add(target)
    return hidden


def shown_text(text):
    """'text' with every hidden item taken out of the representations listing it, and how many were."""
    records = _records(text)
    hidden = hidden_items(records)
    if not hidden:
        return text, 0
    edits = []
    removed = 0
    for entity, parameters, (start, _end) in records.values():
        # A representation is (name, items, context_of_items); every shape
        # representation is a subtype, and so are the ones that list a body.
        if not entity.endswith("REPRESENTATION") or len(parameters) < 3:
            continue
        items = parameters[1].strip()
        if not (items.startswith("(") and items.endswith(")")):
            continue
        listed = _references(items)
        kept = [item for item in listed if item not in hidden]
        if len(kept) == len(listed):
            continue
        removed += len(listed) - len(kept)
        offset = start + len(parameters[0]) + 1
        edits.append((offset, offset + len(parameters[1]), "(%s)" % ",".join("#%d" % item for item in kept)))
    if not edits:
        return text, 0
    pieces = []
    last = 0
    for begin, finish, replacement in sorted(edits):
        pieces.append(text[last:begin])
        pieces.append(replacement)
        last = finish
    pieces.append(text[last:])
    return "".join(pieces), removed


@contextlib.contextmanager
def shown(path):
    """The STEP file to read for what 'path' shows: itself, or a copy with its hidden items left out.

    The copy lives as long as the 'with' block does.
    """
    with open(path, "rb") as f:
        data = f.read()
    if KEYWORD not in data:
        yield path
        return
    # Part 21 is 7-bit text with escapes for anything else, so latin-1 is a
    # lossless way to get at it as a string and back (as in 'step_repair').
    text, removed = shown_text(data.decode("latin-1"))
    if not removed:
        yield path
        return
    handle, copy = tempfile.mkstemp(prefix="partcad-shown-", suffix=os.path.splitext(path)[1] or ".step")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(text.encode("latin-1"))
        yield copy
    finally:
        try:
            os.remove(copy)
        except OSError:
            pass
