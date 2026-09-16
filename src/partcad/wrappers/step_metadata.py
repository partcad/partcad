#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a STEP file says about itself and about the things inside it.

A STEP file is not only geometry. It may put its contents on named **layers**,
and it may hang **properties** - named key/value pairs - on a product or on one
named feature of one. That is where a STEP file says what the geometry cannot,
and it is the same thing a DXF says in XDATA: two identical faces are a bend up
through 90 degrees and a bend down through 30, and nothing about the faces says
which.

So the keys come out lower-cased and the values as the file states them, exactly
as 'dxf_metadata' produces them - an 'angle' reads the same whether a drawing
stated it or a model did, and what asks the question has no business knowing
which format answered.

Read here, in the wrapper, because this is the process the file is open in. It
is read as *text* rather than through OCCT, and that is not for want of a
kernel: XCAF gives names, layers and colours, and has nowhere to put an
arbitrary 'PROPERTY_DEFINITION', which is the half this exists for. A STEP file
is ISO 10303-21, a list of '#<id> = ENTITY(<arguments>);' records, and the
handful of entity types that matter can be matched straight out of it.

Whole-file rather than streamed: OCCT has just parsed the same bytes into a
model in this very process, so a second pass over them is the cheap part of what
this wrapper does. Nothing here needs the careful block-boundary handling a
streaming reader would.

What is read: the header ('FILE_NAME', 'FILE_DESCRIPTION', 'FILE_SCHEMA'), the
products the file names, its 'PRESENTATION_LAYER_ASSIGNMENT' layers, and the
'PROPERTY_DEFINITION' -> 'PROPERTY_DEFINITION_REPRESENTATION' ->
'REPRESENTATION' -> items chain that CAD applications write user attributes as.

Only the exact entity 'PROPERTY_DEFINITION_REPRESENTATION' is followed, never a
subtype: 'SHAPE_DEFINITION_REPRESENTATION' is one, every file holding a solid
states one, and following it would report each solid as a property set stating
nothing.
"""

import re

# A Part 21 string: single-quoted, a doubled quote standing for one inside it.
_STRING = re.compile(r"'[^']*(?:''[^']*)*'")

# Where one record of a given entity type starts. Only the '#id = ENTITY(' is
# matched; where the argument list *ends* is found by walking it, because a
# Part 21 string may hold anything - a ';' most of all. Every STEP file ever
# exported writes "FILE_DESCRIPTION((...),'2;1')", so a pattern that stopped at
# the first semicolon would read no header at all.
_RECORD = r"#(\d+)\s*=\s*%s\s*\("

# A value, as the three ways a representation item states one: a string, a
# measure wrapped around its number, or a bare number.
_MEASURE = re.compile(r"^[A-Z][A-Z0-9_]*_MEASURE\s*\(\s*([^()]*?)\s*\)$", re.I)
_ENUM = re.compile(r"^\.([A-Z]+)\.$")

# The representation items that state a key and a value. Every one of them names
# the key first and the value second; what differs is only the type of the
# value, which '_value()' reads off the argument rather than off the name.
_ITEMS = (
    "DESCRIPTIVE_REPRESENTATION_ITEM",
    "VALUE_REPRESENTATION_ITEM",
    "REAL_REPRESENTATION_ITEM",
    "INTEGER_REPRESENTATION_ITEM",
    "BOOLEAN_REPRESENTATION_ITEM",
    "MEASURE_REPRESENTATION_ITEM",
)


def read(path: str) -> dict:
    """What the STEP file at 'path' states, as 'pc info' reports it.

    ``{"File": {...}, "Products": [...], "Layers": [...], "Properties": [...]}``,
    with a section the file states nothing in left out rather than reported
    empty. The section names are this format's own: the core merges them
    verbatim and never translates one format's vocabulary into another's.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    # Comments mean nothing and may hold anything shaped like a record.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    head, _, body = text.partition("DATA;")

    sections = (
        ("File", _header(head)),
        ("Products", _products(body)),
        ("Layers", _layers(body)),
        ("Properties", _properties(body)),
    )
    return {name: value for name, value in sections if value}


