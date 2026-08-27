#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""The one icon that is checked in rather than rendered by the build.

`make_icons.py` cannot run on Windows -- `cairocffi` finds no `libcairo` there --
so `resources/partcad-ide.ico` is in git, and the Windows build takes it from
there. A file in git is a file that can rot, and the two ways it rots silently
are worth catching here: an `.ico` that no longer holds the sizes the generator
declares, and one that a bad checkout or a text-mode transfer has truncated.

What this cannot check is whether the icon still looks like the current logo.
That needs the renderers, which is the whole reason the file is checked in;
README.md says to regenerate it whenever the logo changes.
"""

import struct

import make_icons
import pytest
from conftest import COMPONENT_ROOT

ICON = COMPONENT_ROOT / "resources" / "partcad-ide.ico"


def entries():
    """The ICO directory: (width, height, offset, length) per image."""
    data = ICON.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "not an ICO file"
    parsed = []
    for index in range(count):
        width, height, _colors, _reserved, _planes, _bpp, length, offset = struct.unpack(
            "<BBBBHHII", data[6 + index * 16 : 22 + index * 16]
        )
        # An ICO stores 256 as 0, there being one byte for it.
        parsed.append((width or 256, height or 256, offset, length))
    return data, parsed


def test_the_checked_in_icon_is_there():
    """The build falls back to this file, so its absence must not be a warning."""
    assert ICON.is_file(), f"{ICON} is missing; regenerate it as README.md describes"


def test_it_holds_the_sizes_the_generator_declares():
    """The checked-in file must still be what 'make_icons.py' would produce today."""
    _data, parsed = entries()
    assert sorted(width for width, _height, _offset, _length in parsed) == sorted(make_icons.ICO_SIZES)
    for width, height, _offset, _length in parsed:
        assert width == height, f"the {width}x{height} image is not square"


@pytest.mark.parametrize("index", range(len(make_icons.ICO_SIZES)))
def test_every_image_is_wholly_inside_the_file(index):
    """A truncated or LFS-pointer '.ico' still parses as a directory of entries."""
    data, parsed = entries()
    _width, _height, offset, length = parsed[index]
    assert length > 0
    assert offset + length <= len(data), "the file is truncated"
