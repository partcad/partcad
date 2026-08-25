#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Render the PartCAD logo into the icon formats an application bundle needs.

The source is `ide/vscode/resources/logo.svg`, the same logo the VS Code
extension uses, so the IDE cannot end up with an icon that has drifted from the
project's. The icons are built with the IDE rather than kept as binaries next to
it, with one exception: `../resources/partcad-ide.ico` is in git, because
`cairocffi` cannot load a `libcairo` on Windows and so this script cannot run
there at all. Regenerate that one whenever the logo changes:

    python tools/make_icons.py --svg ../partcad-ide-vscode/resources/logo.svg \
        --output-dir /tmp/icons && cp /tmp/icons/partcad-ide.ico resources/

Outputs (into `--output-dir`):
  partcad-ide.png    512x512, the Linux window and launcher icon
  partcad-ide.ico    16-256, the Windows executable and window icon
  partcad-ide.icns   32-1024, the macOS application bundle icon

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

# How much of the icon's edge is left empty. The logo is a wireframe drawing
# that touches the edges of its viewBox; every platform crops or rounds the
# corners of an application icon, and without a margin the drawing loses lines.
MARGIN = 0.08


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
    from PIL import Image

    largest = Image.open(io.BytesIO(images[max(images)])).convert("RGBA")
    largest.save(path, format="ICO", sizes=[(size, size) for size in ICO_SIZES])


def main(argv: list[str] | None = None) -> int:
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

    for generated in sorted(args.output_dir.glob(f"{args.name}.*")):
        print(f"{generated} ({generated.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
