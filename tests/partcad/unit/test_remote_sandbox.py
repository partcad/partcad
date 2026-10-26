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

import json

import pytest

from partcad import remote_sandbox, sandbox_versions


class _Recorder:
    """Runs nothing, remembers everything.

    Except the version probe, which it answers: the environment is checked for
    being the version that was asked for, so a recorder that said nothing would
    fail every creation for the wrong reason.
    """

    def __init__(self, fail_on=None, version=None, installs=(), log=False):
        self.calls = []
        self.locks = []
        self.fail_on = fail_on
        # What the image's interpreter reports, when that is not what was asked.
        self.version = version
        # The requirements pip really installs, rather than finds satisfied.
        self.installs = set(installs)
        # Whether the image's pip is configured loud enough to outweigh '--quiet',
        # so that its log comes out in front of the report.
        self.log = log

    def __call__(self, image, command, lock=None):
        self.calls.append((image, command))
        self.locks.append(lock)
        if self.fail_on and self.fail_on in " ".join(command):
            return 1, "", "it went wrong"
        if "sys.version_info" in " ".join(command):
            return 0, self.version or _asked_version(command[0]), ""
        if "pip" in command:
            return 0, self._pip(command[-1]), ""
        return 0, "", ""

    def _pip(self, requirement):
        """What 'pip install --quiet --report -' prints."""
        installed = requirement in self.installs
        report = json.dumps({"version": "1", "install": [{"metadata": {"name": requirement}}] if installed else []})
        if not self.log:
            return report
        said = "Successfully installed %s" if installed else "Requirement already satisfied: %s"
        return "Collecting %s\n%s\n%s" % (requirement, report, said % requirement)

    def commands(self):
        return [command for _image, command in self.calls]

    def builds(self):
        """The commands that built something, without the probes after them."""
        return [c for c in self.commands() if "sys.version_info" not in " ".join(c)]


def _asked_version(interpreter):
    """The version out of an environment's interpreter path."""
    return interpreter.split("-env-")[1].split("/")[0]


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
    assert remote_sandbox.environment_path("3.11") == "/pc-sandbox/v2-env-3.11"
    assert remote_sandbox.interpreter_path("3.11").endswith("/bin/python")
    assert remote_sandbox.interpreter_path("3.11").startswith(remote_sandbox.environment_path("3.11"))


def test_whatever_changes_the_environment_holds_its_lock_exclusively():
    """Other PartCAD processes share the volume, and their own gates know nothing of this one's."""
    run = _Recorder()
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", ["numpy"])

    held = dict(zip((" ".join(c) for c in run.commands()), run.locks))
    exclusive = remote_sandbox.lock_for("3.11", exclusive=True)
    assert all(held[" ".join(c)] == exclusive for c in run.builds())
    # The version probe only reads it.
    probe = next(c for c in run.commands() if "sys.version_info" in " ".join(c))
    assert held[" ".join(probe)] == remote_sandbox.lock_for("3.11", exclusive=False)


def test_each_environment_has_a_lock_of_its_own_beside_it_on_the_volume():
    one = remote_sandbox.lock_for("3.11", exclusive=True)["path"]
    assert one != remote_sandbox.lock_for("3.12", exclusive=True)["path"]
    assert one.startswith(remote_sandbox.SANDBOX_ROOT + "/")
    # Beside the environment, not in it: 'venv' creates that directory.
    assert not one.startswith(remote_sandbox.environment_path("3.11") + "/")


# --------------------------------------------------------------------------- #
# Building it                                                                  #
# --------------------------------------------------------------------------- #


def test_the_environment_is_created_and_the_interpreter_returned():
    run = _Recorder()
    interpreter = remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11")

    assert interpreter == remote_sandbox.interpreter_path("3.11")
    # By the name the image's allowlist gives its interpreter, not by the name
    # of the file: a command the service does not recognise is refused before
    # anything runs. With nothing to ask, the first of the names.
    assert run.builds() == [["python", "-m", "venv", "--upgrade-deps", remote_sandbox.environment_path("3.11")]]
    assert remote_sandbox.IMAGE_PYTHONS == ("python", "python3")


class _Which:
    """What the image says it has, and how often it was asked."""

    def __init__(self, found):
        self.found = found
        self.asked = []

    def __call__(self, image, names):
        self.asked.append((image, list(names)))
        if self.found is None:
            return None
        return {name: self.found.get(name) for name in names}


def _built_with(run):
    """The name the environment was created with."""
    return next(c for c in run.builds() if "venv" in c)[0]


def test_an_image_with_python_is_built_with_it():
    """PartCAD's base image pins "python" to its interpreter; that pin is the image's word."""
    run = _Recorder()
    which = _Which({"python": "/usr/local/bin/python3", "python3": "/usr/local/bin/python3"})
    remote_sandbox.Environments(run, which=which).ensure("ghcr.io/x/a:1", "3.11")

    assert which.asked == [("ghcr.io/x/a:1", ["python", "python3"])]
    assert _built_with(run) == "python"


