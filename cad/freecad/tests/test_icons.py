#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The workbench's icons: one mark, one palette, and no drift between copies.

`resources/icons/partcad.svg` is a *copy* of `ide/vscode/resources/logo.svg`,
and it has to be one: FreeCAD installs this addon on its own, through the Addon
Manager, so it cannot reach a file that lives in another component of this
repository. A copy is a thing that rots, so the first test here pins it to the
byte, and `AGENTS.md` says which single command refreshes it.

The rest of the icons are drawn rather than rendered, so what can rot in them is
the palette: a colour picked by eye is how a toolbar ends up with four ambers
that are nearly, but not quite, the project's.
"""

import pathlib
import re
import xml.etree.ElementTree as ElementTree

import pytest

COMPONENT_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = COMPONENT_ROOT.parents[1]
ICON_DIR = COMPONENT_ROOT / "resources" / "icons"
LOGO = REPO_ROOT / "ide" / "vscode" / "resources" / "logo.svg"

# The mark's own colours, and nothing else. `partcad.svg` carries all of them;
# the drawn icons use the amber and the edge grey the mark is outlined with.
PALETTE = {"#F5BB2B", "#FEC22E", "#EFB629", "#D6A224", "#707070"}

DRAWN = ("partcad-open.svg", "partcad-refresh.svg", "partcad-import.svg")

COLOUR = re.compile(r"#[0-9A-Fa-f]{3,8}")


def icons():
    return sorted(ICON_DIR.glob("*.svg"))


def test_the_workbench_icon_is_the_project_mark():
    """Byte for byte, so that a logo change cannot leave this one behind."""
    assert LOGO.is_file(), f"{LOGO} is missing"
    assert (ICON_DIR / "partcad.svg").read_bytes() == LOGO.read_bytes(), (
        "resources/icons/partcad.svg has drifted from ide/vscode/resources/logo.svg; "
        "refresh it with the command in AGENTS.md"
    )


@pytest.mark.parametrize("path", icons(), ids=lambda path: path.name)
def test_every_icon_is_well_formed_svg(path):
    """QtSvg reports nothing when it cannot parse an icon; it just draws none."""
    root = ElementTree.parse(path).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("viewBox"), f"{path.name} has no viewBox, so it cannot be scaled"


@pytest.mark.parametrize("path", icons(), ids=lambda path: path.name)
def test_every_icon_uses_the_project_palette(path):
    """One toolbar, one set of colours."""
    used = set(COLOUR.findall(path.read_text(encoding="utf-8")))
    assert used, f"{path.name} names no colour at all"
    assert used <= PALETTE, f"{path.name} uses {sorted(used - PALETTE)}, which is not in the mark's palette"


@pytest.mark.parametrize("name", DRAWN)
def test_the_drawn_icons_carry_a_keyline_under_the_amber(name):
    """The grey pass is what keeps them legible on a light toolbar.

    Amber alone is nearly invisible on one, which is the reason each of these
    is stroked twice; losing the grey pass in an edit would not fail anything
    else, and would not be visible on the dark theme it was checked on.
    """
    text = (ICON_DIR / name).read_text(encoding="utf-8")
    grey = re.search(r'stroke="#707070" stroke-width="([\d.]+)"', text)
    amber = re.search(r'stroke="#F5BB2B" stroke-width="([\d.]+)"', text)
    assert grey and amber, f"{name} no longer has both passes"
    assert float(grey.group(1)) > float(amber.group(1)), f"{name}'s keyline is not wider than the amber over it"
    assert text.index(grey.group(0)) < text.index(amber.group(0)), f"{name} draws the keyline over the amber"
