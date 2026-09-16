#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a STEP file says about itself and about the things inside it.

A STEP file is not only geometry. It states who wrote it and when, it may put
its contents on named **layers**, and it may hang **properties** -- named
key/value pairs -- on a product or on one named feature of one. That is where a
STEP file says what the geometry cannot, and it is the same thing a DXF says in
XDATA: two identical faces are a bend up through 90 degrees and a bend down
through 30, and nothing about the faces says which.

So this reads it, and reads it into the same shape 'wrappers/dxf_metadata.py'
produces -- a list of records, each with a 'metadata' mapping of lower-cased
keys to the values the file states. 'angle' and 'radius' read the same whether
the drawing was a DXF or the model was a STEP, which is the whole point of
normalising them: what asks the question is a manufacturing check, and it has no
business knowing which file format answered it.

Nothing here needs a CAD kernel. A STEP file is ISO 10303-21, which is text, and
'step_p21' reads it as such -- the same trade 'tolerance_inspect' makes for GD&T
and 'brep_inspect' for topology. The core process holds no live shapes, so
putting this to a sandbox would cost a process per part to answer a question the
bytes already answer.

What is read, and where each of them comes from:

* the **header** -- 'FILE_DESCRIPTION', 'FILE_NAME' and 'FILE_SCHEMA', the three
  records every STEP file opens with. Who exported it, when, with what, and to
  which application protocol.

* the **products** -- 'PRODUCT(id, name, description, ...)'. What the file calls
  the things it holds.

* the **layers** -- 'PRESENTATION_LAYER_ASSIGNMENT(name, description, items)'.
  STEP's own answer to a DXF layer: a name, and the elements put on it. The
  count of those elements is reported rather than the elements themselves; what
  a reader wants of a layer is that it exists and how much is on it.

* the **properties** -- a 'PROPERTY_DEFINITION' tied by a
  'PROPERTY_DEFINITION_REPRESENTATION' to a 'REPRESENTATION' whose items are the
  pairs. That is the chain every CAD application writes a user-defined attribute
  as, and reading it is the whole of how an 'angle' reaches PartCAD from a STEP
  file.

  Only the exact entity 'PROPERTY_DEFINITION_REPRESENTATION' is followed, never
  a subtype. 'SHAPE_DEFINITION_REPRESENTATION' is one, and it ties a product's
  shape to its geometry: following it would report every solid in the file as a
  property set holding nothing.

