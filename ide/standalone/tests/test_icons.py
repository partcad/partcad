#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""The three images that are checked in rather than rendered by the build.

`make_icons.py` cannot run on Windows -- `cairocffi` finds no `libcairo` there --
so `resources/partcad-ide.ico` and the two wizard bitmaps beside it are in git,
and the Windows build takes them from there. A file in git is a file that can
rot, and the ways they rot silently are worth catching here: an `.ico` that no
longer holds the sizes the generator declares, one that a bad checkout or a
text-mode transfer has truncated, and a bitmap that is no longer the size Inno
Setup draws or is no longer named by the installer script.

What this cannot check is whether any of them still looks like the current logo.
That needs the renderers, which is the whole reason the files are checked in;
README.md says to regenerate them whenever the logo changes.
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


# The wizard images beside it, in git for the same reason and rotting in the
# same two ways: Inno Setup fails the build on a bitmap it cannot parse, but a
# bitmap of the wrong size is one it silently stretches over the wizard.
WIZARD = {
    COMPONENT_ROOT / "resources" / "partcad-ide-wizard.bmp": make_icons.WIZARD_LARGE,
    COMPONENT_ROOT / "resources" / "partcad-ide-wizard-small.bmp": make_icons.WIZARD_SMALL,
}


def bitmap_header(path):
    """(width, height, bits per pixel) out of a Windows bitmap's two headers."""
    data = path.read_bytes()
    magic, size = struct.unpack("<2sI", data[:6])
    assert magic == b"BM", f"{path.name} is not a Windows bitmap"
    assert size == len(data), f"{path.name} is truncated"
    width, height, _planes, depth = struct.unpack("<iiHH", data[18:30])
    return width, height, depth


@pytest.mark.parametrize("path", sorted(WIZARD), ids=lambda path: path.name)
def test_the_wizard_image_is_there_and_is_the_size_inno_draws(path):
    """A bitmap Inno Setup has to stretch is one somebody drew at the wrong size."""
    assert path.is_file(), f"{path} is missing; regenerate it as README.md describes"
    width, height, depth = bitmap_header(path)
    assert (width, abs(height)) == WIZARD[path]
    assert depth in (8, 24), f"{path.name} is {depth} bits deep; Inno Setup wants a plain bitmap"


@pytest.mark.parametrize("path", sorted(WIZARD), ids=lambda path: path.name)
def test_the_installer_asks_for_the_wizard_image(path):
    """A file nothing names is one the wizard is not wearing."""
    script = (COMPONENT_ROOT / "installer" / "partcad-ide.iss").read_text(encoding="utf-8")
    assert f"\\{path.name}" in script, f"partcad-ide.iss no longer points at {path.name}"
