#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A colour drawn with an image: its 'display' as a raster texture.

A colour's 'display' is how to draw it (see 'partcad.cmf'): a CSS colour, the
reference of another colour - or, in its long form, an image::

    colors:
      walnut:
        display:
          image: textures/walnut.jpg   # a PNG or a JPEG, in the package
          size: 300                    # mm one copy of it covers across; or [width, height]
          color: "#5C3A21"             # (optional) what it is drawn as where only a colour can be

What the image is drawn on is a surface, so it is drawn wherever PartCAD draws
surfaces - a shaded picture, a video, glTF and the IDE's 3D view - covering each
face with copies of the image laid side by side, 'size' apart, from the side the
face looks towards ('texture_mapping' in the wrappers). Wherever only a colour
can be drawn - a line of a drawing, a swatch, a reader that knows no textures -
the colour is drawn as 'color', or as the mean colour of the image where it
states none. A texture is a hint, as a display colour is: it claims nothing.

The image is read once per file and kept for as long as the file is unchanged,
and checked as it is read: it has to be a PNG or a JPEG that decodes, inside the
package that names it, and no larger than MAX_IMAGE_BYTES - it travels inside the
payload of every part drawn with it (see 'cmf_section', 'Texture').
"""

import io
import os
import sys
import threading
import typing

from . import logging as pc_logging

# The wrappers directory is on the path for anything that imports 'partcad'
# (see 'shape.py'); said again so that this module stands on its own, as
# 'partcad.cmf' says it.
_WRAPPERS = os.path.join(os.path.dirname(__file__), "wrappers")
if _WRAPPERS not in sys.path:
    sys.path.append(_WRAPPERS)
import cmf_section  # noqa: E402
import css_color  # noqa: E402

# How much of a surface one copy of an image covers across when its colour does
# not say: ten centimetres, its height in proportion. A texture is a picture of
# a material - a grain, a weave, a finish - and that is the order of what one is
# a photograph of; a package that knows says.
DEFAULT_SIZE = 100.0

# The largest image a colour may be drawn with. It is carried inside the payload
# of every part drawn in that colour, sent to every sandbox drawing one and put
# in every glTF the IDE is shown: a texture is a picture of a surface, and four
# megapixels of JPEG are a few hundred kilobytes.
MAX_IMAGE_BYTES = 16 * 1024 * 1024

# The images read so far, by file: '(path, size, mtime) -> Image'. Shared by
# every package in the process - two packages naming one file read it once - and
# never stale, since a file that changes is a different key.
_images: dict = {}
_lock = threading.Lock()


class Image:
    """One image file, read and checked: its bytes, its size in pixels and its mean colour."""

    __slots__ = ("data", "pixels", "mean")

    def __init__(self, data: bytes, pixels: tuple, mean: tuple) -> None:
        self.data = data
        self.pixels = pixels
        self.mean = mean


def image_display(config) -> typing.Optional[dict]:
    """The long form of a 'display' - the mapping that names an image - or None for any other."""
    display = config.get("display") if isinstance(config, dict) else None
    if isinstance(display, dict) and isinstance(display.get("image"), str) and display["image"].strip():
        return display
    return None


def _read(path: str) -> Image:
    """The image at 'path', read and checked, or an exception saying why it is none."""
    from PIL import Image as PILImage

    stat = os.stat(path)
    key = (path, stat.st_size, stat.st_mtime_ns)
    with _lock:
        found = _images.get(key)
    if found is not None:
        return found
    if stat.st_size > MAX_IMAGE_BYTES:
        raise ValueError(
            "is %d bytes, more than the %d an image a colour is drawn with may be" % (stat.st_size, MAX_IMAGE_BYTES)
        )
    with open(path, "rb") as handle:
        data = handle.read()
    if cmf_section.image_type(data) is None:
        raise ValueError("is neither a PNG nor a JPEG")
    with PILImage.open(io.BytesIO(data)) as image:
        image.load()
        pixels = image.size
        if pixels[0] < 1 or pixels[1] < 1:
            raise ValueError("has no pixels")
        # The mean of every pixel, which a box filter shrinking the whole image
        # to one pixel is. Opaque: a texture is drawn opaque (see 'texture_of').
        mean = image.convert("RGB").resize((1, 1), PILImage.Resampling.BOX).getpixel((0, 0))
    found = Image(data, pixels, (int(mean[0]), int(mean[1]), int(mean[2]), 1.0))
    with _lock:
        _images[key] = found
    return found


def _size(display: dict, pixels: tuple) -> typing.Optional[tuple]:
    """'(width, height)' in millimetres one copy of the image covers, from 'size'; None if 'size' is not one."""
    size = display.get("size")
    aspect = pixels[1] / float(pixels[0])
    if size is None:
        return DEFAULT_SIZE, DEFAULT_SIZE * aspect
    if isinstance(size, bool):
        return None
    if isinstance(size, (int, float)):
        return (float(size), float(size) * aspect) if size > 0 else None
    if isinstance(size, (list, tuple)) and len(size) == 2:
        if all(isinstance(side, (int, float)) and not isinstance(side, bool) and side > 0 for side in size):
            return float(size[0]), float(size[1])
    return None


def load(declaration):
    """'(texture, rgba)' of a colour whose display is an image, or None if it is not one or cannot be read.

    'texture' is the 'cmf_section.Texture' the colour's surfaces are drawn with,
    and 'rgba' what the colour is drawn as wherever only a colour can be: the
    display's 'color', else the image's mean colour. What is wrong with the
    image is the declaration's error, said once (see 'Declaration.error').
    """
    display = image_display(getattr(declaration, "config", None))
    if display is None:
        return None
    written = display["image"].strip()
    base = getattr(declaration, "config_dir", None)
    if not base:
        declaration.error("names the image '%s', and its package has no directory to read it from" % written)
        return None
    root = os.path.realpath(base)
    path = os.path.realpath(os.path.join(root, written))
    # Inside the package: an image is carried with every part drawn with it, to
    # sandboxes and caches that need not be this machine's, and a package names
    # what it ships rather than what happens to be beside it on one machine.
    if os.path.commonpath([root, path]) != root:
        declaration.error("names the image '%s', which is outside its package" % written)
        return None
    try:
        image = _read(path)
    except FileNotFoundError:
        declaration.error("names the image '%s', which is not there" % written)
        return None
    except Exception as e:  # pylint: disable=broad-except
        declaration.error("names the image '%s', which %s" % (written, str(e) or type(e).__name__))
        return None
    size = _size(display, image.pixels)
    if size is None:
        declaration.error(
            "has a 'size' that is neither a length in millimetres nor [width, height]: %r" % (display.get("size"),)
        )
        size = _size({}, image.pixels)
    rgba = image.mean
    stated = display.get("color")
    if stated is not None:
        parsed = css_color.parse(stated) if isinstance(stated, str) else None
        if parsed is None:
            declaration.error("has a 'display: color:' that is not a CSS colour: %r" % (stated,))
        else:
            rgba = parsed
    return cmf_section.Texture(image.data, written, size[0], size[1]), rgba


def describe(declaration) -> typing.Optional[str]:
    """A colour's image display in words, as 'pc info' and 'pc list' say it; None if it is not one."""
    display = image_display(getattr(declaration, "config", None))
    if display is None:
        return None
    words = "image %s" % display["image"].strip()
    size = display.get("size")
    if isinstance(size, (list, tuple)) and len(size) == 2:
        words += ", %g x %g mm" % (size[0], size[1])
    elif isinstance(size, (int, float)) and not isinstance(size, bool):
        words += ", %g mm across" % size
    return words


def thumbnail(texture, pixels: int = 64) -> typing.Optional[str]:
    """A small PNG of a texture's image, as a 'data:' URL, for a swatch; None if it cannot be made."""
    import base64

    from PIL import Image as PILImage

    try:
        with PILImage.open(io.BytesIO(texture.image)) as image:
            image = image.convert("RGB")
            image.thumbnail((pixels, pixels))
            out = io.BytesIO()
            image.save(out, format="PNG")
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("No thumbnail of %s: %s" % (texture.name, e))
        return None
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
