#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The CMF section a shape's payload carries after its BREP (docs/design/cmf.md, section 6).

A payload is its BREP followed by this section and a footer. OCCT reads a BREP
followed by anything as the same geometry, so the payload stays a BREP to every
reader; the section is what PartCAD finds after it::

    payload := brep section footer
    footer  := u32 len(section), b"PARTCMF1"                     (little-endian)
    section := u16 n, n x (u16 len, utf-8)                       strings
               u16 m, m x set                                    the palette
               i32 default                                       the part's own set, -1 for none
               runs(solids), runs(faces)
    set     := i32 color, i32 material, i32 finish, i32 origin   string indices, -1 for none
               u8 r, u8 g, u8 b, u8 a                            display colour (sRGB)
               u8 roughness, u8 metallic                         finish display, 0..255 for 0..1
               u8 flags                                          1 colour, 2 roughness, 4 metallic present
    runs(x) := u32 count of x, u32 k, k x (u32 length, i32 set)  TopExp::MapShapes order; -1 for none
    [looks]                                                      optional, see below

A set whose colour is drawn with an image (a texture: see 'Texture') says so in
a trailer after the runs, which a reader that does not know it never reaches -
it stops after the runs, so it reads every set with the display colour beside
it, which is what the texture is drawn as where only a colour can be::

    looks   := b"PCTX", u16 k, k x look, u16 j, j x image
    look    := i32 set, i32 name, i32 image, f64 width, f64 height     name a string index
    image   := u32 len, bytes                                          PNG or JPEG, each once

How it reads: a face's colour and finish are its set's, else the part's own
set's; a solid's material is its set's, else the part's own set's. A face's set
already holds what its solid lends it - whoever writes the section merges the
two, having the shape at hand - so a reader needs no CAD kernel to answer: the
core reads it to complete a part's CMF with its declaration, and to count what
is unspecified. Counts of zero mean "not addressed one by one": everything of
that kind takes the part's own set.

