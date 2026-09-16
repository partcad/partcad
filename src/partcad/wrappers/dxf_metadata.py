#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a DXF drawing says about its own elements, read out of extended data.

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

Only ezdxf is imported, and no CAD library, so the annotations can be read - and
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

    include = list(include or [])
    exclude = list(exclude or [])

    document = ezdxf.readfile(path)
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
