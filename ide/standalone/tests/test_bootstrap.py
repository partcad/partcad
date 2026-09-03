#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
The bootstrap extension: the welcome window, and the package the IDE starts in.

Everything here is a link between two files that nothing else keeps together --
a walkthrough addressed by a string in JavaScript, a button that runs a command
another extension contributes, a starter package whose path the installer tests
and the documentation both spell out. Each of them breaks into an IDE that
starts and looks right, with a welcome window whose buttons do nothing.
"""

import json
import re

import pytest
from conftest import COMPONENT_ROOT, REPO_ROOT

BOOTSTRAP = COMPONENT_ROOT / "bootstrap"
EXTENSION_JS = (BOOTSTRAP / "extension.js").read_text(encoding="utf-8")

# The documentation the welcome window sends people to. Every page it names is a
# page in `docs/source`, which is what this repository publishes there.
DOCUMENTATION = re.compile(r"https://partcad\.readthedocs\.io/en/latest/([a-z_]+)\.html")

# The commands a walkthrough may use without any extension contributing them:
# the editor's own. Prefixes rather than a list -- what this is really checking
# is that a `partcad.*` command in a button is one that exists.
BUILT_IN_COMMAND_PREFIXES = ("workbench.", "vscode.", "editor.")


@pytest.fixture(scope="module")
def manifest():
    return json.loads((BOOTSTRAP / "package.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def walkthrough(manifest):
    (only,) = manifest["contributes"]["walkthroughs"]
    return only


@pytest.fixture(scope="module")
def examples():
    return json.loads((BOOTSTRAP / "examples.json").read_text(encoding="utf-8"))["examples"]


def javascript_constant(name):
    """The string a `const NAME = '...'` in extension.js is set to."""
    match = re.search(rf"^const {name} = '([^']*)';$", EXTENSION_JS, re.MULTILINE)
    assert match, f"extension.js no longer declares {name}"
    return match.group(1)


def command_links(text):
    return re.findall(r"\(command:([^)]+)\)", text)


def test_the_walkthrough_is_the_one_the_extension_opens(manifest, walkthrough):
    # `workbench.action.openWalkthrough` takes the id the editor gives a
    # walkthrough, which is assembled from three fields in three places. An id
    # that is not registered opens an empty editor and reports nothing.
    identifier = f"{manifest['publisher']}.{manifest['name']}#{walkthrough['id']}"
    assert javascript_constant("WALKTHROUGH") == identifier


def test_every_step_has_the_media_it_names(walkthrough):
    for step in walkthrough["steps"]:
        (kind, value), *rest = step["media"].items()
        assert not rest, f"step {step['id']} declares more than one kind of media"
        assert kind in ("markdown", "image", "svg"), f"step {step['id']} has media the editor does not render"
        assert (BOOTSTRAP / value).is_file(), f"step {step['id']} points at {value}, which is not there"


def test_every_button_runs_a_command_that_exists(manifest, walkthrough):
    ours = {command["command"] for command in manifest["contributes"]["commands"]}
    extension = json.loads((REPO_ROOT / "ide" / "vscode" / "package.json").read_text(encoding="utf-8"))
    theirs = {command["command"] for command in extension["contributes"]["commands"]}

    for step in walkthrough["steps"]:
        for command in command_links(step["description"]):
            if command.startswith(BUILT_IN_COMMAND_PREFIXES):
                continue
            assert command in ours or command in theirs, f"step {step['id']} runs {command}, which nothing contributes"


def test_every_completion_event_names_something_that_happens(manifest, walkthrough):
    ours = {command["command"] for command in manifest["contributes"]["commands"]}
    extension = json.loads((REPO_ROOT / "ide" / "vscode" / "package.json").read_text(encoding="utf-8"))
    theirs = {command["command"] for command in extension["contributes"]["commands"]}

    for step in walkthrough["steps"]:
        for event in step.get("completionEvents", []):
            if not event.startswith("onCommand:"):
                continue
            command = event[len("onCommand:") :]
            if command.startswith(BUILT_IN_COMMAND_PREFIXES):
                continue
            # A step that waits for a command nobody can run never completes.
            assert command in ours or command in theirs, f"step {step['id']} waits for {command}, which does not exist"


def test_the_extension_registers_the_commands_it_contributes(manifest):
    contributed = {command["command"] for command in manifest["contributes"]["commands"]}
    registered = set(re.findall(r"registerCommand\('([^']+)'", EXTENSION_JS))
    # One without the other is either a palette entry that fails when it is
    # chosen, or a command that only the code knows about.
    assert contributed == registered


def test_the_settings_the_extension_reads_are_declared(manifest):
    declared = set(manifest["contributes"]["configuration"]["properties"])
    read = {f"partcadIde.{name}" for name in re.findall(r"configuration\.get\('([^']+)'", EXTENSION_JS)}
    assert read <= declared, "extension.js reads a setting that is in no settings UI and has no default"


def test_the_starter_package_is_where_everything_else_expects_it():
    # The path is spelled out in four places that cannot import each other: the
    # extension, the settings description, the documentation, and the workflow
    # that starts an installed IDE and waits for the package to appear. The
    # workflow is the one that matters -- moving the package without it silently
    # stops testing anything.
    path = re.search(r"const STARTER_PACKAGE_PATH = \[([^\]]+)\];", EXTENSION_JS)
    assert path, "extension.js no longer declares STARTER_PACKAGE_PATH"
    directory = "/".join(re.findall(r"'([^']+)'", path.group(1)))
    assert directory == ".partcad/projects/start"

    workflow = (REPO_ROOT / ".github" / "workflows" / "build-ide-standalone.yml").read_text(encoding="utf-8")
    assert directory in workflow, "the install jobs no longer check the directory the IDE creates"
    documentation = (REPO_ROOT / "docs" / "source" / "installation.rst").read_text(encoding="utf-8")
    assert directory in documentation, "the documentation no longer tells the user where the package is"


def test_the_welcome_window_offers_the_examples(walkthrough):
    # The step that hands a new user something that already works.
    steps = {step["id"]: step for step in walkthrough["steps"]}
    assert "example" in steps, "the welcome window no longer offers an example to open"
    assert "partcadIde.openExample" in command_links(steps["example"]["description"])


def test_every_step_points_at_the_documentation(walkthrough):
    # Every step is somebody's first encounter with what it describes, so each
    # one carries the page that explains it rather than leaving the reader to
    # find the documentation from the last step.
    for step in walkthrough["steps"]:
        assert "partcad.readthedocs.io" in step["description"], f"step {step['id']} links to no documentation"


def test_every_example_points_at_the_documentation(examples):
    for example in examples:
        assert "partcad.readthedocs.io" in example.get("documentation", ""), f"{example['package']} has no docs link"


def test_the_documentation_links_are_pages_that_exist(manifest, examples):
    # A link to a page that was renamed or never existed is a 404 in front of
    # somebody who has just installed the IDE. The pages are the sources of
    # https://partcad.readthedocs.io, in this repository.
    text = json.dumps(manifest) + json.dumps(examples)
    for media in sorted((BOOTSTRAP / "media").glob("*.md")):
        text += media.read_text(encoding="utf-8")

    pages = set(DOCUMENTATION.findall(text))
    assert pages, "nothing links to the documentation any more"
    for page in sorted(pages):
        assert (REPO_ROOT / "docs" / "source" / f"{page}.rst").is_file(), f"there is no {page} page to link to"


def test_the_examples_are_the_ones_the_build_ships(examples):
    # `copy_examples.py` reads the same manifest and copies what it names into
    # the extension; the extension offers what it finds there. Two readers, one
    # list, and `test_copy_examples.py` checks it against `examples/`.
    assert re.search(r"const EXAMPLES_MANIFEST = 'examples\.json';", EXTENSION_JS)
    assert javascript_constant("EXAMPLES_DIRECTORY") == "examples"
    assert examples, "the manifest offers nothing"


def test_the_icon_the_manifest_names_is_the_one_the_build_copies(manifest):
    # `package.json` names an icon that is not in `bootstrap/`: the build copies
    # it in from `ide/vscode/resources`, so that the IDE and the extension wear
    # the same one and there is nothing to keep in step. `vsce` fails outright
    # on an icon it cannot find, so what this catches is the rename that leaves
    # the manifest and `build.sh` naming two different files.
    icon = manifest["icon"]
    assert icon.endswith(".png"), "`vsce` packages a .png and refuses an .svg"
    assert not (BOOTSTRAP / icon).exists(), f"{icon} is in git after all; the build would overwrite it"

    build = (COMPONENT_ROOT / "build.sh").read_text(encoding="utf-8")
    source = REPO_ROOT / "ide" / "vscode" / "resources" / "logo_128x128.png"
    assert f'"${{staging}}/{icon}"' in build, f"build.sh no longer writes {icon} into the staging directory"
    assert 'ide/vscode/resources/logo_128x128.png"' in build, "build.sh no longer copies the project logo"
    assert source.is_file(), f"{source} is missing"
    assert source.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{source} is not a PNG; is this checkout LFS-smudged?"
