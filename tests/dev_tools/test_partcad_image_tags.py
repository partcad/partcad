#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The tags of the PartCAD image on a release, against a registry kept in a dictionary.

`dev-tools/ci/partcad_image_tags.py` is what `publish-image` in `deploy.yml`
runs to move `<major>.<minor>` and `latest` onto the version tag it pushed, and
to check, without credentials, that they are there. It only ever runs on `main`,
after a maintainer approved a release -- which is no time to find out what it
does -- so what it does is here: a first publish, the re-run of a publish that
stopped after the version tag, the re-run of an older release, and the registry
answers that must stop it rather than be taken for "not there".
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dev-tools" / "ci" / "partcad_image_tags.py"
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
IMAGE = "ghcr.io/partcad/partcad"

_spec = importlib.util.spec_from_file_location("partcad_image_tags", SCRIPT)
tags = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tags)

# The registry the fake `docker` serves, as a module: the end-to-end test below
# writes this file out and runs it as `docker buildx ...`, so the two tests
# exercise one fake and not two that could disagree.
FAKE_DOCKER = r'''
import json, sys

PLATFORMS = ("linux/amd64", "linux/arm64")


def respond(state, argv):
    """`docker <argv>` against `state`: {"tags": {tag: digest}, "manifests": {digest: {...}}, "fail": str}."""
    image = state["image"]
    if argv[:3] == ["buildx", "imagetools", "inspect"]:
        ref, template = argv[3], argv[5]
        if state.get("fail"):
            return 1, "", "ERROR: " + state["fail"]
        tag = ref.rpartition(":")[2]
        digest = state["tags"].get(tag)
        if digest is None:
            return 1, "", "ERROR: %s: not found" % ref
        manifest = state["manifests"][digest]
        if template == "{{json .Manifest}}":
            return 0, json.dumps({
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "digest": digest,
                "manifests": [
                    {"digest": "sha256:" + p.replace("/", ""), "platform": dict(zip(("os", "architecture"), p.split("/")))}
                    for p in manifest["platforms"]
                ],
            }), ""
        if template == "{{json .Image}}":
            labels = manifest["labels"]
            return 0, json.dumps({p: {"config": {"Labels": labels}} for p in manifest["platforms"]}), ""
    if argv[:4] == ["buildx", "imagetools", "create", "--tag"]:
        ref, source = argv[4], argv[5]
        name, _, digest = source.partition("@")
        if name != image or digest not in state["manifests"]:
            return 1, "", "ERROR: %s: not found" % source
        if not state.get("create_is_a_no_op"):
            state["tags"][ref.rpartition(":")[2]] = digest
        state.setdefault("created", []).append(ref)
        return 0, "", ""
    return 2, "", "the fake docker does not do %r" % (argv,)


if __name__ == "__main__":
    with open("registry.json") as f:
        state = json.load(f)
    status, out, err = respond(state, sys.argv[1:])
    with open("registry.json", "w") as f:
        json.dump(state, f)
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(status)
'''
fake = {}
exec(compile(FAKE_DOCKER, "fake_docker", "exec"), fake)


def manifest(version, platforms=("linux/amd64", "linux/arm64")):
    return {"platforms": list(platforms), "labels": {tags.VERSION_LABEL: version} if version else {}}


def registry(versions=(), aliases=None):
    """A registry with a version tag for each of `versions`, and `aliases` as {alias: version}."""
    state = {"image": IMAGE, "tags": {}, "manifests": {}}
    for tag, version in [(v, v) for v in versions] + sorted((aliases or {}).items()):
        digest = "sha256:" + version.replace(".", "")
        state["manifests"].setdefault(digest, manifest(version))
        state["tags"][tag] = digest
    return state


def run_main(state, *argv):
    out, err = [], []
    status = tags.main(list(argv), run=lambda a: fake["respond"](state, list(a)), out=out.append, err=err.append)
    return status, out, err


def points_at(state, tag):
    return state["manifests"][state["tags"][tag]]["labels"][tags.VERSION_LABEL]


