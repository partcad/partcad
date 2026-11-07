#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Decoding a meshopt-compressed glTF buffer view: 'EXT_meshopt_compression' and 'KHR_meshopt_compression'.

What 'gltfpack', 'gltf-transform meshopt' and most of the tools that make glTF
small for the web write. A buffer view that carries either extension holds its
bytes compressed by one of three codecs, named by its 'mode':

- 'ATTRIBUTES': vertex data, as byte-wise deltas between consecutive elements,
  version 0 (the only one 'EXT_meshopt_compression' has) or version 1 (which
  'KHR_meshopt_compression' adds: per-byte control modes, and deltas over two
  and four bytes);
- 'TRIANGLES': a triangle list, as codes against FIFOs of recent edges and
  vertices;
- 'INDICES': any other index sequence, as deltas against two baselines;

and, for attributes, by a 'filter' run over what that decoded to: 'OCTAHEDRAL'
(unit vectors), 'QUATERNION', 'EXPONENTIAL' (floats with a shared exponent) and,
in the KHR extension only, 'COLOR' (YCoCg).

This is a decoder written from the two specifications' Appendix A and B, in
Python and NumPy, because what the sandbox can install has none: the reference
decoder is C++ and WebAssembly, and its Python bindings do not reach every
platform and interpreter PartCAD's sandbox runs. It is checked against that
reference - the tests decode what meshoptimizer's own encoder wrote, every mode,
both versions and every filter, and a file 'gltfpack' wrote - and it is slower
than it by far, which a part read once and cached can afford.

