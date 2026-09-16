#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a DXF drawing says about itself and about its own elements.

A DXF entity may carry *extended data* - XDATA - which is arbitrary application
data attached to it: the tags an application wrote under its own APPID, in the
file, beside the geometry. It is where a drawing states what the geometry alone
cannot. A sheet metal bend line is the example this exists for: two identical
lines on one drawing are a bend up through 90 degrees and a bend down through
30, and nothing about the two lines says so.

BREP has nowhere to put any of that, so it is read here, as the file is
imported, and carried beside the geometry from then on (see
'Sketch.get_annotations'). That is what lets the sheet metal instructions be
*a sketch* rather than *a DXF file*: anything that can produce the same
annotations answers the same questions, whether or not a DXF was involved.

The drawing also says things about *itself* - which layers it has, which
application wrote it, what its numbers are in - and that is read here too
('describe()'), on the same trip and for the same reason: it cannot be asked of
the sketch afterwards, because a sketch is the layers that were selected and the
question "which layers does this drawing have" is about the ones that were not.
It is what 'pc info' reports of a DXF sketch, and it is how a layer filter that
matched nothing is told apart from a layer that is not in the file.

Only ezdxf is imported, and no CAD library, so all of it can be read - and
tested - without a sandbox.
"""

# The XDATA group codes this reads, and what each is.
#
# 1000 is a string, 1040 a real, 1070 a 16-bit integer and 1071 a 32-bit one.
# The rest of the XDATA code space says where something is or how big it is
# (1010-1013 points, 1041/1042 distances and scale factors) and is not a value
# a key/value annotation is written as, so it is left alone rather than
# flattened into text that would read as one.
_STRING = 1000
_VALUES = frozenset({1000, 1040, 1070, 1071})

# The control string that opens and closes a list within XDATA ('{' and '}'),
# and the codes that carry structure rather than a value.
_CONTROL = 1002


def _points(entity) -> list:
    """The points that locate this entity, as [x, y, z] lists.

    A sheet metal bend line is a LINE, which is the kind this exists for; the
    rest are here so that an annotated entity of another kind is still reported
    with something to locate it by, rather than being dropped for want of a
    rule.

    Nothing else is extracted. This is not a DXF reader - the geometry comes
    from the import beside it - this is only what identifies the element an
    annotation belongs to.
    """
    dxftype = entity.dxftype()
    dxf = entity.dxf
    try:
        if dxftype == "LINE":
            return [_point(dxf.start), _point(dxf.end)]
        if dxftype in ("CIRCLE", "ARC"):
            return [_point(dxf.center)]
        if dxftype == "LWPOLYLINE":
            return [[float(point[0]), float(point[1]), 0.0] for point in entity.get_points("xy")]
        if dxftype == "POLYLINE":
            return [_point(vertex.dxf.location) for vertex in entity.vertices]
        if dxftype in ("POINT", "TEXT", "MTEXT"):
            return [_point(dxf.location)]
    except Exception:
        # A malformed entity is one this cannot locate, which is not a reason to
        # lose the annotation it carries: the record goes out without points.
        return []
    return []


def _point(value) -> list:
    """One DXF point as an [x, y, z] list, with z filled in when the file omits it.

    A DXF written in two dimensions states two ordinates, and a record whose
    points had different lengths depending on how the file was drawn would be
    one every reader had to check the length of.
    """
    return [float(value[0]), float(value[1]), float(value[2]) if len(value) > 2 else 0.0]


def _tag_value(code: int, value):
    """One XDATA tag's value, as the Python type its group code declares."""
    if code == _STRING:
        return str(value)
    if code == 1040:
        return float(value)
    return int(value)


def metadata_of(entity) -> dict:
    """The key/value annotation an entity carries, flattened across every APPID.

    Two spellings are read, because both are in use and neither is PartCAD's to
    dictate:

    * ``1000 "angle=90"`` - one string tag holding the pair. This is what an
      application that has only strings to write produces, and it is what a
      person writing XDATA by hand writes.
    * ``1000 "angle"`` followed by ``1040 90.0`` - the name as a string and the
      value as whatever type states it best. This is what an application that
      cares about the type of a number writes, and it is the only way to state
      one without it having been text at some point.

    Keys are lower-cased, so that ``ANGLE``, ``Angle`` and ``angle`` are the one
    key they were meant to be; values are left exactly as the file states them.
    A key written twice keeps the last of them, which is what reading a
    key/value stream in order means.

    Flattened across APPIDs rather than kept per application: what the reader of
    an annotation wants is the angle of the bend, and which application wrote it
    down is not part of that question. A drawing whose two applications disagree
    about one key is a drawing to fix, and it reads as the later of the two.
    """
    xdata = getattr(entity, "xdata", None)
    if xdata is None:
        return {}
    metadata = {}
    for appid in sorted(getattr(xdata, "data", {}) or {}):
        try:
            tags = entity.get_xdata(appid)
        except Exception:
            continue
        pending = None
        for tag in tags:
            code, value = tag[0], tag[1]
            if code == _CONTROL:
                # A list opens or closes. Nothing here reads structure, so the
                # marker is skipped rather than taken for a value.
                pending = None
                continue
            if code not in _VALUES:
                pending = None
                continue
            if code == _STRING and "=" in str(value):
                key, _, text = str(value).partition("=")
                key = key.strip().lower()
                if key:
                    metadata[key] = text.strip()
                pending = None
                continue
            if pending is not None:
                metadata[pending] = _tag_value(code, value)
                pending = None
                continue
            if code == _STRING:
                key = str(value).strip().lower()
                pending = key if key else None
            else:
                # A bare number with no name in front of it names nothing.
                pending = None
    return metadata