Values are kept **as the file states them**, exactly as the DXF reader keeps
them: a real stays a float, a string stays a string, and a measure carrying a
unit is reported as its number. This deliberately does not convert units --
which of them a property is in is the property's business, and a file stating an
angle in degrees and one stating it in radians both write a number. Keys are
lower-cased, so 'ANGLE', 'Angle' and 'angle' are the one key they were meant to
be.
"""

import os
import re

from . import logging as pc_logging
from . import step_p21

# What has to appear in a block of records for it to be worth looking at
# closely. Nearly every record in a STEP file is a point, a curve or a face, and
# a block holding none of these words holds nothing this module wants -- so it
# is dropped whole and the expensive half of this is never reached for it.
#
# Every entity read below has one of these in its own name, which is what makes
# dropping a block safe: a record is never split across two of them, so a record
# this wants is always in a block one of these occurs in.
#
# Two of them look redundant and are not. 'PRESENTATION' is not a substring of
# 'REPRESENTATION', and 'PROPERTY_DEFINITION' holds neither - a reader that
# assumed either would find no layers, or no properties, in a file that states
# them next to nothing else.
_KEYWORDS = (
    b"PRODUCT",
    b"PROPERTY",
    b"REPRESENTATION",
    b"PRESENTATION_LAYER_ASSIGNMENT",
    b"SHAPE_ASPECT",
)

# Where a record begins: '#<id> =', followed either by an entity name and its
# arguments, or - for a complex instance - straight by the '(' that holds the
# entities it is made of.
_RECORD = re.compile(rb"#(\d+)\s*=\s*([A-Z][A-Z0-9_]*)?\s*\(")

# One entity inside a complex instance: "( REPRESENTATION_ITEM('radius')
# MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#5) )". Applied to the inside of the
# outer list, so what it matches is a name at the top level of it.
_SUBENTITY = re.compile(rb"([A-Z][A-Z0-9_]*)\s*\(")

# A measure as an argument is written as the kind of measure it is wrapped
# around its number: 'LENGTH_MEASURE(1.5)', 'PLANE_ANGLE_MEASURE(90.0)',
# 'COUNT_MEASURE(3)'. What is wanted is the number; which kind of measure it is
# said to be is the file's own vocabulary and not a value.
_MEASURE = re.compile(rb"^[A-Z][A-Z0-9_]*_MEASURE\s*\(\s*([^()]*?)\s*\)$")

# A Part 21 enumeration, of which the two that are a value are '.T.' and '.F.'.
_ENUMERATION = re.compile(rb"^\.([A-Z]+)\.$")

# The representation items that state a key and a value. Every one of them names
# the key first and states the value second, so all that differs between them is
# the *type* of that value - which '_value()' reads off the argument rather than
# off the entity name, so this is a set of names and not a table of rules.
_ITEM_TYPES = frozenset(
    {
        b"DESCRIPTIVE_REPRESENTATION_ITEM",
        b"VALUE_REPRESENTATION_ITEM",
        b"REAL_REPRESENTATION_ITEM",
        b"INTEGER_REPRESENTATION_ITEM",
        b"BOOLEAN_REPRESENTATION_ITEM",
        b"MEASURE_REPRESENTATION_ITEM",
    }
)

# The file formats this knows how to read, mapped to the reader for each. A part
# type names the *format* of the file it is read from rather than appearing here
# itself, so that a type that produces a STEP file some other way ('kicad' does)
# is read by the same reader without being named twice.
_READERS = {}


def of_file(file_format, path):
    """What the file at 'path' states about itself, or None if nothing can be read.

    None for a format nothing here can read, for a file that is not there (a
    'kicad' part's STEP file does not exist until the part is built, and a part
    fetched from a URL not until it is downloaded), and for a file that cannot
    be read at all. A file that *is* read and states nothing comes back as a
    dictionary of empty sections rather than as None, because "read, and it says
    nothing" and "not read" are different answers - the same distinction the DXF
    reader draws between an un-annotated element and a drawing that annotates
    nothing.
    """
    reader = _READERS.get(file_format)
    if reader is None or not path:
        return None
    if not os.path.isfile(path):
        pc_logging.debug("No %s file to read metadata out of: %s" % (file_format, path))
        return None
    try:
        return reader(path)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.warning("Failed to read the metadata stated by '%s': %s" % (path, e))
        return None


def of_step_file(path):
    """Everything a STEP file states about itself, read without a CAD kernel.

    Four sections, each a list or a mapping that is empty when the file states
    nothing of that kind:

    * ``header`` -- what the file says about its own making;
    * ``products`` -- ``{"id", "name", "description"}`` per product;
    * ``layers`` -- ``{"name", "description", "elements"}`` per layer;
    * ``properties`` -- ``{"name", "owner", "ownerType", "handle", "metadata"}``
      per property set, where ``metadata`` holds the key/value pairs.
    """
    records = _Records()
    step_p21.scan(path, _KEYWORDS, records.read_block)
    return {
        "header": _header(path),
        "products": records.products(),
        "layers": records.layers(),
        "properties": records.properties(),
    }


_READERS["step"] = of_step_file


# What each section of 'of_file()' is called when 'pc info' reports it. The
# vocabulary lives here, with the reader that produces the sections, so that the
# day a second format is read its sections land under the same headings rather
# than under whatever the factory reporting them decided to call them.
_SECTIONS = (
    ("header", "File"),
    ("products", "Products"),
    ("layers", "Layers"),
    ("properties", "Properties"),
)


def as_info(metadata) -> dict:
    """The sections of 'of_file()' as 'pc info' reports them.

    A section the file states nothing in is left out rather than reported empty:
    what 'pc info' prints is what there is to say, and a run of empty headings
    says nothing about the part while burying what does. 'None' - the file could
    not be read at all - is the same empty answer here, because the reader has
    already said why in the log.
    """
    if not metadata:
        return {}
    return {heading: metadata[key] for key, heading in _SECTIONS if metadata.get(key)}


class _Records:
    """The records a STEP file states that this module has any use for.

    Gathered in one pass, by id, and joined up afterwards: a property is four
    records deep (the definition, the link, the representation, the items) and a
    STEP file states them in no particular order, so nothing can be resolved
    until the whole file has gone by.
    """

    def __init__(self):
        """Empty of every record type; 'read_block' is what fills them in."""
        self._products = {}
        self._formations = {}
        self._definitions = {}
        self._definition_shapes = {}
        self._aspects = {}
        self._property_definitions = {}
        self._links = []
        self._representations = {}
        self._items = {}
        self._layers = []

    def read_block(self, block):
        """Take what a block of whole records says.

        Only ever handed a block one of '_KEYWORDS' occurs in, with its comments
        already taken out: 'step_p21.scan' does both.
        """
        for match in _RECORD.finditer(block):
            id = int(match.group(1))
            entity = match.group(2)
            start = match.end() - 1
            if entity is None:
                self._complex(id, block, start)
                continue
            self._simple(id, entity, block, start)

    def _simple(self, id, entity, block, start):
        """One ordinary '#id = ENTITY(...)' record."""
        if entity not in _INTERESTING and entity not in _ITEM_TYPES:
            return
        arguments = step_p21.arguments(block, start)
        if arguments is None:
            return
        if entity in _ITEM_TYPES:
            self._item(id, arguments)
            return
        _INTERESTING[entity](self, id, arguments)

    def _complex(self, id, block, start):
        """One '#id = ( A(...) B(...) )' complex instance.

        The one shape of it that states a value is a representation item and a
        measure together -- "( REPRESENTATION_ITEM('radius')
        MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#5) )" -- which is how a file
        states a named quantity in a unit. The two halves are in separate
        entities, so neither of them is a key/value pair on its own and the
        record has to be read whole.
        """
        outer = step_p21.arguments(block, start)
        if not outer:
            return
        inside = outer[0]
        key = None
        value = None
        for match in _SUBENTITY.finditer(inside):
            arguments = step_p21.arguments(inside, match.end() - 1)
            if not arguments:
                continue
            name = match.group(1)
            if name == b"REPRESENTATION_ITEM":
                key = step_p21.text(arguments[0])
            elif name.endswith(b"MEASURE_WITH_UNIT") and value is None:
                value = _value(arguments[0])
        if key:
            self._items[id] = (key.strip().lower(), value)

    #
    # One method per record type this reads. Each takes the record's id and its
    # already-split arguments, and each keeps only what something else asks for.
    #
    # Part 21 names no attribute: a record is a positional argument list, so
    # every index below is a claim about the schema. Each docstring spells the
    # entity out as AP242 declares it, with the attribute being read in capitals
    # -- that is what makes the index checkable without the standard to hand,
    # and a short argument list is a truncated record rather than a different
    # entity, so it is dropped rather than read at the wrong offset.
    #

    def _product(self, id, arguments):
        """PRODUCT(ID, NAME, DESCRIPTION, frame_of_reference)."""
        if len(arguments) < 2:
            return
        self._products[id] = {
            "id": step_p21.text(arguments[0]),
            "name": step_p21.text(arguments[1]),
            "description": step_p21.text(arguments[2]) if len(arguments) > 2 else None,
        }

    def _formation(self, id, arguments):
        """PRODUCT_DEFINITION_FORMATION(id, description, OF_PRODUCT[, make_or_buy])."""
        if len(arguments) < 3:
            return
        self._formations[id] = step_p21.reference(arguments[2])

    def _definition(self, id, arguments):
        """PRODUCT_DEFINITION(id, description, FORMATION, frame_of_reference)."""
        if len(arguments) < 3:
            return
        self._definitions[id] = step_p21.reference(arguments[2])

    def _definition_shape(self, id, arguments):
        """PRODUCT_DEFINITION_SHAPE(name, description, DEFINITION).

        A subtype of 'property_definition', and the one every STEP file holding
        a solid states. It is followed for its owner and never treated as a
        property set of its own - see 'properties()'.
        """
        if len(arguments) < 3:
            return
        self._definition_shapes[id] = step_p21.reference(arguments[2])

    def _aspect(self, id, arguments):
        """SHAPE_ASPECT(NAME, description, of_shape, product_definitional).

        One named feature of a shape: what a property about *part* of a part is
        stated against, and the nearest thing STEP has to a DXF entity.
        """
        if not arguments:
            return
        self._aspects[id] = step_p21.text(arguments[0])

    def _property_definition(self, id, arguments):
        """PROPERTY_DEFINITION(NAME, description, DEFINITION)."""
        if len(arguments) < 3:
            return
        self._property_definitions[id] = (step_p21.text(arguments[0]), step_p21.reference(arguments[2]))

    def _link(self, id, arguments):
        """PROPERTY_DEFINITION_REPRESENTATION(DEFINITION, USED_REPRESENTATION).

        Kept as a pair rather than resolved here: a STEP file states its records
        in no particular order, so neither end need have been read yet.
        """
        if len(arguments) < 2:
            return
        definition = step_p21.reference(arguments[0])
        representation = step_p21.reference(arguments[1])
        if definition is not None and representation is not None:
            self._links.append((definition, representation))

    def _representation(self, id, arguments):
        """REPRESENTATION(NAME, ITEMS, context_of_items)."""
        if len(arguments) < 2:
            return
        self._representations[id] = (step_p21.text(arguments[0]), step_p21.references(arguments[1]))

    def _layer(self, id, arguments):
        """PRESENTATION_LAYER_ASSIGNMENT(NAME, DESCRIPTION, ASSIGNED_ITEMS)."""
        if len(arguments) < 3:
            return
        self._layers.append(
            {
                "name": step_p21.text(arguments[0]),
                "description": step_p21.text(arguments[1]),
                "elements": len(step_p21.references(arguments[2])),
            }
        )

    def _item(self, id, arguments):
        """One representation item that states a key and a value.

        Every one of '_ITEM_TYPES' names the key first and the value second, so
        which of them this is does not change how it is read - what differs
        between them is the *type* of the value, and '_value()' reads that off
        the argument rather than off the entity name.
        """
        if len(arguments) < 2:
            return
        key = step_p21.text(arguments[0])
        if not key:
            return
        self._items[id] = (key.strip().lower(), _value(arguments[1]))

    #
    # What comes out, once the whole file has gone by.
    #

    def products(self):
        """The products the file names, in the order their records are numbered.

        By id rather than by the order they were read: a block-at-a-time scan
        reads them in file order, which is the same thing for every file written
        by an exporter and not something the format promises.
        """
        return [self._products[id] for id in sorted(self._products)]

    def layers(self):
        """The layers the file declares, in the order it declares them."""
        return list(self._layers)

    def properties(self):
        """One record per property set, in the order the file states the links.

        A set whose items could not be read is still reported, with an empty
        'metadata'. That is the same distinction the DXF reader draws: "this
        file states no properties" and "this property set states nothing" are
        different answers, and a check on what a property says needs to tell
        them apart.
        """
        found = []
        for definition, representation in self._links:
            property = self._property_definitions.get(definition)
            if property is None:
                # Not a user property: a 'PRODUCT_DEFINITION_SHAPE' tied to the
                # geometry of a product, which every STEP file holding a solid
                # states and which says nothing about it.
                continue
            name, owner_reference = property
            represented = self._representations.get(representation)
            metadata = {}
            if represented is not None:
                for item in represented[1]:
                    pair = self._items.get(item)
                    if pair is not None:
                        metadata[pair[0]] = pair[1]
            owner_type, owner = self._owner(owner_reference)
            found.append(
                {
                    "name": name,
                    "owner": owner,
                    "ownerType": owner_type,
                    "handle": "#%d" % definition,
                    "metadata": metadata,
                }
            )
        return found

    def _owner(self, reference):
        """What a property is stated against, as (what kind of thing, its name).

        Three chains reach a name, and a file uses whichever suits what it is
        describing:

        * a 'SHAPE_ASPECT' - one named feature of a shape, which is where a
          property about *part* of a part belongs;
        * a 'PRODUCT_DEFINITION', through its formation to the 'PRODUCT' whose
          name this is;
        * a 'PRODUCT_DEFINITION_SHAPE', which is one hop further out and reaches
          the same place.

        (None, None) for anything else, which is a property stated against
        something this does not follow rather than one stated against nothing.
        """
        if reference is None:
            return None, None
        if reference in self._aspects:
            return "feature", self._aspects[reference]
        definition = reference
        if definition in self._definition_shapes:
            definition = self._definition_shapes[definition]
        formation = self._definitions.get(definition)
        if formation is None:
            return None, None
        product = self._products.get(self._formations.get(formation))
        if product is None:
            return None, None
        return "product", product["name"] or product["id"]


# Which record types are read, and by which method. Spelled as exact entity
# names rather than as a pattern, because every one of them has subtypes that
# mean something else: 'SHAPE_DEFINITION_REPRESENTATION' is a
# 'PROPERTY_DEFINITION_REPRESENTATION' tying a product to its geometry, and
# following it would report every solid in the file as a property set.
_INTERESTING = {
    b"PRODUCT": _Records._product,
    b"PRODUCT_DEFINITION_FORMATION": _Records._formation,
    b"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE": _Records._formation,
    b"PRODUCT_DEFINITION": _Records._definition,
    b"PRODUCT_DEFINITION_SHAPE": _Records._definition_shape,
    b"SHAPE_ASPECT": _Records._aspect,
    b"PROPERTY_DEFINITION": _Records._property_definition,
    b"PROPERTY_DEFINITION_REPRESENTATION": _Records._link,
    b"REPRESENTATION": _Records._representation,
    b"PRESENTATION_LAYER_ASSIGNMENT": _Records._layer,
}


def _value(argument):
    """One argument as the value it states, or None if it states none.

    A string comes back as text, a real or an integer as a float, '.T.'/'.F.' as
    a bool, and a measure as the number inside it. Anything else - a reference,
    a list, an enumeration that is not a boolean - is not a value a key/value
    pair is written as, and comes back as None rather than as the bytes that
    spelled it.
    """
    if argument is None or argument == b"$":
        return None
    if argument.startswith(b"'"):
        return step_p21.text(argument)
    enumeration = _ENUMERATION.match(argument)
    if enumeration is not None:
        if enumeration.group(1) == b"T":
            return True
        if enumeration.group(1) == b"F":
            return False
        return None
    measure = _MEASURE.match(argument)
    if measure is not None:
        return step_p21.number(measure.group(1))
    return step_p21.number(argument)


def _header(path):
    """What the file's HEADER section states, as a mapping.

    Empty for a file that has no header this can read, which is the same answer
    as a header stating nothing and the right one for both.
    """
    block = step_p21.header(path)
    if not block:
        return {}

    header = {}
    for entity, keys in _HEADER_ENTITIES:
        match = re.search(rb"\b" + entity + rb"\s*\(", block)
        if match is None:
            continue
        arguments = step_p21.arguments(block, match.end() - 1)
        if arguments is None:
            continue
        for index, (key, kind) in enumerate(keys):
            if index >= len(arguments):
                break
            value = _texts(arguments[index]) if kind == "list" else step_p21.text(arguments[index])
            if value not in (None, "", []):
                header[key] = value
    return header


# The three records a STEP file opens with, what each of their arguments is
# called here, and whether it is one string or a list of them. Positional,
# because Part 21 states a header record's attributes in a fixed order and
# names none of them; an argument the file leaves empty is left out of the
# result rather than reported as empty.
_HEADER_ENTITIES = (
    (b"FILE_DESCRIPTION", (("description", "list"), ("implementationLevel", "text"))),
    (
        b"FILE_NAME",
        (
            ("name", "text"),
            ("timestamp", "text"),
            ("author", "list"),
            ("organization", "list"),
            ("preprocessor", "text"),
            ("originatingSystem", "text"),
            ("authorization", "text"),
        ),
    ),
    (b"FILE_SCHEMA", (("schema", "list"),)),
)


def _texts(argument):
    """The strings in a '(...)' list argument, as a list of str.

    Empty entries are dropped: every STEP exporter writes '('')' for an author
    it was not told, and reporting that as an author called "" would be
    reporting the absence of one as the presence of one.
    """
    if not argument:
        return []
    found = []
    for match in step_p21.STRING.finditer(argument):
        text = step_p21.text(match.group(0))
        if text:
            found.append(text)
    return found
