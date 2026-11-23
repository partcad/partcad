#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD image, `ghcr.io/partcad/partcad`, against what it has to agree with.

The image is a Dockerfile and two scripts, and almost everything they say is
also said somewhere in Python: the variables `partcad_utils.app_image` reads to
know it runs in the image, the directory the volume is mounted at, the label
`pc system prune` leaves alone, the conda the bundles carry. Where the two
disagree nothing fails in a build -- the image builds, and then `pc upgrade`
pip-installs into a container, or the sandboxes go into a directory nobody
mounts. So each of those is checked here, where a disagreement is a red test.

What the image *does* is `dev-tools/ci/test-partcad-image.sh`, which runs it;
the "Container (PartCAD)" job in `test.yml` runs that.
"""

import pathlib
import re

import yaml

from partcad import docker_prune, sandbox_versions
from partcad_utils import app_image
from partcad_utils import conda as pc_conda

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
IMAGE_DIR = REPO_ROOT / "tools" / "containers" / "partcad"
DOCKERFILE = (IMAGE_DIR / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (IMAGE_DIR / "entrypoint.sh").read_text(encoding="utf-8")
BUILD_SCRIPT = "dev-tools/ci/build-partcad-image.sh"
TEST_SCRIPT = "dev-tools/ci/test-partcad-image.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _env():
    """Every `NAME=value` the Dockerfile's ENV instructions set, continuation lines included."""
    found = {}
    for block in re.findall(r"^ENV (.*?)(?<!\\)$", DOCKERFILE, re.M | re.S):
        for name, value in re.findall(r"([A-Z_]+)=(\S+)", block):
            found[name] = value
    return found


def _arg(name):
    match = re.search(r"^ARG %s=(\S+)$" % name, DOCKERFILE, re.M)
    assert match, "the Dockerfile has no default for ARG %s" % name
    return match.group(1)


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_it_says_it_is_the_image_the_way_partcad_asks():
    env = _env()
    assert env[app_image.MANAGED_BY_ENV] == app_image.MANAGED_BY_IMAGE
    assert env[app_image.IMAGE_ENV] == "${PARTCAD_IMAGE}"
    assert _arg("PARTCAD_IMAGE") == app_image.DEFAULT_IMAGE


def test_its_state_is_where_the_volume_is_mounted():
    """One directory to keep: the sandboxes, and conda's cache beside them, as the bundles keep it."""
    env = _env()
    assert env["HOME"] == str(pathlib.PurePosixPath(app_image.STATE_DIR).parent)
    assert env["PC_INTERNAL_STATE_DIR"] == app_image.STATE_DIR
    assert env["MAMBA_ROOT_PREFIX"] == "%s/%s" % (app_image.STATE_DIR, pc_conda.ROOT_PREFIX_SUBDIR)


def test_with_the_hosts_docker_it_sends_files_rather_than_binding_them():
    """Its PartCAD is in its image layer, which no daemon outside the container can bind into a sandbox."""
    assert _env()["PC_USE_DOCKER_REMOTE"] == "true"


def test_it_carries_the_conda_the_bundles_carry_and_partcad_finds_it():
    build_sh = (REPO_ROOT / "dev-tools" / "pyinstaller" / "build.sh").read_text(encoding="utf-8")
    (bundled,) = re.findall(r'^MICROMAMBA_VERSION="([^"]+)"$', build_sh, re.M)
    assert _arg("MICROMAMBA_VERSION") == bundled
    assert "/usr/local/bin/micromamba" in DOCKERFILE
    assert "micromamba" in pc_conda.PATH_NAMES


def test_prune_leaves_it_alone():
    assert 'LABEL %s="1"' % docker_prune.LABEL_APP in DOCKERFILE


def test_it_is_built_on_the_base_the_gstreamer_flavour_exists_for():
    """The GStreamer flavour is built for the default Python alone, and by default this release's."""
    assert _arg("BASE_TAG") == "${PARTCAD_VERSION}-py%s-gstreamer" % sandbox_versions.DEFAULT_PYTHON_VERSION
    build = (REPO_ROOT / BUILD_SCRIPT).read_text(encoding="utf-8")
    assert "-py%s-gstreamer" % sandbox_versions.DEFAULT_PYTHON_VERSION in build


def test_built_from_its_directory_alone_it_is_this_release():
    """What Docker's MCP Catalog does: `docker build tools/containers/partcad`, at a release's commit.

    So the default version is the release, moved by bump-my-version like every other statement of it;
    with no `wheels` context the empty stage of that name stands in and PyPI supplies that version; and
    nothing is copied from outside the directory.
    """
    bumpversion = (REPO_ROOT / "dev-tools" / "bumpversion.toml").read_text(encoding="utf-8")
    (release,) = re.findall(r'^current_version = "([^"]+)"$', bumpversion, re.M)
    assert _arg("PARTCAD_VERSION") == release
    assert 'filename = "tools/containers/partcad/Dockerfile"' in bumpversion
    assert re.search(r"^FROM scratch AS wheels$", DOCKERFILE, re.M)
    assert "partcad[lint]==${PARTCAD_VERSION}" in DOCKERFILE
    for source in re.findall(r"^COPY (?:--\S+ )*(\S+)", DOCKERFILE, re.M):
        assert (IMAGE_DIR / source).is_file(), source


