#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Render the PartCAD logo into every image an application bundle and its installer
need.

The source is `ide/vscode/resources/logo.svg`, the same logo the VS Code
extension uses, so the IDE cannot end up with an icon that has drifted from the
project's. Most of these are built with the IDE rather than kept as binaries
next to it; the Windows three are in git, because `cairocffi` cannot load a
`libcairo` on Windows and so this script cannot run there at all. Regenerate
those whenever the logo changes, from the repository root:

    python ide/standalone/tools/make_icons.py \
        --svg ide/vscode/resources/logo.svg --output-dir /tmp/icons
    cp /tmp/icons/partcad-ide.ico /tmp/icons/partcad-ide-wizard*.bmp \
        ide/standalone/resources/

Outputs (into `--output-dir`):
  partcad-ide.png                512x512, the Linux window and launcher icon
  partcad-ide.ico                16-256, the Windows executable and window icon
  partcad-ide.icns               32-1024, the macOS application bundle icon
  partcad-ide-wizard.bmp         164x314, the Windows installer's side panel
  partcad-ide-wizard-small.bmp   55x55, its page header

Needs `cairosvg` (to rasterize) and `Pillow` (to write the `.ico`). `build.sh`
treats both as optional: without them the build keeps VSCodium's icons and says
so, rather than failing over an icon.
"""

import argparse
import io
import pathlib
import struct
import sys

# The `.icns` entry types, by the pixel size of the image they hold. Every one
# of these takes a PNG payload, which is why the file can be assembled here
# rather than with `iconutil` (which exists only on macOS, and this build has to
# produce a macOS bundle from a macOS runner but its icons from anywhere).
ICNS_TYPES = {
    32: b"ic11",  # 16x16@2x
    64: b"ic12",  # 32x32@2x
    128: b"ic07",
    256: b"ic13",  # 128x128@2x
    512: b"ic14",  # 256x256@2x
    1024: b"ic10",  # 512x512@2x
}

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# The two images Inno Setup draws the wizard with: the panel beside the welcome
# and finished pages, and the badge in the header of every page between them.
# The sizes are the ones Inno's own images use, and Inno scales them for a
# high-DPI display. They are Windows bitmaps because that is the one format
# every Inno Setup reads -- it is the only consumer here that cannot be handed
# the SVG, and `.png` in this repository is Git LFS, which no checkout in CI
# fetches. Written 8 bits deep, since between them they hold one flat ground and
# four ambers: a 24-bit pair would be three times the size in git for nothing.
#
# The panel carries the ground of `logo_128x128.png`; the header badge is on
# white, because the wizard's own header is, and a dark tile there would read as
# a hole rather than as a logo.
WIZARD_LARGE = (164, 314)
WIZARD_SMALL = (55, 55)
WIZARD_LARGE_GROUND = (0x44, 0x44, 0x44)
WIZARD_SMALL_GROUND = (0xFF, 0xFF, 0xFF)

# How much of the icon's edge is left empty. Every platform crops or rounds the
# corners of an application icon, and without a margin the drawing loses lines.
MARGIN = 0.08

# The same, for the wizard images. Small, because it is on top of the one
# `render` already leaves and because nothing crops these: it is only there to
# keep the mark off the edge of the panel.
WIZARD_MARGIN = 0.04


def render(svg_path: pathlib.Path, size: int) -> bytes:
    """Render the SVG to a square PNG of `size` pixels, with a margin."""
    import cairosvg  # imported here so `--help` works without it

    inner = max(1, round(size * (1.0 - 2.0 * MARGIN)))
    drawing = cairosvg.svg2png(url=str(svg_path), output_width=inner, output_height=inner)

    from PIL import Image

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = (size - inner) // 2
    canvas.alpha_composite(Image.open(io.BytesIO(drawing)).convert("RGBA"), (offset, offset))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def write_icns(images: dict[int, bytes], path: pathlib.Path) -> None:
    """Assemble an `.icns` file out of PNG images keyed by pixel size."""
    entries = b"".join(ICNS_TYPES[size] + struct.pack(">I", len(png) + 8) + png for size, png in sorted(images.items()))
    path.write_bytes(b"icns" + struct.pack(">I", len(entries) + 8) + entries)


def write_ico(images: dict[int, bytes], path: pathlib.Path) -> None:
    """Assemble a Windows `.ico` out of PNG images keyed by pixel size.

    Pillow builds every size in `ICO_SIZES` by downscaling the largest image it
    was given, rather than using the separately rendered one for each size.
    """
    from PIL import Image

    largest = Image.open(io.BytesIO(images[max(images)])).convert("RGBA")
    largest.save(path, format="ICO", sizes=[(size, size) for size in ICO_SIZES])


def write_wizard_image(svg_path: pathlib.Path, path: pathlib.Path, size, ground) -> None:
    """Draw the logo centred on a flat ground and write it as a Windows bitmap.

    Flattened onto an opaque ground rather than kept transparent, because a
    bitmap has no alpha channel for Inno Setup to read.
    """
    from PIL import Image

    width, height = size
    mark = max(1, round(min(width, height) * (1.0 - 2.0 * WIZARD_MARGIN)))
    canvas = Image.new("RGBA", size, ground + (255,))
    drawing = Image.open(io.BytesIO(render(svg_path, mark))).convert("RGBA")
    canvas.alpha_composite(drawing, ((width - mark) // 2, (height - mark) // 2))
    canvas.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256).save(path, format="BMP")


def main(argv: list[str] | None = None) -> int:
    """Render the logo once per size and write every icon and wizard image.

    Returns 1 without writing anything if `cairosvg` or Pillow is missing --
    which is every Windows machine, since `cairocffi` needs a `libcairo-2.dll`
    no wheel ships. That is why the Windows files are checked in.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--svg", type=pathlib.Path, required=True, help="the logo to render")
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--name", default="partcad-ide", help="base name of the generated files")
    args = parser.parse_args(argv)

    try:
        import cairosvg  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as error:
        print(f"error: {error}. Install them with: python -m pip install cairosvg pillow", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    images = {size: render(args.svg, size) for size in sorted(set(ICNS_TYPES) | set(ICO_SIZES))}

    png_path = args.output_dir / f"{args.name}.png"
    png_path.write_bytes(images[512])
    write_ico(images, args.output_dir / f"{args.name}.ico")
    write_icns({size: images[size] for size in ICNS_TYPES}, args.output_dir / f"{args.name}.icns")
    write_wizard_image(args.svg, args.output_dir / f"{args.name}-wizard.bmp", WIZARD_LARGE, WIZARD_LARGE_GROUND)
    write_wizard_image(args.svg, args.output_dir / f"{args.name}-wizard-small.bmp", WIZARD_SMALL, WIZARD_SMALL_GROUND)

    for generated in sorted(args.output_dir.glob(f"{args.name}*")):
        print(f"{generated} ({generated.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
