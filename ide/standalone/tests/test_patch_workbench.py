#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json
import shutil
import subprocess

import patch_workbench
import pytest

from conftest import REPO_ROOT, WORKBENCH_CSS, WORKBENCH_JS, write_workbench

LOGO = REPO_ROOT / "ide" / "vscode" / "resources" / "logo.svg"
PARTCAD = patch_workbench.CONTAINER_ID

# The editor's own containers, with the orders it gives them, and an
# extension's, numbered from 7 as the editor numbers them.
BUILT_IN = [
    ("workbench.view.explorer", 0),
    ("workbench.view.search", 1),
    ("workbench.view.scm", 2),
    ("workbench.view.debug", 3),
    ("workbench.view.extensions", 4),
]
OTHER_EXTENSION = "workbench.view.extension.python"


def patched_app(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    write_workbench(app)
    patch_workbench.patch(app, LOGO)
    return app


def workbench_js(app):
    return (app / "out" / patch_workbench.WORKBENCH_JS).read_text(encoding="utf-8")


def workbench_css(app):
    return (app / "out" / patch_workbench.WORKBENCH_CSS).read_text(encoding="utf-8")


def test_a_patched_workbench_has_no_problems(tmp_path):
    app = patched_app(tmp_path)
    assert patch_workbench.problems(app) == []


def test_an_unpatched_workbench_has_one_problem_per_part(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    write_workbench(app)

    found = patch_workbench.problems(app)
    assert len(found) == 3
    assert any("not ordered first" in problem for problem in found)
    assert any("not moved to the top" in problem for problem in found)
    assert any("not drawn in colour" in problem for problem in found)


def test_the_checksums_follow_the_files(tmp_path):
    app = patched_app(tmp_path)
    checksums = json.loads((app / "product.json").read_text(encoding="utf-8"))["checksums"]

    for name in (patch_workbench.WORKBENCH_JS, patch_workbench.WORKBENCH_CSS):
        assert checksums[name] == patch_workbench.checksum(app / "out" / name)


def test_a_file_that_disagrees_with_its_checksum_is_a_problem(tmp_path):
    app = patched_app(tmp_path)
    (app / "out" / patch_workbench.WORKBENCH_CSS).write_text("/* changed afterwards */", encoding="utf-8")

    assert any("would call the installation corrupt" in problem for problem in patch_workbench.problems(app))


def test_the_checksum_is_the_one_the_editor_computes(tmp_path):
    # SHA-256 in base64, with the trailing "=" removed: what VSCodium's own
    # product.json holds, and what `openssl dgst -sha256 -binary | base64`
    # prints for the same bytes, padding aside.
    path = tmp_path / "file"
    path.write_bytes(b"PartCAD")
    assert patch_workbench.checksum(path) == "iBSVdZqnr/Ia5qKOc3+Vb4Hf2UUsqPt5q07M1p34QXc"


def test_a_product_json_without_checksums_is_left_without_them(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    write_workbench(app)
    (app / "product.json").write_text(json.dumps({"nameLong": "PartCAD IDE"}), encoding="utf-8")

    patch_workbench.patch(app, LOGO)
    assert json.loads((app / "product.json").read_text(encoding="utf-8")) == {"nameLong": "PartCAD IDE"}
    assert patch_workbench.problems(app) == []


def test_patching_twice_changes_nothing(tmp_path):
    app = patched_app(tmp_path)
    before = {path: path.read_bytes() for path in (app / "out").rglob("*") if path.is_file()}
    before[app / "product.json"] = (app / "product.json").read_bytes()

    assert patch_workbench.patch(app, LOGO) == []
    for path, content in before.items():
        assert path.read_bytes() == content, path


def test_the_icon_rule_is_appended_after_what_was_there(tmp_path):
    css = workbench_css(patched_app(tmp_path))

    assert css.startswith(WORKBENCH_CSS)
    assert '[class*="activity-workbench-view-extension-partcad-container-"]' in css
    assert "mask: none !important" in css
    assert 'url("data:image/svg+xml;base64,' in css


@pytest.mark.parametrize("which", ["order", "move"])
def test_code_that_is_not_there_stops_the_build(tmp_path, which):
    app = tmp_path / "app"
    app.mkdir()
    if which == "order":
        js = WORKBENCH_JS.replace("hideIfEmpty:!0,order:i,", "hideIfEmpty:!0,priority:i,")
        expected = "order"
    else:
        js = WORKBENCH_JS.replace("r=n.order!==t,n.order=t", "r=n.rank!==t,n.rank=t")
        expected = "remembered place"
    write_workbench(app, js=js)

    with pytest.raises(SystemExit, match=f"{expected}: no match .* changed upstream"):
        patch_workbench.patch(app, LOGO)


def test_code_that_is_there_twice_stops_the_build(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    write_workbench(app, js=WORKBENCH_JS + WORKBENCH_JS)

    with pytest.raises(SystemExit, match="2 matches"):
        patch_workbench.patch(app, LOGO)


def test_the_editors_own_registrations_are_not_touched(tmp_path):
    js = workbench_js(patched_app(tmp_path))
    assert '"workbench.panel.testResults",{mergeViewWithContainerWhenSingleView:!0}]),hideIfEmpty:!0,order:3}' in js


# ---------------------------------------------------------------------------
# What the patched code does, run under Node rather than read: a substitution
# that reads right but throws, or inserts PartCAD one place too far down, is an
# IDE that starts fine and is wrong.
# ---------------------------------------------------------------------------

DRIVER = """
const PARTCAD = %(partcad)s, BUILT_IN = %(built_in)s, OTHER = %(other)s;
const handler = new Handler();
const registeredOrder = id => handler.registerCustomViewContainer(id, id, undefined, 7, "x", 0).order;

// What the composite bar does on every start: each registered container is
// added, the editor's own first and the extensions' as they register.
function start(remembered) {
    const bar = new Model(remembered.map(([id, order]) => ({ id, order, visible: true, pinned: true })));
    for (const [id, order] of BUILT_IN) bar.add(id, id, order, undefined);
    bar.add(OTHER, OTHER, 7, undefined);
    bar.add(PARTCAD, PARTCAD, registeredOrder(PARTCAD), undefined);
    return bar.items.map(item => [item.id, item.order]);
}

const fresh = start([]);
const older = start([...BUILT_IN, [PARTCAD, 8], [OTHER, 7]]);
const again = start(older);
const dragged = start([...BUILT_IN.slice(0, 2), [PARTCAD, -1], ...BUILT_IN.slice(2), [OTHER, 7]]);
const partcad = registeredOrder(PARTCAD), other = registeredOrder(OTHER);
console.log(JSON.stringify({ partcad, other, fresh, older, again, dragged }));
"""


@pytest.fixture
def behaviour(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "behaviour.js"
    script.write_text(
        workbench_js(patched_app(tmp_path))
        + DRIVER
        % {
            "partcad": json.dumps(PARTCAD),
            "built_in": json.dumps(BUILT_IN),
            "other": json.dumps(OTHER_EXTENSION),
        },
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def ids(items):
    return [identifier for identifier, _ in items]


def test_partcad_is_registered_ahead_of_explorer_and_nothing_else_is(behaviour):
    assert behaviour["partcad"] == -1
    assert behaviour["other"] == 7


def test_a_new_profile_has_partcad_at_the_top(behaviour):
    assert ids(behaviour["fresh"])[:2] == [PARTCAD, "workbench.view.explorer"]


def test_a_profile_from_an_earlier_ide_has_partcad_moved_to_the_top(behaviour):
    assert ids(behaviour["older"])[:2] == [PARTCAD, "workbench.view.explorer"]
    # Remembered with its new order, which is what makes the move happen once.
    assert dict(behaviour["older"])[PARTCAD] == -1


def test_the_move_happens_once(behaviour):
    assert behaviour["again"] == behaviour["older"]


def test_where_the_user_put_partcad_is_where_it_stays(behaviour):
    assert ids(behaviour["dragged"]).index(PARTCAD) == 2