def test_the_entrypoint_drops_privileges_for_every_partcad_executable():
    """A PartCAD process never runs as root unless asked: it writes into the user's workspace."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = re.search(r"^\[project\.scripts\]\n(.*?)^\[", pyproject, re.M | re.S).group(1)
    executables = set(re.findall(r"^([a-z-]+) = ", scripts, re.M))
    (line,) = [line for line in ENTRYPOINT.splitlines() if line.startswith("pc | ")]
    assert set(re.findall(r"[a-z-]+", line.rstrip(")"))) == executables


def test_tini_is_pid_1():
    """`pc` starts a daemon beside itself, which PID 1 has to reap, and `docker stop` has to stop."""
    assert 'ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/partcad-entrypoint"]' in DOCKERFILE


def test_one_script_builds_it_and_one_tests_it():
    """What "test.yml" tested is what "deploy.yml" published: the same script, from both."""
    test_job = _workflow("test.yml")["jobs"]["container-partcad"]
    runs = "\n".join(step.get("run", "") for step in test_job["steps"])
    assert BUILD_SCRIPT in runs and TEST_SCRIPT in runs

    publish = _workflow("deploy.yml")["jobs"]["publish-image"]
    runs = "\n".join(step.get("run", "") for step in publish["steps"])
    assert BUILD_SCRIPT in runs
    for name in sorted(WORKFLOWS.glob("*.yml")):
        assert "tools/containers/partcad/Dockerfile" not in name.read_text(encoding="utf-8"), name.name


def test_it_is_published_after_pypi_and_before_the_mcp_registry():
    """After the approved upload; and before the registry entry that names its tag and reads its label."""
    jobs = _workflow("deploy.yml")["jobs"]
    assert "publish-to-pypi" in jobs["publish-image"]["needs"]
    assert "publish-image" in jobs["publish-mcp-registry"]["needs"]


def test_the_test_job_waits_for_the_base_it_is_built_on_and_cleanup_waits_for_it():
    jobs = _workflow("test.yml")["jobs"]
    assert "build-containers" in jobs["container-partcad"]["needs"]
    assert jobs["container-partcad"]["env"]["PC_CONTAINER_IMAGE_TAG"] == (
        "${{ needs.set-matrix.outputs.image-override }}"
    )
    assert "container-partcad" in jobs["cleanup-images"]["needs"]


CATALOG = IMAGE_DIR / "docker-mcp-catalog" / "server.yaml"


def test_the_docker_catalog_entry_builds_this_directory_into_dockers_namespace():
    """`mcp/partcad`, Docker's to publish -- never PartCAD's own `partcad` namespace on Docker Hub."""
    entry = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    assert entry["image"] == "mcp/partcad"
    assert entry["name"] == "partcad"
    assert entry["source"]["project"] == "https://github.com/partcad/partcad"
    assert entry["source"]["directory"] == IMAGE_DIR.relative_to(REPO_ROOT).as_posix()
    assert "dockerfile" not in entry["source"], "Docker's build takes 'Dockerfile' in the directory"


def test_the_docker_catalog_entry_runs_pc_mcp_on_the_mounted_workspace_with_the_state_volume():
    entry = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    command = entry["run"]["command"]
    assert command[-1] == "mcp" and command[0] == "-p"
    volumes = entry["run"]["volumes"]
    assert any(volume.endswith(":%s" % command[1]) for volume in volumes)
    assert "%s:%s" % (app_image.STATE_VOLUME, app_image.STATE_DIR) in volumes
    # The image has the directory, so the server starts -- and lists its tools -- with nothing mounted.
    assert re.search(r"^RUN mkdir -p .*\s%s\s" % re.escape(command[1]), DOCKERFILE, re.M)
    assert entry["config"]["parameters"]["required"] == ["workspace"]


def test_the_docker_catalog_entry_does_not_hand_over_the_hosts_docker():
    assert "docker.sock" not in CATALOG.read_text(encoding="utf-8").split("\nname:")[1]
    assert not yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["run"].get("disableNetwork")


def test_the_docker_catalog_mounts_the_workspace_as_picked_and_writable_only_once_allowed():
    """Docker's MCP gateway checks the host side of a bind itself (`pkg/gateway/docker_binds.go` there).

    It refuses a folder outside its temporary directories unless it is allowed, mounts it read-only unless
    MCP_GATEWAY_DOCKER_BIND_ALLOW_WRITABLE_PATHS names it, and refuses an explicit `:rw` it does not name. So
    no mode, which is writable exactly when the person allowed it; and the source as the person picked it, since
    `volume-target` and `volume` turn `C:\\work` into `/C/work`, a path inside a container and no folder on Windows.
    The person is told what to allow where they pick the folder.
    """
    entry = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    (workspace,) = [volume for volume in entry["run"]["volumes"] if "partcad.workspace" in volume]
    template, separator, target = workspace.partition("}}:")
    assert separator and "|" not in template, workspace
    assert target == entry["run"]["command"][1], "the package `-p` names, and no mode after it"
    assert "MCP_GATEWAY_DOCKER_BIND_ALLOW_WRITABLE_PATHS" in entry["config"]["description"]
