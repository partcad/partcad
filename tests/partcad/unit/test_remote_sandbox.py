#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The environment a `remote` sandbox runs in, kept on the container's side.

What is worth pinning is the sequence: which commands run over there, in what
order, and how often. `Environments` is handed a way to run one rather than
performing it, so all of that is decidable without Docker -- and the "how often"
half matters most, because a service that rebuilt the environment or re-ran pip
on every request would work perfectly and be unusable.
"""

import pytest

from partcad import remote_sandbox


class _Recorder:
    """Runs nothing, remembers everything."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, image, command):
        self.calls.append((image, command))
        if self.fail_on and self.fail_on in " ".join(command):
            return 1, "", "it went wrong"
        return 0, "", ""

    def commands(self):
        return [command for _image, command in self.calls]


# --------------------------------------------------------------------------- #
# Where things live                                                            #
# --------------------------------------------------------------------------- #


def test_each_image_gets_a_volume_of_its_own():
    """What pip resolves depends on the native libraries under it."""
    one = remote_sandbox.volume_name("ghcr.io/x/a:1")
    two = remote_sandbox.volume_name("ghcr.io/x/b:1")
    assert one != two
    assert one == remote_sandbox.volume_name("ghcr.io/x/a:1")
    assert one.startswith("pc-sandbox-")


def test_each_python_version_gets_an_environment_of_its_own():
    assert remote_sandbox.environment_path("3.11") != remote_sandbox.environment_path("3.12")
    assert remote_sandbox.interpreter_path("3.11").endswith("/bin/python")
    assert remote_sandbox.interpreter_path("3.11").startswith(remote_sandbox.environment_path("3.11"))


# --------------------------------------------------------------------------- #
# Building it                                                                  #
# --------------------------------------------------------------------------- #


def test_the_environment_is_created_and_the_interpreter_returned():
    run = _Recorder()
    interpreter = remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11")

    assert interpreter == remote_sandbox.interpreter_path("3.11")
    assert run.commands() == [["python3", "-m", "venv", "--upgrade-deps", remote_sandbox.environment_path("3.11")]]


def test_it_is_created_once_however_many_times_it_is_asked_for():
    """A service that rebuilt it per request would work and be unusable."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    for _ in range(5):
        environments.ensure("ghcr.io/x/a:1", "3.11")

    assert len(run.commands()) == 1


def test_two_images_are_two_environments():
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11")
    environments.ensure("ghcr.io/x/b:1", "3.11")

    assert len(run.commands()) == 2
    assert {image for image, _ in run.calls} == {"ghcr.io/x/a:1", "ghcr.io/x/b:1"}


def test_a_failed_creation_is_raised_rather_than_stepped_past():
    """Otherwise the next thing anybody sees is pip failing on a missing file."""
    run = _Recorder(fail_on="venv")
    with pytest.raises(RuntimeError, match="Could not create"):
        remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11")


# --------------------------------------------------------------------------- #
# Installing into it                                                           #
# --------------------------------------------------------------------------- #


def test_requirements_are_installed_with_the_environments_own_interpreter():
    run = _Recorder()
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1"])

    install = run.commands()[-1]
    assert install[0] == remote_sandbox.interpreter_path("3.11")
    assert install[1:4] == ["-m", "pip", "install"]
    assert install[-1] == "numpy==2.4.1"


def test_a_requirement_already_installed_is_not_installed_again():
    """pip is idempotent and slow; a round trip per part is what this avoids."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1"])
    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1"])
    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1", "trimesh"])

    installs = [c for c in run.commands() if "install" in c]
    assert [c[-1] for c in installs] == ["numpy==2.4.1", "trimesh"]


def test_the_same_requirement_in_two_environments_is_installed_in_both():
    """They are different disks; what is in one says nothing about the other."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])
    environments.ensure("ghcr.io/x/a:1", "3.12", ["numpy"])

    installs = [c for c in run.commands() if "install" in c]
    assert len(installs) == 2


def test_a_failed_install_names_the_requirement_and_the_image():
    run = _Recorder(fail_on="pip")
    with pytest.raises(RuntimeError, match="numpy"):
        remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", ["numpy"])


def test_a_failed_install_is_not_remembered_as_installed():
    """Or a retry after fixing the registry would skip the install that failed."""
    run = _Recorder(fail_on="pip")
    environments = remote_sandbox.Environments(run)

    with pytest.raises(RuntimeError):
        environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])

    run.fail_on = None
    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])
    assert len([c for c in run.commands() if "install" in c]) == 2


# --------------------------------------------------------------------------- #
# Forgetting                                                                   #
# --------------------------------------------------------------------------- #


def test_forgetting_an_image_makes_the_next_request_check_again():
    """The volume outlives the container; this service's belief about it need not."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])
    environments.forget("ghcr.io/x/a:1")
    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])

    # Both the creation and the install are done again -- 'venv' on a directory
    # that already holds one is cheap, and pip on an installed package is a
    # no-op, so re-checking costs little and assuming costs correctness.
    assert len(run.commands()) == 4


def test_forgetting_one_image_leaves_another_alone():
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11")
    environments.ensure("ghcr.io/x/b:1", "3.11")
    environments.forget("ghcr.io/x/a:1")
    environments.ensure("ghcr.io/x/b:1", "3.11")

    assert len(run.commands()) == 2


# --------------------------------------------------------------------------- #
# Concurrency                                                                  #
# --------------------------------------------------------------------------- #


def test_one_environment_is_built_once_under_concurrency():
    """Two parts of one package arrive at once; only one of them may run pip."""
    import threading

    seen = []
    barrier = threading.Barrier(2)

    def run(image, command):
        seen.append(command)
        if "venv" in command:
            # Hold the first caller inside the build so the second must wait.
            barrier.wait(timeout=5)
        return 0, "", ""

    environments = remote_sandbox.Environments(run)
    errors = []

    def ask():
        try:
            environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])
        except Exception as e:  # pragma: no cover - only on a real failure
            errors.append(e)

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len([c for c in seen if "venv" in c]) == 1
    assert len([c for c in seen if "install" in c]) == 1