def test_a_first_publish_creates_both_aliases():
    state = registry(["0.10.35"])
    assert run_main(state, "aliases", IMAGE, "0.10.35")[0] == 0
    assert points_at(state, "0.10") == points_at(state, "latest") == "0.10.35"
    assert run_main(state, "aliases", IMAGE, "0.10.35", "--check")[0] == 0


def test_a_rerun_after_a_push_that_stopped_at_the_version_tag_moves_the_aliases():
    """The bug: the version is there, both aliases are on the previous release, and the run must not stop."""
    state = registry(["0.10.34", "0.10.35"], {"0.10": "0.10.34", "latest": "0.10.34"})
    assert run_main(state, "published", IMAGE, "0.10.35")[1] == ["true"]

    status, _, err = run_main(state, "aliases", IMAGE, "0.10.35", "--check")
    assert status == 1 and "0.10 is not 0.10.35" in err[0] and "latest is not 0.10.35" in err[0]

    assert run_main(state, "aliases", IMAGE, "0.10.35")[0] == 0
    assert points_at(state, "0.10") == points_at(state, "latest") == "0.10.35"
    # From the version tag's digest: the same manifest, not a second one.
    assert state["tags"]["0.10"] == state["tags"]["latest"] == state["tags"]["0.10.35"]
    assert run_main(state, "aliases", IMAGE, "0.10.35", "--check")[0] == 0


def test_a_rerun_with_nothing_left_to_do_writes_nothing():
    state = registry(["0.10.35"], {"0.10": "0.10.35", "latest": "0.10.35"})
    assert run_main(state, "aliases", IMAGE, "0.10.35")[0] == 0
    assert "created" not in state


def test_a_rerun_of_an_older_release_moves_nothing_backwards_and_succeeds():
    """`publish-plugin-dist`'s rule: never backwards; and, as `publish-mcp-registry` does, stop without failing."""
    state = registry(["0.10.34", "0.10.35", "0.11.0"], {"0.10": "0.10.35", "latest": "0.11.0"})
    status, out, _ = run_main(state, "aliases", IMAGE, "0.10.34")
    assert status == 0
    assert "created" not in state
    assert points_at(state, "0.10") == "0.10.35" and points_at(state, "latest") == "0.11.0"
    assert any("::notice::" in line and "0.11.0" in line for line in out)
    assert run_main(state, "aliases", IMAGE, "0.10.34", "--check")[0] == 0


def test_an_older_minor_still_gets_its_own_alias_when_latest_has_moved_on():
    """A 0.10 patch released after 0.11.0: `0.10` moves to it, `latest` stays on 0.11.0."""
    state = registry(["0.10.35", "0.10.36", "0.11.0"], {"0.10": "0.10.35", "latest": "0.11.0"})
    assert run_main(state, "aliases", IMAGE, "0.10.36")[0] == 0
    assert points_at(state, "0.10") == "0.10.36" and points_at(state, "latest") == "0.11.0"


def test_versions_compare_as_numbers_not_strings():
    """`sort -V`, as the plugin branch's check: 0.10.9 is older than 0.10.10."""
    state = registry(["0.10.9", "0.10.10"], {"0.10": "0.10.9", "latest": "0.10.9"})
    assert run_main(state, "aliases", IMAGE, "0.10.10")[0] == 0
    assert points_at(state, "latest") == "0.10.10"
    assert run_main(state, "aliases", IMAGE, "0.10.9")[0] == 0
    assert points_at(state, "latest") == "0.10.10"


def test_an_alias_that_does_not_say_its_release_is_an_error_not_a_guess():
    state = registry(["0.10.35"])
    state["manifests"]["sha256:unlabelled"] = manifest(None)
    state["tags"]["latest"] = "sha256:unlabelled"
    status, _, err = run_main(state, "aliases", IMAGE, "0.10.35")
    assert status == 1 and "does not say which release" in err[0]
    assert state["tags"]["latest"] == "sha256:unlabelled"


@pytest.mark.parametrize("failure", ["unexpected status from HEAD request: 503", "denied: denied", "i/o timeout"])
def test_only_not_found_means_absent(failure):
    """A refused or timed-out inspection is not an absent tag: taken for one, it rebuilds or moves `latest` back."""
    state = registry(["0.10.35"], {"latest": "0.11.0"})
    state["fail"] = failure
    for argv in (("published", IMAGE, "0.10.35"), ("aliases", IMAGE, "0.10.35")):
        status, out, err = run_main(state, *argv)
        assert status == 1 and out == [] and failure in err[0]
    assert "created" not in state


