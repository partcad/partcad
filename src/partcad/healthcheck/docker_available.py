#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Whether this machine can run anything in a container.

Reported and not failed. Docker is not a requirement: conda or a virtual
environment renders every part that does not ask for a container by name, and
on a great many machines -- every one with conda and no daemon -- nothing is
wrong at all. What a missing container runtime does cost is specific and worth
saying once, here, rather than being discovered a part at a time: an
implementation that declares `container:`, a KiCad PCB, and the `docker`
sandbox itself all need one and say so only when they are reached.

The check that does fail is `SandboxAvailable`, which asks whether *anything*
is left after this one and the conda one have both found nothing.

What this deliberately does not do is ask the question a second way. "Is there
a `docker` on the PATH", "is the socket there", "does the module import" are
all cheaper and all wrong in the same direction: a socket with nothing behind
it, a Docker Desktop running Windows containers, a `DOCKER_HOST` pointing
somewhere unreachable. `partcad.runtime.docker_enabled` is what decides whether
PartCAD will actually start a container here -- it is what
`Context.preferred_python_sandbox` asks before choosing the `docker` sandbox --
and a healthcheck answering differently from it would be reporting on a machine
other than the one the user's parts render on.
"""

from partcad import runtime as pc_runtime
from partcad.user_config import user_config

from .tests import SEVERITY_WARNING, HealthCheckReport, HealthCheckTest


class DockerAvailableCheck(HealthCheckTest):
    def __init__(self):
        super().__init__(
            name="DockerAvailable",
            tags=["docker", "container", "sandbox"],
            description="check if a container runtime is available for PartCAD to use",
            severity=SEVERITY_WARNING,
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        self.findings = []

        # Both halves of "can PartCAD use Docker here", asked the way every
        # other caller asks them. It caches, so the daemon is pinged once
        # however many of the checks here end up asking.
        enabled = pc_runtime.docker_enabled()

        # Turned off is not a finding. That is the machine's owner having said
        # so -- a machine that has a daemon and should not use it, or an image
        # built without one -- and reporting a deliberate setting back at them
        # on every run is how it becomes noise. Split out only for the message:
        # to the sandbox, "you turned it off" and "there is none" are the same
        # answer, and to a reader they are entirely different things.
        turned_off = not user_config.use_docker

        if not enabled and not turned_off:
            self.findings.append(
                "No container runtime is answering on this machine. PartCAD renders in conda or in a "
                "virtual environment without one, but an implementation that declares a container, a "
                "KiCad PCB, and the 'docker' Python sandbox each need one and will fail. Install Docker "
                "and start it, or set 'useDocker: false' to stop PartCAD looking for one. Run with '-v' "
                "for what the runtime said -- a daemon that answers but runs Windows containers counts "
                "as none here, because every image PartCAD uses is a Linux image."
            )

        report = HealthCheckReport(self.name, self.findings)
        if turned_off:
            report.debug("Containers are turned off here ('useDocker'), so none was looked for")
        elif enabled:
            report.debug("A container runtime is answering and runs Linux containers")
        return report

    def fix(self) -> bool:
        return False