def _records(body: str, entity: str):
    """Every '#id = ENTITY(...)' record of one entity type, as (id, arguments)."""
    for match in re.finditer(_RECORD % entity, body):
        inside = _list_at(body, match.end() - 1)
        if inside is not None:
            yield int(match.group(1)), _arguments(inside)


def _list_at(text: str, opening: int):
    """The inside of the parameter list that opens at 'text[opening]'.

    None if it never closes. Walked rather than matched: a nested list and a
    quoted string may both hold the delimiters, and a string may hold the
    semicolon that would otherwise look like the end of the record.
    """
    depth = 0
    i = opening
    while i < len(text):
        char = text[i]
        if char == "'":
            match = _STRING.match(text, i)
            if match is None:
                return None
            i = match.end()
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : i]
        i += 1
    return None


def _arguments(text: str) -> list:
    """The top-level arguments of one record's parameter list.

    Split by hand rather than by pattern: a nested list and a quoted string may
    both hold a comma, and a regular expression that got that right would be
    harder to read than the loop.
    """
    arguments = []
    depth = 0
    begin = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char == "'":
            match = _STRING.match(text, i)
            if match is None:
                break
            i = match.end()
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append(text[begin:i].strip())
            begin = i + 1
        i += 1
    arguments.append(text[begin:].strip())
    return arguments


def _text(argument):
    """A Part 21 string as a str, or None for the '$' that stands for none.

    None rather than "" for an omitted value: a file that left a description out
    and one that wrote an empty description are saying different things, and
    only the second of them is saying anything.
    """
    if not argument or argument == "$" or not argument.startswith("'") or not argument.endswith("'"):
        return None
    return argument[1:-1].replace("''", "'")


def _reference(argument):
    """The record id an argument refers to, or None if it is not a reference."""
    match = re.match(r"^#(\d+)$", argument or "")
    return None if match is None else int(match.group(1))


def _number(argument):
    """An argument read as a float, or None if it is not written as one.

    A reference, a list and an enumeration all land here and all come back None:
    none of them is the number a measure or a real was supposed to hold.
    """
    try:
        return float(argument)
    except (TypeError, ValueError):
        return None


def _value(argument):
    """One argument as the value it states, or None if it states none."""
    if not argument or argument == "$":
        return None
    if argument.startswith("'"):
        return _text(argument)
    enum = _ENUM.match(argument)
    if enum is not None:
        return {"T": True, "F": False}.get(enum.group(1))
    measure = _MEASURE.match(argument)
    if measure is not None:
        return _number(measure.group(1))
    return _number(argument)


def _header(head: str) -> dict:
    """What the file states about its own making, as far as it states it."""
    fields = (
        ("FILE_NAME", ("name", "timestamp", "author", "organization", "preprocessor", "originatingSystem")),
        ("FILE_DESCRIPTION", ("description",)),
        ("FILE_SCHEMA", ("schema",)),
    )
    header = {}
    for entity, names in fields:
        match = re.search(r"\b%s\s*\(" % entity, head)
        if match is None:
            continue
        inside = _list_at(head, match.end() - 1)
        if inside is None:
            continue
        arguments = _arguments(inside)
        for index, key in enumerate(names):
            if index >= len(arguments):
                break
            argument = arguments[index]
            # A list argument holds any number of strings; every exporter writes
            # "('')" for a field it was not told, so an empty one is not a value.
            value = [_text(s) for s in _STRING.findall(argument)] if argument.startswith("(") else _text(argument)
            if isinstance(value, list):
                value = [item for item in value if item]
            if value:
                header[key] = value
    return header


def _products(body: str) -> list:
    """PRODUCT(ID, NAME, DESCRIPTION, frame_of_reference) - what the file holds."""
    products = []
    for _, arguments in _records(body, "PRODUCT"):
        if len(arguments) < 2:
            continue
        products.append(
            {
                "id": _text(arguments[0]),
                "name": _text(arguments[1]),
                "description": _text(arguments[2]) if len(arguments) > 2 else None,
            }
        )
    return products