Plain Python, for the core and for a wrapper alike.
"""

import hashlib
import struct

FOOTER_MAGIC = b"PARTCMF1"
_LENGTH = struct.Struct("<I")
_FOOTER_SIZE = _LENGTH.size + len(FOOTER_MAGIC)
_SET = struct.Struct("<iiii4BBBB")
NONE = -1

COMPONENTS = ("color", "material", "finish")
FLAG_COLOR, FLAG_ROUGHNESS, FLAG_METALLIC = 1, 2, 4

# What starts the trailer of textures, and how each of its entries is written.
LOOKS_MAGIC = b"PCTX"
_LOOK = struct.Struct("<iiidd")

# What an image starts with, by the media type it is: the two kinds a colour
# may be drawn with (see 'Texture').
IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def image_type(image) -> "str | None":
    """'image/png' or 'image/jpeg' for the bytes of such an image, None for anything else."""
    for signature, mime in IMAGE_SIGNATURES:
        if bytes(image[: len(signature)]) == signature:
            return mime
    return None


class Texture:
    """An image a colour is drawn with, and how large one copy of it is on a surface.

    'image' is the bytes of a PNG or a JPEG, as the colour's declaration names
    the file; 'name' is that file as written, for whoever shows it. 'width' and
    'height' are how much of a surface one copy of the image covers, in
    millimetres: a surface is covered with copies of it, side by side, laid on
    each face from the side the face looks towards (see 'texture_mapping'). A
    texture is part of how its colour is drawn - a hint, like a display colour -
    and its set carries the colour it is drawn as where only a colour can be
    drawn (a line, a swatch), in 'rgba'.

    Two textures are one when their images are the same bytes and they cover the
    same size, whatever the file was called.
    """

    __slots__ = ("image", "name", "width", "height", "digest")

    def __init__(self, image, name=None, width=100.0, height=100.0, digest=None) -> None:
        self.image = bytes(image)
        self.name = name or None
        self.width = float(width)
        self.height = float(height)
        self.digest = digest or hashlib.sha256(self.image).hexdigest()

    def key(self) -> tuple:
        return (self.digest, self.width, self.height)

    def __eq__(self, other) -> bool:
        return isinstance(other, Texture) and self.key() == other.key()

    def __hash__(self) -> int:
        return hash(self.key())

    def __repr__(self) -> str:
        return "Texture(%r, %gx%g mm, %s)" % (self.name, self.width, self.height, self.digest[:12])

    @property
    def mime_type(self) -> "str | None":
        return image_type(self.image)

    def as_dict(self) -> dict:
        """The texture as plain data, its image named rather than carried: for a summary or a message."""
        result = {"image": self.name, "digest": self.digest, "size": [self.width, self.height]}
        return {key: value for key, value in result.items() if value is not None}


class CmfSet:
    """One entry of the palette: a colour, a material and a finish, each optional.

    'rgba' is the colour's display as '(red, green, blue, alpha)', alpha from 0
    to 1; 'roughness' and 'metallic' the finish's, from 0 to 1. 'origin' says
    where the set came from ('source:step', 'declared', ...), for whoever shows it.
    'texture' is the image the colour is drawn with where a surface can be drawn
    with one (see 'Texture'), and 'rgba' is then what it is drawn as elsewhere.
    """

    __slots__ = ("color", "material", "finish", "origin", "rgba", "roughness", "metallic", "texture")

    def __init__(
        self,
        color=None,
        material=None,
        finish=None,
        origin=None,
        rgba=None,
        roughness=None,
        metallic=None,
        texture=None,
    ) -> None:
        self.color = color or None
        self.material = material or None
        self.finish = finish or None
        self.origin = origin or None
        self.rgba = tuple(rgba) if rgba is not None else None
        self.roughness = roughness
        self.metallic = metallic
        self.texture = texture

    def key(self) -> tuple:
        texture = self.texture.key() if self.texture is not None else None
        return (self.color, self.material, self.finish, self.origin, self.rgba, self.roughness, self.metallic, texture)

    def __eq__(self, other) -> bool:
        return isinstance(other, CmfSet) and self.key() == other.key()

    def __hash__(self) -> int:
        return hash(self.key())

    def __repr__(self) -> str:
        return "CmfSet(%s)" % ", ".join("%s=%r" % (k, getattr(self, k)) for k in self.__slots__ if getattr(self, k))

    def has(self, component: str) -> bool:
        return getattr(self, component) is not None

    def without(self, components) -> "CmfSet":
        """This set with 'components' taken out, and the display that goes with them."""
        values = {name: getattr(self, name) for name in self.__slots__}
        for component in components:
            values[component] = None
            if component == "color":
                values["rgba"] = values["texture"] = None
            if component == "finish":
                values["roughness"] = values["metallic"] = None
        if all(values[component] is None for component in COMPONENTS):
            # Nothing of where it came from is left in it.
            values["origin"] = None
        return CmfSet(**values)

    def filled_from(self, other: "CmfSet") -> "CmfSet":
        """This set, with what it leaves unset taken from 'other', component by component."""
        if other is None:
            return self
        values = {name: getattr(self, name) for name in self.__slots__}
        if self.color is None and other.color is not None:
            values["color"], values["rgba"], values["texture"] = other.color, other.rgba, other.texture
        if self.material is None and other.material is not None:
            values["material"] = other.material
        if self.finish is None and other.finish is not None:
            values["finish"], values["roughness"], values["metallic"] = other.finish, other.roughness, other.metallic
        if values["origin"] is None:
            values["origin"] = other.origin
        return CmfSet(**values)

    def as_dict(self) -> dict:
        """The set as plain data, for a summary or a message."""
        result = {name: getattr(self, name) for name in ("color", "material", "finish", "origin")}
        if self.rgba is not None:
            result["display"] = "#%02X%02X%02X%02X" % (self.rgba[0], self.rgba[1], self.rgba[2], _byte(self.rgba[3]))
        if self.roughness is not None:
            result["roughness"] = self.roughness
        if self.metallic is not None:
            result["metallic"] = self.metallic
        if self.texture is not None:
            result["texture"] = self.texture.as_dict()
        return {key: value for key, value in result.items() if value is not None}

    def textured(self) -> bool:
        return self.texture is not None


class Section:
    """A shape's CMF: the palette, the part's own set, and a set per solid and per face.

    'solids' and 'faces' are a palette index (or NONE) per sub-shape, in
    'TopExp::MapShapes' order, or empty when nothing is addressed one by one.
    """

    def __init__(self, sets=None, default=NONE, solids=None, faces=None) -> None:
        self.sets = list(sets or [])
        self.default = default
        self.solids = list(solids or [])
        self.faces = list(faces or [])

    def __eq__(self, other) -> bool:
        return isinstance(other, Section) and (self.sets, self.default, self.solids, self.faces) == (
            other.sets,
            other.default,
            other.solids,
            other.faces,
        )

    def __repr__(self) -> str:
        return "Section(sets=%r, default=%r, solids=%d, faces=%d)" % (
            self.sets,
            self.default,
            len(self.solids),
            len(self.faces),
        )

    def index_of(self, cmf_set: CmfSet) -> int:
        """The palette index of 'cmf_set', added if it is not there yet."""
        if cmf_set is None:
            return NONE
        try:
            return self.sets.index(cmf_set)
        except ValueError:
            self.sets.append(cmf_set)
            return len(self.sets) - 1

    def own(self):
        return self.sets[self.default] if 0 <= self.default < len(self.sets) else None

    def face_set(self, index: int) -> CmfSet:
        """The colour and finish face 'index' is in: its own set's, else the part's own."""
        own = self.own()
        if 0 <= index < len(self.faces) and self.faces[index] != NONE:
            return self.sets[self.faces[index]].filled_from(own) if own is not None else self.sets[self.faces[index]]
        return own if own is not None else CmfSet()

    def solid_set(self, index: int) -> CmfSet:
        """The material solid 'index' is made of: its own set's, else the part's own."""
        own = self.own()
        if 0 <= index < len(self.solids) and self.solids[index] != NONE:
            return self.sets[self.solids[index]].filled_from(own) if own is not None else self.sets[self.solids[index]]
        return own if own is not None else CmfSet()

    def is_textured(self) -> bool:
        """Whether any set of this section draws its colour with an image."""
        return any(cmf_set.texture is not None for cmf_set in self.sets)

    def is_empty(self) -> bool:
        return self.own() is None and all(i == NONE for i in self.faces) and all(i == NONE for i in self.solids)

    def without(self, components) -> "Section":
        """This section with 'components' taken out of every set: what 'sourceCmf' drops."""
        if not components:
            return self
        return Section([s.without(components) for s in self.sets], self.default, self.solids, self.faces)

    def completed(self, declared: CmfSet) -> "Section":
        """This section with what it leaves unset completed by 'declared', the part's own CMF.

        The part's own set takes 'declared' for every component it leaves unset;
        a face or a solid whose own set leaves one unset reads it from there.
        """
        if declared is None:
            return self
        result = Section(self.sets, NONE, self.solids, self.faces)
        own = self.own()
        merged = own.filled_from(declared) if own is not None else declared
        result.default = result.index_of(merged)
        return result.compacted()

    def compacted(self) -> "Section":
        """This section with the sets nothing refers to taken out, and the indices renumbered."""
        used = sorted({i for i in [self.default] + self.solids + self.faces if i != NONE})
        mapping = {old: new for new, old in enumerate(used)}
        return Section(
            [self.sets[i] for i in used],
            mapping.get(self.default, NONE),
            [mapping.get(i, NONE) for i in self.solids],
            [mapping.get(i, NONE) for i in self.faces],
        )

    def summary(self) -> dict:
        """What a part's CMF comes to, as plain data: the sets with their counts, and what is unspecified.

        Counted one by one where the section addresses faces and solids, and
        otherwise said of all of them ('"all"'): the core reads this, and has no
        CAD kernel to count faces with.
        """
        sets = []
        unspecified = {}
        own = self.own()
        if self.faces:
            face_sets = [self.face_set(i) for i in range(len(self.faces))]
            unspecified["color"] = sum(1 for s in face_sets if s.color is None)
        else:
            face_sets = []
            if own is None or own.color is None:
                unspecified["color"] = "all"
        if self.solids:
            solid_sets = [self.solid_set(i) for i in range(len(self.solids))]
            unspecified["material"] = sum(1 for s in solid_sets if s.material is None)
        else:
            solid_sets = []
            if own is None or own.material is None:
                unspecified["material"] = "all"
        counted = {}
        for cmf_set in face_sets:
            entry = counted.setdefault(cmf_set.key(), [cmf_set, 0, 0])
            entry[1] += 1
        for cmf_set in solid_sets:
            entry = counted.setdefault(cmf_set.key(), [cmf_set, 0, 0])
            entry[2] += 1
        if not counted and own is not None:
            counted[own.key()] = [own, "all", "all"]
        for cmf_set, faces, solids in counted.values():
            sets.append({**cmf_set.as_dict(), "faces": faces, "solids": solids})
        return {
            "sets": sets,
            "unspecified": {key: value for key, value in unspecified.items() if value},
        }


def as_stated(section, convention):
    """'section' as a part type states it, in 'output["cmf"]' ('wrapper_part_type'), or None if it says nothing.

    The inverse of what 'wrapper_part_type' reads: the designations of each
    face's and solid's set, in 'convention''s terms, with the colour to draw it
    in. Where each set came from is not carried: the wrapper makes it
    'raw:<convention>' again, which is what a reader states.
    """
    if section is None or section.is_empty():
        return None

    def plain(index):
        if index == NONE:
            return None
        found = section.sets[index]
        entry = {key: getattr(found, key) for key in COMPONENTS if getattr(found, key) is not None}
        if found.rgba is not None:
            entry["rgba"] = list(found.rgba)
        return entry or None

    stated = {"convention": convention}
    if section.faces:
        stated["faces"] = [plain(index) for index in section.faces]
    if section.solids:
        stated["solids"] = [plain(index) for index in section.solids]
    return stated if len(stated) > 1 else None


def _added(one, other):
    """Two counts of a summary added: numbers add, and a count that is not a number makes 'some' of them.

    '"all"' is every face (or solid) of one payload, counted by nobody; added to
    a number, or to the 'all' of another payload, what is left is that some of
    the part's faces are - which is what is true of it, and as much as can be
    said without a kernel to count them.
    """
    if one is None:
        return other
    if other is None:
        return one
    if isinstance(one, int) and isinstance(other, int):
        return one + other
    if one == other == "all":
        return "all"
    return "some"


def merge_summaries(summaries) -> dict:
    """The summary of a part whose geometry is several payloads, each with a summary of its own.

    Sets alike in everything but their counts are one set; what is unspecified
    is added up (see '_added'). One payload's summary is returned as it is.
    """
    summaries = [summary for summary in summaries if summary]
    if len(summaries) == 1:
        return summaries[0]
    if not summaries:
        return {"sets": [], "unspecified": {}}
    merged = {}
    unspecified = {}
    for index, summary in enumerate(summaries):
        for entry in summary.get("sets") or []:
            key = tuple(sorted((k, repr(v)) for k, v in entry.items() if k not in ("faces", "solids")))
            if key not in merged:
                merged[key] = dict(entry)
            else:
                for count in ("faces", "solids"):
                    merged[key][count] = _added(merged[key].get(count), entry.get(count))
        for component in ("color", "material"):
            # A payload saying nothing about a component left none of it
            # unspecified. Added up from nothing rather than from nought, so
            # that payloads which all leave it unspecified leave all of it so.
            unspecified[component] = _added(
                unspecified.get(component), (summary.get("unspecified") or {}).get(component, 0)
            )
    return {
        "sets": list(merged.values()),
        "unspecified": {key: value for key, value in unspecified.items() if value},
    }


def _byte(fraction) -> int:
    return max(0, min(255, int(round(float(fraction) * 255))))


def _runs(indices) -> list:
    runs = []
    for index in indices:
        if runs and runs[-1][1] == index:
            runs[-1][0] += 1
        else:
            runs.append([1, index])
    return runs


def encode(section: Section) -> bytes:
    """The section's bytes, without the footer."""
    strings, index = [], {}

    def string(value):
        if value is None:
            return NONE
        if value not in index:
            index[value] = len(strings)
            strings.append(value)
        return index[value]

    sets = []
    for cmf_set in section.sets:
        flags = 0
        red = green = blue = alpha = 0
        if cmf_set.rgba is not None:
            flags |= FLAG_COLOR
            red, green, blue = (max(0, min(255, int(c))) for c in cmf_set.rgba[:3])
            alpha = _byte(cmf_set.rgba[3])
        roughness = metallic = 0
        if cmf_set.roughness is not None:
            flags |= FLAG_ROUGHNESS
            roughness = _byte(cmf_set.roughness)
        if cmf_set.metallic is not None:
            flags |= FLAG_METALLIC
            metallic = _byte(cmf_set.metallic)
        sets.append(
            _SET.pack(
                string(cmf_set.color),
                string(cmf_set.material),
                string(cmf_set.finish),
                string(cmf_set.origin),
                red,
                green,
                blue,
                alpha,
                roughness,
                metallic,
                flags,
            )
        )
    # The textures, if any set has one: after everything a reader that knows
    # none reads (see the module's docstring), each image once however many
    # sets it draws. Worked out before the strings are written, since a
    # texture's name is one of them.
    looks, images, image_index = [], [], {}
    for set_index, cmf_set in enumerate(section.sets):
        texture = cmf_set.texture
        if texture is None:
            continue
        if texture.digest not in image_index:
            image_index[texture.digest] = len(images)
            images.append(texture.image)
        looks.append(
            _LOOK.pack(set_index, string(texture.name), image_index[texture.digest], texture.width, texture.height)
        )
    out = [struct.pack("<H", len(strings))]
    for value in strings:
        data = value.encode("utf-8")
        out.append(struct.pack("<H", len(data)) + data)
    out.append(struct.pack("<H", len(sets)))
    out.extend(sets)
    out.append(struct.pack("<i", section.default))
    for indices in (section.solids, section.faces):
        runs = _runs(indices)
        out.append(struct.pack("<II", len(indices), len(runs)))
        out.extend(struct.pack("<Ii", length, value) for length, value in runs)
    if looks:
        out.append(LOOKS_MAGIC + struct.pack("<H", len(looks)))
        out.extend(looks)
        out.append(struct.pack("<H", len(images)))
        out.extend(_LENGTH.pack(len(image)) + image for image in images)
    return b"".join(out)