def test_an_image_with_only_python3_is_built_with_python3():
    """Debian and Ubuntu install no "python": Gazebo's image, ROS's, a stock distribution's."""
    run = _Recorder()
    which = _Which({"python": None, "python3": "/usr/bin/python3"})
    remote_sandbox.Environments(run, which=which).ensure("ghcr.io/partcad/partcad-sim-gazebo:latest", "3.12")

    assert _built_with(run) == "python3"


def test_an_image_with_neither_is_refused_naming_both():
    """Rather than the service turning down "python" with nothing said about "python3"."""
    run = _Recorder()
    which = _Which({"python": None, "python3": None})
    with pytest.raises(RuntimeError, match="python and python3"):
        remote_sandbox.Environments(run, which=which).ensure("ghcr.io/x/a:1", "3.11")
    assert run.builds() == []


def test_an_image_that_could_not_be_asked_is_built_with_the_first_name():
    """No answer is not "neither": it fails, if it does, the way it did before there was a question."""
    run = _Recorder()
    remote_sandbox.Environments(run, which=_Which(None)).ensure("ghcr.io/x/a:1", "3.11")
    assert _built_with(run) == "python"


def test_an_image_that_could_not_be_asked_is_asked_again_next_time():
    """No answer is what a timeout gives too; a "python" kept for a python3-only image fails every build in it."""
    run = _Recorder(fail_on="venv")
    which = _Which(None)
    environments = remote_sandbox.Environments(run, which=which)
    with pytest.raises(RuntimeError):
        environments.ensure("ghcr.io/partcad/partcad-sim-gazebo:latest", "3.12")

    which.found = {"python": None, "python3": "/usr/bin/python3"}
    run.fail_on = None
    environments.ensure("ghcr.io/partcad/partcad-sim-gazebo:latest", "3.12")

    assert len(which.asked) == 2
    assert [c[0] for c in run.builds() if "venv" in c] == ["python", "python3"]


def test_an_image_is_asked_once_for_every_environment_in_it_and_again_once_forgotten():
    run = _Recorder()
    which = _Which({"python3": "/usr/bin/python3"})
    environments = remote_sandbox.Environments(run, which=which)

    environments.ensure("ghcr.io/x/a:1", "3.11")
    environments.ensure("ghcr.io/x/a:1", "3.12")
    assert len(which.asked) == 1

    # The container is gone, and the next one may be another image's build.
    environments.forget("ghcr.io/x/a:1")
    environments.ensure("ghcr.io/x/a:1", "3.11")
    assert len(which.asked) == 2


def test_it_is_created_once_however_many_times_it_is_asked_for():
    """A service that rebuilt it per request would work and be unusable."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    for _ in range(5):
        environments.ensure("ghcr.io/x/a:1", "3.11")

    assert len(run.builds()) == 1


def test_two_images_are_two_environments():
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11")
    environments.ensure("ghcr.io/x/b:1", "3.11")

    assert len(run.builds()) == 2
    assert {image for image, _ in run.calls} == {"ghcr.io/x/a:1", "ghcr.io/x/b:1"}


def test_a_failed_creation_is_raised_rather_than_stepped_past():
    """Otherwise the next thing anybody sees is pip failing on a missing file."""
    run = _Recorder(fail_on="venv")
    with pytest.raises(RuntimeError, match="Could not create"):
        remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11")


def test_an_image_carrying_another_version_is_a_failure():
    """The version names the directory; the image supplies the interpreter.

    An image a package named is under no obligation to carry the version the
    package also asked for, and without checking, the mismatch is silent until
    something imports a wheel built for the other one.
    """
    run = _Recorder(version="3.9")
    with pytest.raises(RuntimeError, match="3.9") as refused:
        remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11")
    # With the way out: the one place that knows what the image carries is the
    # implementation naming it, and the version asked for is usually a default.
    assert "pythonVersion" in str(refused.value)


def test_a_mismatched_version_is_not_remembered_as_built():
    run = _Recorder(version="3.9")
    environments = remote_sandbox.Environments(run)

    with pytest.raises(RuntimeError):
        environments.ensure("ghcr.io/x/a:1", "3.11")

    run.version = None
    environments.ensure("ghcr.io/x/a:1", "3.11")
    assert len([c for c in run.builds() if "venv" in c]) == 2


# --------------------------------------------------------------------------- #
# Installing into it                                                           #
# --------------------------------------------------------------------------- #


def test_requirements_are_installed_with_the_environments_own_interpreter():
    run = _Recorder()
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1"])

    install = run.builds()[-1]
    assert install[0] == remote_sandbox.interpreter_path("3.11")
    assert install[1:4] == ["-m", "pip", "install"]
    assert install[-1] == "numpy==2.4.1"


def test_a_requirement_is_installed_from_a_wheel_when_one_of_its_releases_has_one():
    """As in every other sandbox: an older release with a wheel beats a newer one to compile."""
    run = _Recorder()
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", ["mujoco>=3.2,<4"])

    install = run.builds()[-1]
    assert install.index("--prefer-binary") < install.index("mujoco>=3.2,<4")


def test_what_was_installed_is_read_from_pips_report_and_not_its_log():
    """An image may quiet pip's log (PIP_QUIET, pip.conf), and "Successfully installed" with it."""
    run = _Recorder()
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", ["numpy"])

    install = run.builds()[-1]
    assert "--quiet" in install
    assert install[install.index("--report") + 1] == "-"


