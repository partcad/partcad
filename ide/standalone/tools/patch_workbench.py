#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Put the PartCAD workbench at the top of the activity bar, in its own colours.

The activity bar -- the strip of icons down the side of the window that picks
what the side bar shows -- belongs to the editor, and an extension has no say
in how its entry there looks or where it goes:

- **The icon is drawn as a mask.** The editor paints a view container's icon
  file as a CSS `mask` over a flat fill in the theme's foreground colour, so
  every extension's icon comes out one shade of grey, whatever colours its file
  has. The rule is generated per icon, on a class named after the container
  (`activity-workbench-view-extension-partcad-container-<hash>`).
- **The order is the editor's.** Its own containers are numbered 0 to 6,
  Explorer first, and an extension's are numbered from 7 up as extensions
  register. `package.json` has no field for it.

So this edits the workbench itself, which is the one thing that can:

- one rule appended to `workbench.desktop.main.css`, which matches the
  PartCAD container's icon in any composite bar, removes the mask, and draws
  `logo.svg` in its place, at the size the mask had;
- two substitutions in `workbench.desktop.main.js`. The first gives the PartCAD
  container the order -1 when it is registered, which puts it ahead of Explorer
  (0) on a profile that has never seen it. The second is for every other
  profile, because the editor remembers the activity bar as the user last left
  it -- including where PartCAD was -- and places a container it remembers
  there, whatever its order. That remembered entry also records the order the
  container had, so the first start of this build on an older profile finds
  -1 where it remembered 7 or more, and the substitution moves PartCAD to the
  top on that one change. From then on the remembered order is -1 too, and
  wherever the user drags PartCAD is where it stays.

Then the checksums `product.json` keeps for both files are recomputed. The
editor compares them at startup and calls an installation whose files disagree
"corrupt", with a warning on every start.

The substitutions are written against the *minified* workbench, which is what
VSCodium ships, so they name structure rather than identifiers: the minifier
renames every local variable on each release, and leaves property names, method
names and string literals alone. Each one must match exactly once; when an
upstream release changes the code underneath it, the build stops here and says
which one, rather than shipping an IDE whose PartCAD icon is quietly grey or
quietly sixth. The source each one corresponds to is quoted beside it, from
`microsoft/vscode`.