def decode(data: bytes) -> Section:
    """The section 'data' holds - the inverse of 'encode'."""
    offset = 0

    def take(fmt):
        nonlocal offset
        values = struct.unpack_from(fmt, data, offset)
        offset += struct.calcsize(fmt)
        return values

    (count,) = take("<H")
    strings = []
    for _ in range(count):
        (length,) = take("<H")
        strings.append(data[offset : offset + length].decode("utf-8"))
        offset += length

    def string(i):
        return strings[i] if 0 <= i < len(strings) else None

    (count,) = take("<H")
    sets = []
    for _ in range(count):
        color, material, finish, origin, red, green, blue, alpha, roughness, metallic, flags = _SET.unpack_from(
            data, offset
        )
        offset += _SET.size
        sets.append(
            CmfSet(
                string(color),
                string(material),
                string(finish),
                string(origin),
                (red, green, blue, alpha / 255.0) if flags & FLAG_COLOR else None,
                roughness / 255.0 if flags & FLAG_ROUGHNESS else None,
                metallic / 255.0 if flags & FLAG_METALLIC else None,
            )
        )
    (default,) = take("<i")
    expanded = []
    for _ in range(2):
        total, runs = take("<II")
        indices = []
        for _ in range(runs):
            length, value = take("<Ii")
            indices.extend([value] * length)
        if len(indices) != total:
            raise ValueError("a CMF section's runs cover %d of %d sub-shapes" % (len(indices), total))
        expanded.append(indices)
    if data[offset : offset + len(LOOKS_MAGIC)] == LOOKS_MAGIC:
        offset += len(LOOKS_MAGIC)
        (count,) = take("<H")
        looks = [take(_LOOK.format) for _ in range(count)]
        (count,) = take("<H")
        images = []
        for _ in range(count):
            (length,) = take("<I")
            if offset + length > len(data):
                raise ValueError("a CMF section's image runs past its end")
            images.append(data[offset : offset + length])
            offset += length
        for set_index, name, image, width, height in looks:
            if not (0 <= set_index < len(sets) and 0 <= image < len(images)):
                raise ValueError("a CMF section's texture names a set or an image it does not hold")
            sets[set_index].texture = Texture(images[image], string(name), width, height)
    return Section(sets, default, expanded[0], expanded[1])


def split(payload: bytes):
    """'(brep, section)' of an uncompressed payload; the section is None when it carries none."""
    if not payload.endswith(FOOTER_MAGIC) or len(payload) < _FOOTER_SIZE:
        return payload, None
    (length,) = _LENGTH.unpack_from(payload, len(payload) - _FOOTER_SIZE)
    start = len(payload) - _FOOTER_SIZE - length
    if start < 0:
        return payload, None
    return payload[:start], decode(payload[start : len(payload) - _FOOTER_SIZE])


def join(brep: bytes, section) -> bytes:
    """An uncompressed payload of 'brep' and 'section'; just the BREP when there is no section to carry."""
    if section is None or section.is_empty():
        return brep
    data = encode(section)
    return brep + data + _LENGTH.pack(len(data)) + FOOTER_MAGIC