def test_published_says_false_only_for_not_found():
    assert run_main(registry(), "published", IMAGE, "0.10.35") == (0, ["false"], [])


def test_aliases_need_the_version_tag_first():
    status, _, err = run_main(registry([], {"latest": "0.10.34"}), "aliases", IMAGE, "0.10.35")
    assert status == 1 and "0.10.35 is not published" in err[0]


def test_a_create_that_said_it_worked_and_did_not_is_a_failure():
    state = registry(["0.10.35"], {"latest": "0.10.34"})
    state["create_is_a_no_op"] = True
    status, _, err = run_main(state, "aliases", IMAGE, "0.10.35")
    assert status == 1 and "did not move" in err[0]


def test_the_check_wants_both_architectures():
    state = registry(["0.10.35"], {"0.10": "0.10.35", "latest": "0.10.35"})
    state["manifests"]["sha256:01035"]["platforms"] = ["linux/amd64"]
    status, _, err = run_main(state, "aliases", IMAGE, "0.10.35", "--check")
    assert status == 1 and "no linux/arm64 image" in err[0]


def test_the_check_names_the_settings_page_when_it_cannot_read_the_tag():
    """A package GHCR has never seen is created private, and that is found here."""
    state = registry(["0.10.35"])
    state["fail"] = "unauthorized: authentication required"
    status, _, err = run_main(state, "aliases", IMAGE, "0.10.35", "--check")
    assert status == 1 and "https://github.com/orgs/partcad/packages/container/partcad/settings" in err[0]


def test_it_runs_as_the_workflow_runs_it(tmp_path):
    """The script as a process, its `docker` the fake above -- run as `python buildx ...` from its directory."""
    (tmp_path / "buildx").write_text(
        # `python buildx imagetools ...`: argv[0] is the file, so put "buildx" back.
        FAKE_DOCKER.replace("sys.argv[1:]", '["buildx"] + sys.argv[1:]'),
        encoding="utf-8",
    )
    state = registry(["0.10.34", "0.10.35"], {"0.10": "0.10.34", "latest": "0.10.34"})
    (tmp_path / "registry.json").write_text(json.dumps(state), encoding="utf-8")
    env = {**os.environ, "PC_DOCKER": sys.executable}

    def script(*argv):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
        )

    assert script("published", IMAGE, "0.10.35").stdout.strip() == "true"
    done = script("aliases", IMAGE, "0.10.35")
    assert done.returncode == 0, done.stderr
    assert script("aliases", IMAGE, "0.10.35", "--check").returncode == 0
    after = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert after["tags"]["latest"] == after["tags"]["0.10"] == after["tags"]["0.10.35"]


def test_the_workflow_builds_the_version_tag_alone_and_moves_the_aliases_on_every_run():
    """The order that fixes the re-run: the aliases are not behind the "already published" skip."""
    steps = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))["jobs"]["publish-image"]["steps"]
    by_name = {step.get("name"): step for step in steps}
    names = [step.get("name") for step in steps]

    build = by_name['Build the image, and on "main" publish it']
    assert 'PC_IMAGE_REFS="${IMAGE}:${VERSION}"' in build["run"]
    assert "latest" not in build["run"]

    move = by_name['Point "<major>.<minor>" and "latest" at it']
    assert "partcad_image_tags.py aliases" in move["run"] and "--check" not in move["run"]
    assert "already" not in move.get("if", "")

    login = by_name["Login to GitHub Container Registry"]
    assert "already" not in login.get("if", "")
    assert names.index("Login to GitHub Container Registry") < names.index("Is this version published already")

    pull = by_name["Check that anybody can pull it"]
    assert "partcad_image_tags.py aliases" in pull["run"] and "--check" in pull["run"]
    assert "docker logout" in pull["run"]
    assert names.index(build["name"]) < names.index(move["name"]) < names.index(pull["name"])

    assert "partcad_image_tags.py published" in by_name["Is this version published already"]["run"]