Everything takes and gives bytes; a stream that is not one of these, or is cut
short, or has bytes over, is a ValueError naming what is wrong with it.
"""

import numpy as np

# What this produces is what a 'gltf' part is made of: a change to what it
# decodes is a change to 'wrapper_import_gltf''s CACHE_VERSION, which is the
# number the cache reads (see 'partcad.code_version').

MODES = ("ATTRIBUTES", "TRIANGLES", "INDICES")
FILTERS = ("NONE", "OCTAHEDRAL", "QUATERNION", "EXPONENTIAL", "COLOR")

# The packed deltas of a group, unpacked a byte at a time: 2- and 4-bit deltas
# are stored from the most significant bit down, 1-bit ones (version 1 only)
# from the least significant bit up.
_UNPACK = {
    1: [[(byte >> shift) & 1 for shift in range(8)] for byte in range(256)],
    2: [[(byte >> shift) & 3 for shift in (6, 4, 2, 0)] for byte in range(256)],
    4: [[byte >> 4, byte & 15] for byte in range(256)],
}

# The bits a group's delta is stored in, by its two header bits: in version 0,
# and in version 1 by the control mode of its byte position.
_BITS_V0 = (0, 2, 4, 8)
_BITS_V1 = ((0, 1, 2, 4), (1, 2, 4, 8))


def decode(data, count: int, stride: int, mode: str, filter_name: str = "NONE", khr: bool = False) -> bytes:
    """The bytes a compressed buffer view stands for: 'count' elements of 'stride' bytes.

    'khr' says the view is 'KHR_meshopt_compression''s, which is what allows the
    'COLOR' filter; both extensions read version 0 and 1 vertex streams alike,
    since a version 1 stream says so in its first byte.
    """
    mode = mode or ""
    filter_name = filter_name or "NONE"
    if mode not in MODES:
        raise ValueError("unknown meshopt compression mode '%s'" % mode)
    if filter_name not in FILTERS or (filter_name == "COLOR" and not khr):
        raise ValueError("unknown meshopt filter '%s'" % filter_name)
    if mode == "ATTRIBUTES":
        decoded = decode_vertex_buffer(data, count, stride)
        return apply_filter(decoded, count, stride, filter_name)
    if filter_name != "NONE":
        raise ValueError("a meshopt index stream takes no filter, and this one names '%s'" % filter_name)
    if mode == "TRIANGLES":
        return decode_index_buffer(data, count, stride)
    return decode_index_sequence(data, count, stride)


def _truncated(what):
    return ValueError("the meshopt %s stream is cut short" % what)


def decode_vertex_buffer(data, count: int, stride: int) -> bytes:
    """Mode 'ATTRIBUTES': 'count' elements of 'stride' bytes, version 0 or 1."""
    data = bytes(data)
    if stride <= 0 or stride > 256 or stride % 4:
        raise ValueError("a meshopt attribute stride is a multiple of 4 up to 256, not %d" % stride)
    if not data or data[0] & 0xF0 != 0xA0:
        raise ValueError("not a meshopt attribute stream (it starts with %s)" % (hex(data[0]) if data else "nothing"))
    version = data[0] & 0x0F
    if version > 1:
        raise ValueError("meshopt attribute stream version %d is newer than PartCAD reads (0 and 1)" % version)

    channel_count = stride // 4
    tail = stride + (channel_count if version == 1 else 0)
    padded = max(tail, 24 if version == 1 else 32)
    if len(data) < 1 + padded:
        raise _truncated("attribute")
    limit = len(data) - padded
    last = np.frombuffer(data, np.uint8, stride, len(data) - tail).copy()
    channels = data[len(data) - tail + stride :] if version == 1 else bytes(channel_count)
    for channel in channels:
        if channel & 0x0F > 2 or (channel & 0x0F < 2 and channel >> 4):
            raise ValueError("meshopt attribute channel mode 0x%02x is not one PartCAD reads" % channel)

    out = np.empty((count, stride), np.uint8)
    block_limit = min((8192 // stride) & ~15, 256)
    pos = 1
    done = 0
    while done < count:
        elements = min(count - done, block_limit)
        groups = (elements + 15) // 16
        controls = b""
        if version == 1:
            controls = data[pos : pos + channel_count]
            pos += channel_count
        planes = np.zeros((stride, groups * 16), np.uint8)
        for k in range(stride):
            if version == 1:
                control = (controls[k >> 2] >> ((k & 3) << 1)) & 3
                if control == 2:
                    continue  # every delta of this byte is 0
                if control == 3:
                    # Literal: the deltas themselves, a byte each, no header.
                    if pos + elements > limit:
                        raise _truncated("attribute")
                    planes[k, :elements] = np.frombuffer(data, np.uint8, elements, pos)
                    pos += elements
                    continue
                bits_of = _BITS_V1[control]
            else:
                bits_of = _BITS_V0
            header = data[pos : pos + (groups + 3) // 4]
            pos += (groups + 3) // 4
            row = []
            for group in range(groups):
                bits = bits_of[(header[group >> 2] >> ((group & 3) << 1)) & 3]
                pos = _group(data, pos, bits, row)
            if pos > limit:
                raise _truncated("attribute")
            planes[k] = row
        values = _undelta(planes[:, :elements], last, channels)
        out[done : done + elements] = values
        last = values[-1].copy()
        done += elements
    if pos != limit:
        raise ValueError("the meshopt attribute stream has %d bytes it does not use" % (limit - pos))
    return out.tobytes()


def _group(data, pos: int, bits: int, row: list) -> int:
    """Append a group's 16 deltas of 'bits' each, stored at 'pos', to 'row'; the position after them."""
    if bits == 0:
        row.extend((0,) * 16)
        return pos
    if bits == 8:
        row.extend(data[pos : pos + 16])
        return pos + 16
    size = 2 * bits  # 16 deltas of 'bits' each
    table = _UNPACK[bits]
    start = len(row)
    for byte in data[pos : pos + size]:
        row.extend(table[byte])
    pos += size
    # A delta of all ones - the sentinel - is too big for its bits and follows
    # as a byte of its own, in order.
    sentinel = (1 << bits) - 1
    for index in range(start, start + 16):
        if row[index] == sentinel:
            row[index] = data[pos]
            pos += 1
    return pos