def is_included(layer: str, include, exclude) -> bool:
    """Whether an entity on this layer is one the sketch reads.

    The same rule the import itself applies - 'include' is the layers to read
    and 'exclude' the layers not to - so that the annotations describe the
    elements that are actually in the sketch and not the ones that were
    filtered out of it.

    Case-insensitively, because that is what CadQuery's importer does with the
    very same two lists ('_importDXF' lowercases every layer name before
    comparing, the DXF specification having nothing to say about the case of
    one). A rule that differed here would describe elements the sketch does not
    contain, or miss ones it does.
    """
    layer = (layer or "").lower()
    if include and layer not in [name.lower() for name in include]:
        return False
    if exclude and layer in [name.lower() for name in exclude]:
        return False
    return True


def read(path: str, include=None, exclude=None) -> list:
    """Every element of the drawing that is read into the sketch, annotated.

    One record per DXF entity, in the order the file states them:

    * ``type`` - the DXF entity type ('LINE', 'ARC', ...);
    * ``layer`` - the layer it is on;
    * ``handle`` - the file's own identifier for it, so that a record can be
      traced back to the entity it came from;
    * ``points`` - where it is, as far as '_points()' can say;
    * ``metadata`` - what its XDATA says, as key/value pairs.

    An entity with no XDATA at all is still reported, with an empty
    ``metadata``. That is the difference between "this drawing annotates
    nothing" and "this line was left un-annotated", and a check that every bend
    line says how far it bends needs to be able to tell them apart.

    A file that cannot be read raises, as it does for the import beside this:
    annotations that are silently empty would read as a drawing that annotates
    nothing.
    """
    import ezdxf

    return annotations_of(ezdxf.readfile(path), include, exclude)


def annotations_of(document, include=None, exclude=None) -> list:
    """'read()', of a drawing that has already been opened.

    Split out so that one pass over the file answers both questions a caller
    has of it -- what it says about its elements, and what it says about itself
    -- rather than opening and parsing a drawing twice to ask them separately.
    """
    include = list(include or [])
    exclude = list(exclude or [])

    annotations = []
    for entity in document.modelspace():
        layer = getattr(entity.dxf, "layer", "")
        if not is_included(layer, include, exclude):
            continue
        annotations.append(
            {
                "type": entity.dxftype(),
                "layer": layer,
                "handle": getattr(entity.dxf, "handle", None),
                "points": _points(entity),
                "metadata": metadata_of(entity),
            }
        )
    return annotations


# What '$INSUNITS' says the drawing is drawn in. DXF states it as a code and
# nothing else in the file repeats it, so a drawing whose numbers are inches
# looks exactly like one whose numbers are millimetres until this is read.
#
# Spelled out here rather than taken from ezdxf, which has had the table under
# two different names across the versions a sandbox may install.
#
# 0 is not in the table: it is the code for *unitless*, which '_units()' answers
# with None because a drawing that says it has no units has said something, and
# what it said is not a unit. 21-24 are the US survey units, which AutoCAD added
# long after the other twenty; they are here because a code this does not know
# must not come out looking like a code that means nothing - see '_units()'.
_UNITS = {
    1: "in",
    2: "ft",
    3: "mi",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "uin",
    9: "mil",
    10: "yd",
    11: "angstrom",
    12: "nm",
    13: "um",
    14: "dm",
    15: "dam",
    16: "hm",
    17: "Gm",
    18: "au",
    19: "ly",
    20: "pc",
    21: "us-ft",
    22: "us-in",
    23: "us-yd",
    24: "us-mi",
}


def read_file(path: str, include=None, exclude=None) -> dict:
    """Everything this module reads out of one drawing, in one pass over it.

    ``{"metadata": ..., "annotations": ...}`` -- what the drawing says about
    itself ('describe()') and what it says about its elements ('read()'). One
    'ezdxf.readfile' serves both, which is the whole reason this exists: the
    import wrapper wants both and a drawing is not cheap to parse twice.

    The first of those comes back under the headings 'pc info' prints it with,
    because naming the sections is the reader's job and not the core's: the core
    merges what a wrapper hands it verbatim, and it has no business translating
    one format's vocabulary into another's. ``Layers`` is the heading a STEP file
    uses for the same idea, which is why it is lifted out of ``Drawing`` - the
    rest of what a DXF states about itself has no counterpart anywhere else.
    """
    import ezdxf

    document = ezdxf.readfile(path)
    described = describe(document, include, exclude)
    layers = described.pop("layers", [])

    metadata = {}
    if described:
        metadata["Drawing"] = described
    if layers:
        metadata["Layers"] = layers
    return {"metadata": metadata, "annotations": annotations_of(document, include, exclude)}