Running this again over a workbench it has already patched changes nothing.
"""

import argparse
import base64
import hashlib
import json
import pathlib
import re
import sys
from collections.abc import Callable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonc  # noqa: E402  (the path has to be set up first)

# The id the editor gives the view container `ide/vscode/package.json`
# contributes as `partcad-container`.
CONTAINER_ID = "workbench.view.extension.partcad-container"

# Relative to `<resources>/app/out`, which is also how `product.json` names
# them in `checksums`.
WORKBENCH_JS = "vs/workbench/workbench.desktop.main.js"
WORKBENCH_CSS = "vs/workbench/workbench.desktop.main.css"

# A JavaScript identifier, as the minifier writes one.
_NAME = r"[\w$]+"

# src/vs/workbench/api/browser/viewsExtensionPoint.ts, in
# `ViewsExtensionHandler.registerCustomViewContainer(id, title, icon, order, extensionId, location)`:
#
#     this.viewContainersRegistry.registerViewContainer({
#         id,
#         title: { value: title, original: title },
#         extensionId,
#         ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [id, { mergeViewWithContainerWhenSingleView: true }]),
#         hideIfEmpty: true,
#         order,
#         icon,
#     }, location);
#
# Every view container an extension contributes is registered here, and nothing
# else is: the editor registers its own one by one, elsewhere, and none of those
# passes its order in a variable.
ORDER_PATTERN = re.compile(
    rf"registerViewContainer\(\{{id:(?P<id>{_NAME}),title:\{{value:(?P<title>{_NAME}),original:(?P=title)\}},"
    rf"extensionId:{_NAME},ctorDescriptor:new {_NAME}\({_NAME},\[(?P=id),"
    rf"\{{mergeViewWithContainerWhenSingleView:!0\}}\]\),hideIfEmpty:!0,order:(?P<order>{_NAME})(?=[,}}])"
)
ORDER_APPLIED = f'==="{CONTAINER_ID}"?-1:'

# src/vs/workbench/browser/parts/compositeBar.ts, in `CompositeBarModel.add(id, name, order, requestedIndex)`,
# for a container the composite bar already has -- because the profile
# remembered it:
#
#     const item = this.findItem(id);
#     if (item) {
#         let changed = false;
#         item.name = name;
#         if (!isUndefinedOrNull(order)) {
#             changed = item.order !== order;
#             item.order = order;
#         }
#
# The substitution goes between the last two statements: when the item is
# PartCAD's and its order changed, it moves to the front of `this.items`, which
# is the activity bar from the top down.
MOVE_PATTERN = re.compile(
    rf"\badd\((?P<id>{_NAME}),{_NAME},(?P<order>{_NAME}),{_NAME}\)\{{let (?P<item>{_NAME})=this\.findItem\((?P=id)\);"
    rf"if\((?P=item)\)\{{[^{{}}]*?(?P<changed>{_NAME})=(?P=item)\.order!==(?P=order),"
    rf"(?=(?P=item)\.order=(?P=order)\))"
)
MOVE_APPLIED = f'==="{CONTAINER_ID}"&&this.items.unshift('

CSS_MARKER = "/* PartCAD IDE: the PartCAD workbench icon, in colour (ide/standalone/tools/patch_workbench.py) */"

# The class the editor puts on the container's icon is
# `activity-<id with "." spelled "-">-<hash of the icon's URL>`, so it is
# matched by its prefix. `:not(#partcad-ide)` matches every element (none has
# that id) and is there for its weight: the editor colours an icon with
# `background-color: ... !important` from selectors as many as eleven classes
# deep, and an id outweighs any number of classes.
#
# `--activity-bar-icon-size` is set on the activity bar only (24px, or 16px
# when it is compact); every other composite bar -- the side bar's header,
# when the activity bar is at the top, the panel, the secondary side bar --
# draws 16px icons, which is the fallback the editor's own rule uses too.
CSS_RULE = """
{marker}
.monaco-workbench .monaco-action-bar .action-label.uri-icon[class*="activity-{icon_class}-"]:not(#partcad-ide) {{
\t-webkit-mask: none !important;
\tmask: none !important;
\tbackground: url("data:image/svg+xml;base64,{icon}") no-repeat 50% 50% / var(--activity-bar-icon-size, 16px) !important;
}}
"""


def checksum(path: pathlib.Path) -> str:
    """What the editor's integrity check computes: SHA-256, in base64, without the padding."""
    return base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode("ascii").rstrip("=")


def substitute_once(
    text: str,
    pattern: re.Pattern[str],
    replacement: Callable[[re.Match[str]], str],
    applied: str,
    what: str,
    path: pathlib.Path,
) -> str:
    """Apply one substitution that must match exactly once, or recognise that it already has been."""
    if applied in text:
        return text
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        found = "no match" if not matches else f"{len(matches)} matches"
        raise SystemExit(
            f"error: {path}: {what}: {found} for the code this substitutes, where exactly one was expected. "
            "The workbench changed upstream; see the source quoted beside the pattern in "
            "ide/standalone/tools/patch_workbench.py, and update the pattern to the new code."
        )
    return pattern.sub(replacement, text, count=1)


def order_first(match: re.Match[str]) -> str:
    return f'{match.group(0)[: -len(match["order"])]}({match["id"]}==="{CONTAINER_ID}"?-1:{match["order"]})'


def move_to_top_once(match: re.Match[str]) -> str:
    item = match["item"]
    return (
        f'{match.group(0)}{match["changed"]}&&{match["id"]}==="{CONTAINER_ID}"'
        f"&&this.items.unshift(...this.items.splice(this.items.indexOf({item}),1)),"
    )