def _undelta(planes, last, channels):
    """The elements a block's delta planes ('stride' rows of one byte each per element) stand for.

    Each four bytes of the element are a channel, and its mode - always 0 in
    version 0 - says what the deltas are: zigzagged byte differences (0), zigzagged
    16-bit differences (1), or 32-bit XORs rotated left by the mode's high four bits
    (2). Every element is the one before it plus its delta, the first the one before
    the block ('last').
    """
    stride, elements = planes.shape
    values = np.empty((elements, stride), np.uint8)
    for channel, mode_byte in enumerate(channels):
        mode, rotation = mode_byte & 0x0F, mode_byte >> 4
        first = channel * 4
        if mode == 0:
            for k in range(first, first + 4):
                delta = planes[k]
                delta = (delta >> 1) ^ ((delta & 1) * np.uint8(0xFF))
                values[:, k] = np.cumsum(delta, dtype=np.uint8) + last[k]
        elif mode == 1:
            for k in (first, first + 2):
                delta = planes[k].astype(np.uint16) | (planes[k + 1].astype(np.uint16) << 8)
                delta = (delta >> 1) ^ ((delta & 1) * np.uint16(0xFFFF))
                previous = np.uint16(int(last[k]) | (int(last[k + 1]) << 8))
                value = np.cumsum(delta, dtype=np.uint16) + previous
                values[:, k] = value & 0xFF
                values[:, k + 1] = value >> 8
        else:
            delta = np.zeros(elements, np.uint32)
            for byte in range(4):
                delta |= planes[first + byte].astype(np.uint32) << np.uint32(8 * byte)
            if rotation:
                # The encoder rotated the XOR left ('rotate' in the specification);
                # undoing it is rotating it back, right.
                delta = (delta >> np.uint32(rotation)) | (delta << np.uint32(32 - rotation))
            previous = np.uint32(int.from_bytes(bytes(last[first : first + 4]), "little"))
            value = np.bitwise_xor.accumulate(delta) ^ previous
            for byte in range(4):
                values[:, first + byte] = (value >> np.uint32(8 * byte)) & 0xFF
    return values


def _leb128(data, pos: int):
    """'(value, position after it)' of the unsigned LEB128 integer at 'pos'."""
    value = 0
    shift = 0
    while True:
        try:
            byte = data[pos]
        except IndexError:
            raise _truncated("index") from None
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
        if shift > 35:
            raise ValueError("a meshopt index stream has an integer longer than 32 bits")


def _indices(values, index_size: int) -> bytes:
    if index_size not in (2, 4):
        raise ValueError("a meshopt index is 2 or 4 bytes, not %d" % index_size)
    array = np.asarray(values, dtype=np.uint64)
    if index_size == 2:
        return (array & 0xFFFF).astype("<u2").tobytes()
    return (array & 0xFFFFFFFF).astype("<u4").tobytes()


