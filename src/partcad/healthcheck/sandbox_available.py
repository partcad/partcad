#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Whether there is anything at all to render, export or inspect a part in.

PartCAD imports no CAD kernel. Every part is produced by a script run in a
sandbox, and there are two mechanisms that can provision one on a machine that
starts with nothing: conda, which installs an interpreter and the CAD stack
beside it, and a container, which carries both already.

`CondaAvailable` and `DockerAvailable` each report their own as missing and let
the command succeed, and that is right -- either one alone is a working
machine, so neither absence is a failure by itself. This is the check that says
what those two cannot say separately: that there is nothing left. It is the
only healthcheck that fails the command (`SEVERITY_ERROR`), because it is the
only one about something PartCAD cannot work without.

**A stated `pythonSandbox` is obeyed, and that is most of this check.** Asking
"is there conda or a container" is the right question only when nobody has
said which sandbox to use, because that is when PartCAD is the one choosing
and those two are what it chooses between. Somebody who wrote
`pythonSandbox: venv` -- a CI job that means to build a virtual environment
from the interpreter it already has, an air-gapped machine, a container image
with no conda in it -- has not misconfigured anything, and failing their
`pc healthcheck` for not having a conda they deliberately did without would
make the check something to switch off rather than something to read.

So a declared sandbox is checked against what *it* needs, and nothing else:
`conda` needs a conda, `docker` needs a container runtime, and the three that
build on the host's own interpreter (`venv`, `pypy`, `none`) need neither. Only
where nothing was declared does this fall back to "conda or a container", which
is the machine PartCAD has to choose for -- and the one the user with neither
is on.

Everything it asks, it asks the way the sandboxes themselves ask it: the conda
resolution `CondaPythonRuntime` uses, and the `docker_enabled` that
`Context.preferred_python_sandbox` uses. A machine this passes is a machine
that has the sandbox it will later choose, and not one where a different
spelling of the question happened to answer yes.
"""

from partcad import runtime as pc_runtime
from partcad.runtime_python_conda import CondaPythonRuntime
from partcad.user_config import user_config

from .tests import SEVERITY_ERROR, HealthCheckReport, HealthCheckTest

# The sandboxes that are built from the interpreter PartCAD is running under,
# and so need nothing installed on the machine to be available. 'remote' is
# here for a different reason: what it needs is a reachable
# 'partcad-service-remote-docker', which is a network address this check cannot
# ping and has no business failing a command over.
NEEDS_NOTHING_LOCAL = ("venv", "pypy", "none", "remote")


class SandboxAvailableCheck(HealthCheckTest):
    def __init__(self):
        super().__init__(
            name="SandboxAvailable",
            # No "python" tag, although a Python sandbox is what this is
            # about: 'pc healthcheck --filters=python' means the interpreter
            # PartCAD is running under, and this check has nothing to say
            # about that one.
            tags=["sandbox", "conda", "docker", "container"],
            description="check that a sandbox to render in is available",
            severity=SEVERITY_ERROR,
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        self.findings = []

        conda_path = CondaPythonRuntime.find_conda_executable()
        docker_enabled = pc_runtime.docker_enabled()

        if user_config.python_sandbox_declared:
            self._declared(user_config.python_sandbox, conda_path, docker_enabled)
        elif conda_path is None and not docker_enabled:
            self.findings.append(
                "Neither conda nor a container runtime is available here, so PartCAD has no sandbox it "
                "can provision from nothing. Install conda or mamba and put it on the PATH, or install "
                "Docker and start it. If this machine is meant to render in a virtual environment built "
                "from the Python it is running under, say so with 'pythonSandbox: venv' (or "
                "'PC_PYTHON_SANDBOX=venv') and this check will hold you to that instead."
            )

        report = HealthCheckReport(self.name, self.findings)
        if not self.findings:
            report.debug(self._passed(conda_path, docker_enabled))
        return report

    def _declared(self, sandbox: str, conda_path, docker_enabled: bool) -> None:
        """Check the sandbox that was asked for, and only that one."""
        if sandbox == "conda" and conda_path is None:
            self.findings.append(
                "'pythonSandbox' is set to 'conda' and no conda is available here. Install conda or "
                "mamba and put it on the PATH, or choose a sandbox this machine can build: 'venv' needs "
                "only the Python PartCAD is running under."
            )
        elif sandbox == "docker" and not docker_enabled:
            self.findings.append(
                "'pythonSandbox' is set to 'docker' and no container runtime is available here. Start "
                "Docker, or choose a sandbox this machine can build: 'venv' needs only the Python "
                "PartCAD is running under."
            )
        elif sandbox not in NEEDS_NOTHING_LOCAL and sandbox not in ("conda", "docker"):
            # A value no sandbox answers to. 'runtime_python_all.create' raises
            # on it at the first part rendered; said here it is one line at the
            # top of the run, next to the option it came from.
            self.findings.append(
                "'pythonSandbox' is set to '%s', which is not a sandbox PartCAD has. The values are: "
                "conda, docker, venv, pypy, remote, none." % sandbox
            )

    def _passed(self, conda_path, docker_enabled: bool) -> str:
        """What carried it, because a pass says nothing about which did."""
        if user_config.python_sandbox_declared:
            return "'pythonSandbox' is set to '%s', and this machine can build it" % user_config.python_sandbox

        found = []
        if conda_path is not None:
            found.append("conda at %s" % conda_path)
        if docker_enabled:
            found.append("a container runtime")
        return "A sandbox can be provisioned here: %s" % ", ".join(found)

    def fix(self) -> bool:
        return False