def icon_rule(icon: pathlib.Path) -> str:
    return CSS_RULE.format(
        marker=CSS_MARKER,
        icon_class=CONTAINER_ID.replace(".", "-"),
        icon=base64.b64encode(icon.read_bytes()).decode("ascii"),
    )


def patch(app_dir: pathlib.Path, icon: pathlib.Path) -> list[str]:
    """Patch the workbench under `<app_dir>/out`, and return the files that changed."""
    out = app_dir / "out"
    changed = []

    js_path = out / WORKBENCH_JS
    js = js_path.read_text(encoding="utf-8")
    patched = substitute_once(js, ORDER_PATTERN, order_first, ORDER_APPLIED, "the PartCAD workbench's order", js_path)
    patched = substitute_once(
        patched, MOVE_PATTERN, move_to_top_once, MOVE_APPLIED, "the PartCAD workbench's remembered place", js_path
    )
    if patched != js:
        js_path.write_text(patched, encoding="utf-8")
        changed.append(WORKBENCH_JS)

    css_path = out / WORKBENCH_CSS
    css = css_path.read_text(encoding="utf-8")
    if CSS_MARKER not in css:
        css_path.write_text(css + icon_rule(icon), encoding="utf-8")
        changed.append(WORKBENCH_CSS)

    update_checksums(app_dir, changed)
    return changed


def update_checksums(app_dir: pathlib.Path, changed: list[str]) -> None:
    """Recompute the `product.json` checksums of the files that changed, where it has one."""
    product_path = app_dir / "product.json"
    product = jsonc.load(product_path)
    checksums = product.get("checksums") or {}
    stale = [name for name in changed if name in checksums]
    if not stale:
        return
    for name in stale:
        checksums[name] = checksum(app_dir / "out" / name)
    product_path.write_text(json.dumps(product, indent=2) + "\n", encoding="utf-8")


def problems(app_dir: pathlib.Path) -> list[str]:
    """What is wrong with a patched workbench under `<app_dir>/out`: an empty list when nothing is."""
    out = app_dir / "out"
    found = []

    js_path = out / WORKBENCH_JS
    css_path = out / WORKBENCH_CSS
    for path in (js_path, css_path):
        if not path.is_file():
            found.append(f"no workbench at {path}")
    if found:
        return found

    js = js_path.read_text(encoding="utf-8")
    if ORDER_APPLIED not in js:
        found.append(f"{js_path}: the PartCAD workbench is not ordered first on the activity bar")
    if MOVE_APPLIED not in js:
        found.append(f"{js_path}: the PartCAD workbench is not moved to the top of an existing profile's activity bar")
    if CSS_MARKER not in css_path.read_text(encoding="utf-8"):
        found.append(f"{css_path}: the PartCAD workbench icon is not drawn in colour")

    # Every file, not just the two above: the editor checks every one it has a
    # checksum for, and any mismatch is the same warning.
    product = jsonc.load(app_dir / "product.json")
    for name, expected in sorted((product.get("checksums") or {}).items()):
        path = out / name
        if not path.is_file():
            found.append(f"product.json has a checksum for {name}, which is not at {path}")
        elif checksum(path) != expected:
            found.append(
                f"product.json: the checksum of {name} does not match the file; "
                "the editor would call the installation corrupt"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--app", type=pathlib.Path, required=True, help="the application's resources/app directory (holds product.json)"
    )
    parser.add_argument(
        "--icon", type=pathlib.Path, required=True, help="the icon to draw: ide/vscode/resources/logo.svg"
    )
    args = parser.parse_args(argv)

    changed = patch(args.app, args.icon)
    for name in changed:
        print(f"{args.app / 'out' / name}: patched")
    if not changed:
        print(f"{args.app / 'out'}: already patched")
    remaining = problems(args.app)
    for problem in remaining:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