def describe(document, include=None, exclude=None) -> dict:
    """What the drawing says about itself, rather than about any one element.

    Five things, and each of them is a question somebody asks of a DXF before
    they ask anything about its geometry:

    * ``version``/``release`` - which DXF this is ('AC1024', 'R2010'). XDATA is
      in every version, but what a drawing may carry beside it is not.
    * ``units`` - what '$INSUNITS' resolves to ('_units()'): a name, None where
      it says the drawing is unitless, or "unknown (<code>)" for a unit DXF has
      gained since. PartCAD reads a DXF as millimetres whatever it says;
      this is what the file states, and the two disagreeing is worth being able
      to see. Note that a file omitting the variable altogether does not read as
      unitless: ezdxf supplies a default for it while loading and there is no
      way left to tell the two apart, so what is reported for such a file is
      that default.
    * ``appids`` - the applications the file declares. XDATA is written under an
      APPID, so this is the list of names an annotation could have been written
      by, and an empty one is a drawing that carries no XDATA at all.
    * ``layers`` - **every** layer the drawing declares, whether or not this
      sketch reads it, with how many elements are on each and of which types.
      That is the difference between a layer filter that selected nothing and a
      layer that is not in the file - between a typo and an empty layer - which
      is otherwise invisible: both produce a sketch with nothing in it.
    * ``elements`` - how many entities the model space holds, all layers
      together.

    The layer filters are applied to the ``read`` flag and to nothing else. The
    point of reporting a layer that was filtered out is that it was filtered
    out.
    """
    include = list(include or [])
    exclude = list(exclude or [])

    layers = {}
    for name in _declared_layers(document):
        layers[name] = {
            "name": name,
            "read": is_included(name, include, exclude),
            "elements": 0,
            "types": {},
        }

    total = 0
    for entity in document.modelspace():
        total += 1
        name = getattr(entity.dxf, "layer", "") or ""
        layer = layers.get(name)
        if layer is None:
            # An entity on a layer the table does not declare. DXF allows it and
            # applications write it; a layer that is only mentioned by what is
            # drawn on it is still a layer this sketch may be reading.
            layer = layers[name] = {
                "name": name,
                "read": is_included(name, include, exclude),
                "elements": 0,
                "types": {},
            }
        layer["elements"] += 1
        dxftype = entity.dxftype()
        layer["types"][dxftype] = layer["types"].get(dxftype, 0) + 1

    return {
        "version": getattr(document, "dxfversion", None),
        "release": getattr(document, "acad_release", None),
        "units": _units(_header_var(document, "$INSUNITS")),
        "appids": _appids(document),
        "elements": total,
        "layers": [layers[name] for name in sorted(layers)],
    }


def _units(code):
    """What a '$INSUNITS' code is the name of, or None where it names no unit.

    Three answers, and the third is why this is a function rather than a lookup:

    * a **name** for a code in the table;
    * **None** for 0, which is the code for "unitless" - the drawing has said
      something, and what it said is that its numbers are not in anything;
    * **"unknown (<code>)"** for a code the table does not have. DXF has gained
      units before (21-24, the US survey units, arrived long after the first
      twenty) and will again, and a plain 'dict.get' answers a future code with
      the None that means unitless - which is not "this reader is behind", it is
      a wrong answer wearing the same clothes as a right one.
    """
    if code is None or code == 0:
        return None
    return _UNITS.get(code, "unknown (%s)" % code)


def _declared_layers(document) -> list:
    """The names in the drawing's layer table, or an empty list if it has none."""
    try:
        return [layer.dxf.name for layer in document.layers]
    except Exception:
        return []


def _appids(document) -> list:
    """The APPIDs the drawing declares, sorted.

    Reported because an annotation is written under one: a drawing whose table
    names 'PARTCAD' and one that names nothing say different things about where
    an 'angle' could have come from. A file whose table cannot be read reports
    none rather than failing the whole description over it.
    """
    try:
        return sorted(appid.dxf.name for appid in document.appids)
    except Exception:
        return []


def _header_var(document, name):
    """One '$'-prefixed header variable, as ezdxf resolves it.

    None only where ezdxf cannot answer at all. It fills a default in for a
    variable the file omits, so this cannot distinguish a drawing that stated
    one from a drawing that left it out - see the note in 'describe()'.
    """
    try:
        return document.header.get(name)
    except Exception:
        return None