def decode_index_buffer(data, count: int, index_size: int) -> bytes:
    """Mode 'TRIANGLES': 'count' indices, a multiple of three, of 'index_size' bytes."""
    data = bytes(data)
    if count % 3:
        raise ValueError("a meshopt triangle stream holds a multiple of 3 indices, not %d" % count)
    triangles = count // 3
    if len(data) < 1 + triangles + 16:
        raise _truncated("triangle")
    if data[0] != 0xE1:
        raise ValueError("not a meshopt triangle stream PartCAD reads (it starts with 0x%02x, not 0xe1)" % data[0])
    codeaux = data[-16:]
    limit = len(data) - 16
    pos = 1 + triangles
    edges = [(0, 0)] * 16
    edge_at = 0
    vertices = [0] * 16
    vertex_at = 0
    next_index = 0
    last = 0
    out = []
    mask = 0xFFFFFFFF

    for code in data[1 : 1 + triangles]:
        if code < 0xF0:
            # A recent edge, and a third vertex that is new, recent, next to
            # 'last', or stated.
            a, b = edges[(edge_at - 1 - (code >> 4)) & 15]
            third = code & 15
            if third == 0:
                c = next_index
                next_index += 1
                vertices[vertex_at] = c
                vertex_at = (vertex_at + 1) & 15
            elif third < 0x0D:
                c = vertices[(vertex_at - 1 - third) & 15]
            else:
                if third == 0x0F:
                    value, pos = _leb128(data, pos)
                    delta = ~(value >> 1) if value & 1 else value >> 1
                    c = (last + delta) & mask
                else:
                    c = (last + (1 if third == 0x0E else -1)) & mask
                last = c
                vertices[vertex_at] = c
                vertex_at = (vertex_at + 1) & 15
            edges[edge_at] = (c, b)
            edge_at = (edge_at + 1) & 15
            edges[edge_at] = (a, c)
            edge_at = (edge_at + 1) & 15
        else:
            if code < 0xFE:
                aux = codeaux[code & 15]
                explicit = False
            else:
                if pos >= limit:
                    raise _truncated("triangle")
                aux = data[pos]
                pos += 1
                if aux == 0:
                    next_index = 0
                explicit = code == 0xFF
            second, third = aux >> 4, aux & 15
            if explicit:
                value, pos = _leb128(data, pos)
                delta = ~(value >> 1) if value & 1 else value >> 1
                a = last = (last + delta) & mask
            else:
                a = next_index
                next_index += 1
            corners = []
            for which in (second, third):
                if which == 0:
                    corners.append(next_index)
                    next_index += 1
                elif which < 0x0F or code < 0xFE:
                    corners.append(vertices[(vertex_at - which) & 15])
                else:
                    value, pos = _leb128(data, pos)
                    delta = ~(value >> 1) if value & 1 else value >> 1
                    last = (last + delta) & mask
                    corners.append(last)
            b, c = corners
            vertices[vertex_at] = a
            vertex_at = (vertex_at + 1) & 15
            if second == 0 or (second == 0x0F and code >= 0xFE):
                vertices[vertex_at] = b
                vertex_at = (vertex_at + 1) & 15
            if third == 0 or (third == 0x0F and code >= 0xFE):
                vertices[vertex_at] = c
                vertex_at = (vertex_at + 1) & 15
            for edge in ((b, a), (c, b), (a, c)):
                edges[edge_at] = edge
                edge_at = (edge_at + 1) & 15
        out.extend((a, b, c))
        if pos > limit:
            raise _truncated("triangle")
    if pos != limit:
        raise ValueError("the meshopt triangle stream has %d bytes it does not use" % (limit - pos))
    return _indices(out, index_size)


def decode_index_sequence(data, count: int, index_size: int) -> bytes:
    """Mode 'INDICES': 'count' indices of 'index_size' bytes, as deltas against two baselines."""
    data = bytes(data)
    if len(data) < 1 + count + 4:
        raise _truncated("index")
    if data[0] != 0xD1:
        raise ValueError("not a meshopt index stream PartCAD reads (it starts with 0x%02x, not 0xd1)" % data[0])
    limit = len(data) - 4
    baselines = [0, 0]
    pos = 1
    out = []
    for _ in range(count):
        value, pos = _leb128(data, pos)
        delta = ~(value >> 2) if value & 2 else value >> 2
        which = value & 1
        baselines[which] = (baselines[which] + delta) & 0xFFFFFFFF
        out.append(baselines[which])
    if pos != limit:
        raise ValueError("the meshopt index stream has %d bytes it does not use" % (limit - pos))
    return _indices(out, index_size)


def _round(values):
    """To the nearest integer, a half away from zero, as the reference decoder rounds."""
    return np.trunc(values + np.where(values >= 0, np.float32(0.5), np.float32(-0.5)))