def test_a_requirement_already_installed_is_not_installed_again():
    """pip is idempotent and slow; a round trip per part is what this avoids."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1"])
    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1"])
    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy==2.4.1", "trimesh"])

    installs = [c for c in run.builds() if "install" in c]
    assert [c[-1] for c in installs] == ["numpy==2.4.1", "trimesh"]


def test_the_same_requirement_in_two_environments_is_installed_in_both():
    """They are different disks; what is in one says nothing about the other."""
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", ["numpy"])
    environments.ensure("ghcr.io/x/a:1", "3.12", ["numpy"])

    installs = [c for c in run.builds() if "install" in c]
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
    assert len([c for c in run.builds() if "install" in c]) == 2


# --------------------------------------------------------------------------- #
# What one install overwrites of another                                       #
# --------------------------------------------------------------------------- #

# What every sandbox installs last of the CAD stack, after what overwrites it.
_STACK = [sandbox_versions.CADQUERY, sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP]


def _forced(run):
    """The requirements installed with '--force-reinstall', in order."""
    return [c[-1] for c in run.builds() if "--force-reinstall" in c]


def test_cadquerys_ocp_is_reinstalled_over_what_build123d_overwrote():
    """build123d's novtk OCP replaces CadQuery's; asked for again, pip would see it installed and do nothing."""
    run = _Recorder(installs=_STACK)
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", _STACK)

    assert _forced(run) == [sandbox_versions.CADQUERY_OCP]
    assert [c[-1] for c in run.builds() if "install" in c] == _STACK


def test_it_is_reinstalled_even_when_it_was_installed_before_build123d_was():
    run = _Recorder(installs=_STACK)
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", [sandbox_versions.CADQUERY_OCP])
    environments.ensure("ghcr.io/x/a:1", "3.11", [sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP])

    assert _forced(run) == [sandbox_versions.CADQUERY_OCP]


def test_an_environment_found_built_is_not_reinstalled():
    """A process finding the CAD stack already in the volume forces nothing: nothing was overwritten."""
    run = _Recorder()
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", _STACK)

    assert _forced(run) == []


def test_the_repair_is_made_where_pips_log_outweighs_quiet():
    """A configured verbosity puts pip's log in front of the report; the log then says what was installed."""
    run = _Recorder(installs=_STACK, log=True)
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", _STACK)
    assert _forced(run) == [sandbox_versions.CADQUERY_OCP]

    run = _Recorder(log=True)
    remote_sandbox.Environments(run).ensure("ghcr.io/x/a:1", "3.11", _STACK)
    assert _forced(run) == []


def test_the_repair_is_made_once():
    run = _Recorder(installs=_STACK)
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11", _STACK)
    environments.ensure("ghcr.io/x/a:1", "3.11", _STACK)

    assert _forced(run) == [sandbox_versions.CADQUERY_OCP]


def test_a_repair_that_failed_is_still_owed_after_the_container_is_forgotten():
    """What was overwritten is on the volume, which outlives the container."""
    run = _Recorder(installs=_STACK, fail_on="--force-reinstall")
    environments = remote_sandbox.Environments(run)
    with pytest.raises(RuntimeError, match="cadquery-ocp"):
        environments.ensure("ghcr.io/x/a:1", "3.11", _STACK)

    environments.forget("ghcr.io/x/a:1")
    run.fail_on = None
    # This time pip finds build123d in place: it is the earlier install's damage being repaired.
    run.installs = set()
    environments.ensure("ghcr.io/x/a:1", "3.11", _STACK)

    assert _forced(run)[-1] == sandbox_versions.CADQUERY_OCP


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
    assert len(run.builds()) == 4


def test_forgetting_one_image_leaves_another_alone():
    run = _Recorder()
    environments = remote_sandbox.Environments(run)

    environments.ensure("ghcr.io/x/a:1", "3.11")
    environments.ensure("ghcr.io/x/b:1", "3.11")
    environments.forget("ghcr.io/x/a:1")
    environments.ensure("ghcr.io/x/b:1", "3.11")

    assert len(run.builds()) == 2


# --------------------------------------------------------------------------- #
# Concurrency                                                                  #
# --------------------------------------------------------------------------- #


def test_one_environment_is_built_once_under_concurrency():
    """Two parts of one package arrive at once; only one of them may run pip."""
    import threading

    seen = []
    barrier = threading.Barrier(2)

    def run(image, command, lock=None):
        seen.append(command)
        if "sys.version_info" in " ".join(command):
            return 0, "3.11", ""
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