def _layers(body: str) -> list:
    """PRESENTATION_LAYER_ASSIGNMENT(NAME, DESCRIPTION, ASSIGNED_ITEMS).

    STEP's own answer to a DXF layer. How many items are on it is reported
    rather than the items: what a reader wants of a layer is that it exists and
    how much is on it.
    """
    layers = []
    for _, arguments in _records(body, "PRESENTATION_LAYER_ASSIGNMENT"):
        if len(arguments) < 3:
            continue
        layers.append(
            {
                "name": _text(arguments[0]),
                "description": _text(arguments[1]),
                "elements": len(re.findall(r"#\d+", arguments[2])),
            }
        )
    return layers


def _properties(body: str) -> list:
    """The user-defined key/value pairs the file hangs on its contents.

    Four records deep - the definition, the link, the representation, the items
    - and a STEP file states them in no particular order, so each kind is
    collected before any of it is joined up.
    """
    definitions = {}
    for id, arguments in _records(body, "PROPERTY_DEFINITION"):
        if len(arguments) >= 3:
            definitions[id] = (_text(arguments[0]), _reference(arguments[2]))

    representations = {}
    for id, arguments in _records(body, "[A-Z0-9_]*REPRESENTATION"):
        if len(arguments) >= 2:
            representations[id] = [int(ref) for ref in re.findall(r"#(\d+)", arguments[1])]

    items = {}
    for entity in _ITEMS:
        for id, arguments in _records(body, entity):
            key = _text(arguments[0]) if arguments else None
            if key:
                items[id] = (key.strip().lower(), _value(arguments[1]) if len(arguments) > 1 else None)
    # "( REPRESENTATION_ITEM('radius') MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#5) )":
    # the name and the number in separate entities of one record, which is how a
    # file states a named quantity in a unit. Neither half is a pair on its own.
    for match in re.finditer(
        r"#(\d+)\s*=\s*\(\s*REPRESENTATION_ITEM\s*\(\s*(" + _STRING.pattern + r")\s*\)"
        r".*?MEASURE_WITH_UNIT\s*\(\s*([^,]*?)\s*,",
        body,
        re.S,
    ):
        key = _text(match.group(2))
        if key:
            items[int(match.group(1))] = (key.strip().lower(), _value(match.group(3)))

    owners = _owners(body)

    properties = []
    for _, arguments in _records(body, "PROPERTY_DEFINITION_REPRESENTATION"):
        if len(arguments) < 2:
            continue
        definition = definitions.get(_reference(arguments[0]))
        if definition is None:
            # Not a user property: a 'PRODUCT_DEFINITION_SHAPE' tied to the
            # geometry of a product, which says nothing about it.
            continue
        name, owner = definition
        metadata = {}
        for item in representations.get(_reference(arguments[1]), []):
            pair = items.get(item)
            if pair is not None:
                metadata[pair[0]] = pair[1]
        properties.append({"name": name, "owner": owners.get(owner), "metadata": metadata})
    return properties


def _owners(body: str) -> dict:
    """What each record a property can be stated against is called.

    A 'SHAPE_ASPECT' is one named feature of a shape - where a property about
    *part* of a part belongs. Everything else reaches a 'PRODUCT' through its
    definition and formation, so those three are followed to the name at the
    end of them.
    """
    names = {}
    for id, arguments in _records(body, "SHAPE_ASPECT"):
        if arguments:
            names[id] = _text(arguments[0])

    products = {}
    for id, arguments in _records(body, "PRODUCT"):
        if len(arguments) >= 2:
            products[id] = _text(arguments[1]) or _text(arguments[0])

    formations = {}
    for entity in ("PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE", "PRODUCT_DEFINITION_FORMATION"):
        for id, arguments in _records(body, entity):
            if len(arguments) >= 3:
                formations[id] = products.get(_reference(arguments[2]))

    definitions = {}
    for id, arguments in _records(body, "PRODUCT_DEFINITION"):
        if len(arguments) >= 3:
            definitions[id] = formations.get(_reference(arguments[2]))
    names.update({id: name for id, name in definitions.items() if name})

    for id, arguments in _records(body, "PRODUCT_DEFINITION_SHAPE"):
        if len(arguments) >= 3:
            name = definitions.get(_reference(arguments[2]))
            if name:
                names[id] = name
    return names
