#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The host sockets the dev container is handed, and the three files that agree.

A socket reaches the container through a chain nothing type-checks:
`.devcontainer/host-sockets-init.sh` writes a link at a path on the host,
`.devcontainer/devcontainer.json` binds that exact path with `-v`, and whoever
wants to use it names the *container* side of that bind. Every hop is a string
literal in a different file and a different language.

Nothing fails loudly when two of them stop matching. `-v` with a source that
does not exist creates an empty directory instead of refusing -- which is the
property that lets a host with no Docker and no agent open this workspace at all
-- so a typo in either path produces a container that starts perfectly well with
an empty directory where the socket should be. What then fails is a git clone
over SSH, several minutes later, with a message about permissions.

That is exactly how the agent came to be missing from CI in the first place, so
these pin the joins rather than trusting the comments that describe them.
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

DEVCONTAINER_JSON = REPO_ROOT / ".devcontainer" / "devcontainer.json"
INIT_SCRIPT = REPO_ROOT / ".devcontainer" / "host-sockets-init.sh"
TEST_DEV_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test-dev.yml"

# The host directory both sides spell, the one in shell and the other in
# devcontainer.json's own variable syntax.
HOST_LINK_DIR_SHELL = "/tmp/partcad-devcontainer-${USER:-}"
HOST_LINK_DIR_JSON = "/tmp/partcad-devcontainer-${localEnv:USER}"


def _binds():
    """The `-v` arguments in devcontainer.json's runArgs, as (source, target).

    Read with a regex rather than a JSON parser on purpose: devcontainer.json is
    JSONC, every line here is a comment or a string, and this repository's
    environment has no JSON5 parser to add for the sake of one test.
    """
    text = DEVCONTAINER_JSON.read_text(encoding="utf-8")
    # Split on the colon that introduces the container path, not on the one
    # inside "${localEnv:USER}": the target is always absolute, that variable's
    # colon never precedes a "/".
    return [tuple(re.split(r":(?=/)", value, maxsplit=1)) for value in re.findall(r'"-v",\s*"([^"]+)"', text)]


def _bound_agent_target():
    """The container-side path devcontainer.json binds the agent socket to."""
    return dict(_binds())[f"{HOST_LINK_DIR_JSON}/ssh-agent.sock"]


def _behave_env():
    """The `env` block the behave job hands to `devcontainers/ci`."""
    workflow = yaml.safe_load(TEST_DEV_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["behave"]["steps"]
    behave = next(step for step in steps if step.get("name") == "Run Behave")
    return behave["with"]["env"]


def _link_names():
    """The link basenames `host-sockets-init.sh` is asked to write."""
    text = INIT_SCRIPT.read_text(encoding="utf-8")
    return set(re.findall(r"^link_first_socket\s+(\S+)", text, re.MULTILINE))


@pytest.mark.parametrize("link_name", ["docker.sock", "ssh-agent.sock"])
def test_every_link_the_host_writes_is_bound_into_the_container(link_name):
    """A link nothing binds is a link nobody ever sees."""
    assert link_name in _link_names(), f"{INIT_SCRIPT} no longer writes {link_name}"

    expected_source = f"{HOST_LINK_DIR_JSON}/{link_name}"
    sources = [source for source, _ in _binds()]
    assert expected_source in sources, (
        f"{DEVCONTAINER_JSON} does not bind {expected_source}; "
        f"it binds {sources}. A link the host writes and nothing binds is invisible "
        f"in the container, and `-v` reports no error for the other half of the mistake."
    )


def test_the_host_directory_is_spelled_the_same_in_both_languages():
    """The shell's `${USER:-}` and the JSON's `${localEnv:USER}` are one path."""
    assert HOST_LINK_DIR_SHELL in INIT_SCRIPT.read_text(encoding="utf-8")
    assert HOST_LINK_DIR_JSON in DEVCONTAINER_JSON.read_text(encoding="utf-8")


def test_the_behave_job_points_ssh_at_the_socket_that_is_actually_bound():
    """`SSH_AUTH_SOCK` in CI names the container side of the agent bind.

    `devcontainers/ci` has no `mount` input, so the bind can only come from
    devcontainer.json -- and the job has to name the same target, or ssh looks
    for an agent at a path with nothing on it and
    `features/install.feature:44 Install packages with ssh` fails alone among
    the suite's scenarios.
    """
    assert f"SSH_AUTH_SOCK={_bound_agent_target()}" in _behave_env()


def test_the_value_handed_to_ssh_is_not_quoted():
    """...and unquoted, which is not how the line above it is written.

    The action reads that block with `core.getMultilineInput` and hands each
    line to `--remote-env` as one argv element, verbatim -- `populateDefaults`
    in its `common/src/envvars.ts` passes anything containing `=` "straight
    through". No shell ever sees it, so nothing strips a quote: quoted, this
    variable's value would carry the two quote characters and name a socket
    that does not exist.

    `GIT_SSH_COMMAND` in the same block *is* quoted and works anyway, because
    git runs its value through `sh -c`. That makes the quoted form look like
    the house style, and copying it here costs a CI round to find out
    otherwise -- which is exactly what it cost once.
    """
    for line in _behave_env().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "SSH_AUTH_SOCK":
            assert '"' not in value and "'" not in value, (
                f"SSH_AUTH_SOCK is quoted ({value!r}); the quotes become part of the "
                f"path, because this value never passes through a shell"
            )
            break
    else:
        raise AssertionError("the behave job sets no SSH_AUTH_SOCK at all")
