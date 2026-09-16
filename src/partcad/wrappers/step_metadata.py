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

# What '_scan()' jumps to: the next quote, or the next record start. A record
# with no entity name before its list is a *complex* one, which is how a file
# states a named quantity in a unit -- see '_properties()'.
_NEXT = re.compile(r"'|#(\d+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)?\s*\(")

# What '_parts()' jumps to inside one complex record: a quote, or a part name.
_PART = re.compile(r"'|\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

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
        text = _without_comments(f.read())

    cut = _outside_strings(text, "DATA;")
    head, body = (text, "") if cut < 0 else (text[:cut], text[cut + len("DATA;") :])

    records = list(_scan(body))
    sections = (
        ("File", _header(head)),
        ("Products", _products(records)),
        ("Layers", _layers(records)),
        ("Properties", _properties(records)),
    )
    return {name: value for name, value in sections if value}


def _without_comments(text: str) -> str:
    """'text' with its Part 21 comments taken out, string-aware.

    A '/*' inside a quoted string opens nothing, so this walks the strings
    rather than looking only for the delimiters: a property whose value reads
    "use /* draft */ dimensions" is a value, not a value with a hole in it.
    """
    if "/*" not in text:
        return text

    kept = []
    start = 0
    i = 0
    while i < len(text):
        if text[i] == "'":
            match = _STRING.match(text, i)
            if match is None:
                break
            i = match.end()
            continue
        if text.startswith("/*", i):
            kept.append(text[start:i])
            end = text.find("*/", i + 2)
            if end < 0:
                # Unterminated, so the rest of the file is inside it.
                return "".join(kept)
            start = i = end + 2
            continue
        i += 1
    kept.append(text[start:])
    return "".join(kept)


def _outside_strings(text: str, needle: str) -> int:
    """Where 'needle' first occurs outside a quoted string, or -1.

    'DATA;' is what this is asked for, and a header that states it - a file
    named 'DATA;' is silly but legal - would otherwise split the file in the
    middle of the very section being read.
    """
    i = 0
    while i < len(text):
        if text[i] == "'":
            match = _STRING.match(text, i)
            if match is None:
                return -1
            i = match.end()
            continue
        if text.startswith(needle, i):
            return i
        i += 1
    return -1


def _scan(body: str):
    """Every record in 'body', once, as (id, entity, inside).

    'entity' is the name between the '=' and the parameter list, upper-cased -
    and the empty string for a *complex* record, '#30=( A(..) B(..) )', which
    names its parts inside instead.

    One pass for the whole file rather than one per entity type, because each
    caller below wants a different handful of them and a file is large. The
    walk jumps between quotes and record starts with a regular expression
    rather than reading every character, so being string-aware costs nothing
    over the scan this replaced: a record start written inside a quoted string
    is text, and a reader that took it for a record would invent one.
    """
    i = 0
    while True:
        match = _NEXT.search(body, i)
        if match is None:
            return
        if match.group(0) == "'":
            string = _STRING.match(body, match.start())
            if string is None:
                return
            i = string.end()
            continue
        opening = match.end() - 1
        inside = _list_at(body, opening)
        if inside is None:
            return
        yield int(match.group(1)), (match.group(2) or "").upper(), inside
        i = opening + len(inside) + 2


def _parts(inside: str):
    """The 'NAME(...)' parts of a complex record, as (name, arguments).

    '( REPRESENTATION_ITEM('radius') MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#5) )'
    is two parts, and each part's arguments are walked rather than matched for
    the reason every list here is: a quoted value may hold a bracket, and
    'DESCRIPTIVE_REPRESENTATION_ITEM('see 3(a)')' is one argument, not a
    malformed two. A name nested inside a part's own arguments is skipped with
    them, so 'LENGTH_MEASURE' above is never taken for a part of the record.
    """
    i = 0
    while True:
        match = _PART.search(inside, i)
        if match is None:
            return
        if match.group(0) == "'":
            string = _STRING.match(inside, match.start())
            if string is None:
                return
            i = string.end()
            continue
        opening = match.end() - 1
        arguments = _list_at(inside, opening)
        if arguments is None:
            return
        yield match.group(1).upper(), arguments
        i = opening + len(arguments) + 2


def _records(records: list, entity: str):
    """The scanned records whose entity matches 'entity', as (id, arguments).

    'entity' is a pattern rather than a name, because one caller wants every
    '...REPRESENTATION' there is. It is matched whole: 'PROPERTY_DEFINITION'
    must not also answer for 'PROPERTY_DEFINITION_REPRESENTATION'.
    """
    pattern = re.compile(entity)
    for id, name, inside in records:
        if name and pattern.fullmatch(name):
            yield id, _arguments(inside)


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


def _products(records: list) -> list:
    """PRODUCT(ID, NAME, DESCRIPTION, frame_of_reference) - what the file holds."""
    products = []
    for _, arguments in _records(records, "PRODUCT"):
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


def _layers(records: list) -> list:
    """PRESENTATION_LAYER_ASSIGNMENT(NAME, DESCRIPTION, ASSIGNED_ITEMS).

    STEP's own answer to a DXF layer. How many items are on it is reported
    rather than the items: what a reader wants of a layer is that it exists and
    how much is on it.
    """
    layers = []
    for _, arguments in _records(records, "PRESENTATION_LAYER_ASSIGNMENT"):
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


def _properties(records: list) -> list:
    """The user-defined key/value pairs the file hangs on its contents.

    Four records deep - the definition, the link, the representation, the items
    - and a STEP file states them in no particular order, so each kind is
    collected before any of it is joined up.
    """
    definitions = {}
    for id, arguments in _records(records, "PROPERTY_DEFINITION"):
        if len(arguments) >= 3:
            definitions[id] = (_text(arguments[0]), _reference(arguments[2]))

    representations = {}
    for id, arguments in _records(records, "[A-Z0-9_]*REPRESENTATION"):
        if len(arguments) >= 2:
            representations[id] = [int(ref) for ref in re.findall(r"#(\d+)", arguments[1])]

    items = {}
    for entity in _ITEMS:
        for id, arguments in _records(records, entity):
            key = _text(arguments[0]) if arguments else None
            if key:
                items[id] = (key.strip().lower(), _value(arguments[1]) if len(arguments) > 1 else None)
    # "( REPRESENTATION_ITEM('radius') MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#5) )":
    # the name and the number in separate entities of one record, which is how a
    # file states a named quantity in a unit. Neither half is a pair on its own.
    #
    # Both halves are looked for **inside that one record** and nowhere else.
    # Read across the file instead - which is what a '.*?' between the two does,
    # however lazy it is - a part that carries no measure of its own reaches
    # forward and takes the next record's, so a bend stating a 'direction' and a
    # 'radius' reports the radius' number under 'direction' and then loses the
    # radius, the match having consumed the record that stated it.
    for id, name, inside in records:
        if name:
            continue
        key = None
        value = None
        for part, arguments in _parts(inside):
            fields = _arguments(arguments)
            if not fields:
                continue
            if part == "REPRESENTATION_ITEM":
                key = _text(fields[0])
            elif part == "MEASURE_WITH_UNIT":
                # The number and the unit it is in; the unit is a reference to
                # a record this does not follow, so only the number is read.
                value = _value(fields[0])
            elif part in _ITEMS and value is None:
                # No unit: the value is this part's lone argument, the key
                # having come from 'REPRESENTATION_ITEM' rather than from the
                # first argument as it does in a record of one entity.
                value = _value(fields[0])
        if key:
            items[id] = (key.strip().lower(), value)

    owners = _owners(records)

    properties = []
    for _, arguments in _records(records, "PROPERTY_DEFINITION_REPRESENTATION"):
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


def _owners(records: list) -> dict:
    """What each record a property can be stated against is called.

    A 'SHAPE_ASPECT' is one named feature of a shape - where a property about
    *part* of a part belongs. Everything else reaches a 'PRODUCT' through its
    definition and formation, so those three are followed to the name at the
    end of them.
    """
    names = {}
    for id, arguments in _records(records, "SHAPE_ASPECT"):
        if arguments:
            names[id] = _text(arguments[0])

    products = {}
    for id, arguments in _records(records, "PRODUCT"):
        if len(arguments) >= 2:
            products[id] = _text(arguments[1]) or _text(arguments[0])

    formations = {}
    for entity in ("PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE", "PRODUCT_DEFINITION_FORMATION"):
        for id, arguments in _records(records, entity):
            if len(arguments) >= 3:
                formations[id] = products.get(_reference(arguments[2]))

    definitions = {}
    for id, arguments in _records(records, "PRODUCT_DEFINITION"):
        if len(arguments) >= 3:
            definitions[id] = formations.get(_reference(arguments[2]))
    names.update({id: name for id, name in definitions.items() if name})

    for id, arguments in _records(records, "PRODUCT_DEFINITION_SHAPE"):
        if len(arguments) >= 3:
            name = definitions.get(_reference(arguments[2]))
            if name:
                names[id] = name
    return names
