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

# Paints that name no colour, so there is nothing for the palette to reject.
NOT_A_COLOUR = {"none", "inherit", "transparent"}

DRAWN = ("partcad-open.svg", "partcad-refresh.svg", "partcad-import.svg")

SVG = "{http://www.w3.org/2000/svg}"
GREY, AMBER = "#707070", "#F5BB2B"

# `fill:`/`stroke:` inside a style attribute or a <style> block, which is where
# `partcad.svg` keeps its four ambers.
STYLED = re.compile(r"(?:fill|stroke)\s*:\s*([^;}\s]+)")


def icons():
    return sorted(ICON_DIR.glob("*.svg"))


def paints(root):
    """Every colour the file asks for, however it spells it.

    Attributes and style declarations both, because reading only one of them is
    how `fill="red"` slips past a check that scans for hex: the file still has
    palette colours in it, so a test looking for stray *hex* finds nothing
    wrong.
    """
    for element in root.iter():
        for name in ("fill", "stroke", "stop-color"):
            value = element.get(name)
            if value is not None:
                yield value.strip()
        yield from (v.strip() for v in STYLED.findall(element.get("style") or ""))
        if element.tag == f"{SVG}style":
            yield from (v.strip() for v in STYLED.findall(element.text or ""))


def geometry(group):
    """The path data a <g> draws, in order."""
    return [path.get("d") for path in group.iter(f"{SVG}path")]


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
    """One toolbar, one set of colours, however the file spells them."""
    used = {paint for paint in paints(ElementTree.parse(path).getroot()) if paint.lower() not in NOT_A_COLOUR}
    assert used, f"{path.name} names no colour at all"
    assert used <= PALETTE, f"{path.name} uses {sorted(used - PALETTE)}, which is not in the mark's palette"


@pytest.mark.parametrize("path", icons(), ids=lambda path: path.name)
def test_no_icon_reaches_for_use(path):
    """FreeCAD draws these through QtSvg, which implements part of SVG.

    Which part is not something to find out from a user whose toolbar has a
    gap in it, so the icons repeat their paths instead. See AGENTS.md.
    """
    root = ElementTree.parse(path).getroot()
    assert not list(root.iter(f"{SVG}use")), f"{path.name} uses <use>; write the paths out instead"


@pytest.mark.parametrize("name", DRAWN)
def test_the_drawn_icons_are_the_amber_traced_over_a_grey_keyline(name):
    """The grey pass is what keeps them legible on a light toolbar.

    Amber alone is nearly invisible on one, which is why each of these is
    stroked twice; losing the grey pass, or letting the two passes drift into
    different shapes, would not fail anything else and would not be visible on
    the dark theme it was checked on. So the geometry is compared rather than
    the two colours merely being present: a keyline that no longer traces the
    icon is not a keyline.
    """
    root = ElementTree.parse(ICON_DIR / name).getroot()
    groups = [child for child in root if child.tag == f"{SVG}g"]
    assert len(groups) == 2, f"{name} has {len(groups)} groups; it should be a grey pass and an amber one"

    keyline, over = groups
    assert keyline.get("stroke") == GREY, f"{name} draws {keyline.get('stroke')} first, not the {GREY} keyline"
    assert over.get("stroke") == AMBER, f"{name} draws {over.get('stroke')} over the keyline, not {AMBER}"
    assert float(keyline.get("stroke-width")) > float(
        over.get("stroke-width")
    ), f"{name}'s keyline is not wider than the amber over it, so none of it shows"
    assert geometry(keyline) == geometry(over), f"{name}'s two passes draw different shapes"
    assert geometry(over), f"{name} draws no paths at all"