def apply_filter(data: bytes, count: int, stride: int, filter_name: str) -> bytes:
    """Appendix B: 'data' - 'count' elements of 'stride' bytes - with 'filter_name' undone."""
    if filter_name == "NONE":
        return data
    if filter_name in ("OCTAHEDRAL", "COLOR") and stride not in (4, 8):
        raise ValueError("the meshopt %s filter takes 4 or 8 bytes an element, not %d" % (filter_name, stride))
    if filter_name == "QUATERNION" and stride != 8:
        raise ValueError("the meshopt QUATERNION filter takes 8 bytes an element, not %d" % stride)
    if filter_name == "EXPONENTIAL" and stride % 4:
        raise ValueError("the meshopt EXPONENTIAL filter takes a multiple of 4 bytes an element, not %d" % stride)

    if filter_name == "EXPONENTIAL":
        raw = np.frombuffer(data, "<i4").astype(np.int64)
        exponent = raw >> 24
        mantissa = ((raw & 0xFFFFFF) ^ 0x800000) - 0x800000
        scale = np.ldexp(np.float32(1), exponent.astype(np.int32)).astype(np.float32)
        return (mantissa.astype(np.float32) * scale).astype("<f4").tobytes()

    wide = stride == 8
    if filter_name == "OCTAHEDRAL":
        signed = np.frombuffer(data, "<i2" if wide else "i1").reshape(count, 4)
        top = np.float32(32767.0 if wide else 127.0)
        v = signed.astype(np.float32)
        one = v[:, 2]
        x = v[:, 0] / one
        y = v[:, 1] / one
        z = np.float32(1) - np.abs(x) - np.abs(y)
        t = np.minimum(z, np.float32(0))
        x = x + np.where(x >= 0, t, -t)
        y = y + np.where(y >= 0, t, -t)
        scale = top / np.sqrt(x * x + y * y + z * z)
        out = np.empty_like(signed)
        out[:, 0] = _round(x * scale)
        out[:, 1] = _round(y * scale)
        out[:, 2] = _round(z * scale)
        out[:, 3] = signed[:, 3]
        return out.tobytes()

    if filter_name == "QUATERNION":
        signed = np.frombuffer(data, "<i2").reshape(count, 4)
        v = signed.astype(np.float32)
        one = (signed[:, 3] | 3).astype(np.float32)
        scale = np.float32(1.0 / np.sqrt(2.0)) / one
        x, y, z = v[:, 0] * scale, v[:, 1] * scale, v[:, 2] * scale
        w = np.sqrt(np.maximum(np.float32(0), np.float32(1) - x * x - y * y - z * z))
        top = np.float32(32767.0)
        largest = signed[:, 3] & 3
        out = np.empty_like(signed)
        rows = np.arange(count)
        out[rows, (largest + 1) & 3] = _round(x * top)
        out[rows, (largest + 2) & 3] = _round(y * top)
        out[rows, (largest + 3) & 3] = _round(z * top)
        out[rows, largest] = _round(w * top)
        return out.tobytes()

    # COLOR: YCoCg with alpha, whose highest set bit says how many bits each has.
    unsigned = np.frombuffer(data, "<u2" if wide else "u1").reshape(count, 4).astype(np.int64)
    signed = np.frombuffer(data, "<i2" if wide else "i1").reshape(count, 4).astype(np.int64)
    alpha_in = unsigned[:, 3]
    scale_bits = np.zeros(count, np.int64)
    for bit in range(16 if wide else 8):
        scale_bits = np.where((alpha_in >> bit) & 1, bit, scale_bits)
    alpha_scale = (np.int64(1) << (scale_bits + 1)) - 1
    luma, co, cg = unsigned[:, 0], signed[:, 1], signed[:, 2]
    red = luma + co - cg
    green = luma + cg
    blue = luma - co - cg
    alpha = alpha_in & (alpha_scale >> 1)
    alpha = (alpha << 1) | (alpha & 1)
    top = 65535.0 if wide else 255.0
    factor = (np.float32(top) / alpha_scale.astype(np.float32)).astype(np.float32)
    out = np.empty((count, 4), np.uint16 if wide else np.uint8)
    for column, channel in enumerate((red, green, blue, alpha)):
        out[:, column] = np.clip(_round(channel.astype(np.float32) * factor), 0, top)
    return out.astype("<u2" if wide else "u1").tobytes()
