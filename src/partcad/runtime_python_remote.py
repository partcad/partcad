#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A sandbox on a machine that is not this one.

The ``docker`` sandbox mounts the caller's files into a container, which needs
the caller and the container to be the same machine. This one assumes nothing of
the sort: it sends the directories a command reads, sends the command, and
receives what it wrote. What it talks to is ``partcad-service-remote-docker``,
which owns the environment and prepends its interpreter -- so this class holds
no environment, creates nothing, and installs nothing. It says what is wanted.

That division is the reason the class is short. Provisioning guards belong on
the disk holding the thing they describe, and that disk is over there; a client
tracking what is installed would be guessing about a machine it cannot see, and
would guess wrong the first time somebody removed the volume.

What is *not* free is knowing which directories to send. A caller that runs a
script knows the script's path and nothing about what the script imports beside
it, and most callers here -- the part factories -- do not think about containers
at all. So the directories are **inferred from the command**: any argument that
names a file on this machine contributes the directory it is in. That is enough
because of how the far end works -- the service inside the container extracts
each directory and rewrites the arguments that point into it, matching by prefix
-- and it means every existing caller works unchanged.

Inference cannot answer the other half. What a command *writes* is not in the
command, so a caller that produces a file has to name it; ``Shape`` does, the
same way it does for a container. A caller that only reads standard output needs
nothing.
"""

import os
from typing import Optional

from . import runtime, runtime_python, telemetry
from .runtime_json_rpc import RuntimeJsonRpcClient

# Never sent, whatever an argument points into. A sandbox needs none of them,
# `.git` alone can be most of what a package weighs, and `pack_directory` skips
# them too -- this is the coarser cut that keeps a directory from being packed
# at all.
NEVER_SEND = {"/", "/usr", "/bin", "/etc", "/var", "/tmp", "/home", os.path.expanduser("~")}


def _is_root(path: str) -> bool:
    """Whether a path is a filesystem root, on whichever platform this is.

    `NEVER_SEND` above is spelled in POSIX, and that is not enough: on Windows
    `os.path.abspath("/")` comes back as the *current drive's* root -- `D:\\` on
    a GitHub runner -- which the set does not name and `rstrip(os.sep)` does not
    reduce to anything in it. So the whole drive was eligible to be packed and
    sent, which is the exact failure the set exists to prevent, and the worst
    case of it.

    Asked structurally rather than by name, because the names differ per
    platform and per drive: a root is the only path that is its own parent.
    That covers `/`, `C:\\`, and a UNC share root alike.
    """
    return os.path.dirname(path) == path


def _short(image: str) -> str:
    import hashlib

    return hashlib.sha256(image.encode()).hexdigest()[:12]


def input_dirs_for(command, cwd: Optional[str] = None) -> list:
    """The directories this command needs, worked out from the command itself.

    Every argument naming a file on this machine contributes the directory it
    is in -- because a script needs the siblings it imports, which is exactly
    what `runtime.pack_directory` exists for and what naming the one file would
    miss.

    Nested directories are dropped in favour of the one containing them, so a
    package sent whole is not also sent piecemeal, and the far end's
    longest-prefix substitution has one answer rather than two.
    """
    found = set()
    for argument in list(command) + ([cwd] if cwd else []):
        if not isinstance(argument, str) or not argument:
            continue
        path = os.path.abspath(argument)
        if os.path.isdir(path):
            candidate = path
        elif os.path.isfile(path):
            candidate = os.path.dirname(path)
        else:
            continue
        if _is_root(candidate) or candidate.rstrip(os.sep) in {p.rstrip(os.sep) for p in NEVER_SEND}:
            # A file sitting directly in one of these is a system file, and the
            # directory around it is not a package to send.
            continue
        found.add(candidate)

    kept = []
    for path in sorted(found, key=len):
        if not any(path == outer or path.startswith(outer.rstrip(os.sep) + os.sep) for outer in kept):
            kept.append(path)
    return kept


@telemetry.instrument()
def _loopback(host: str) -> bool:
    """Whether an address reaches this machine and nothing else.

    The whole of 127.0.0.0/8, "::1" with or without the brackets a URL puts
    around it, and the name a person actually types. Anything this cannot read
    as loopback is treated as reachable, which is the safe way round: the
    question it answers is whether a request may go out unencrypted.
    """
    import ipaddress

    if not host:
        return False
    candidate = host.strip("[]")
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return candidate.lower() in ("localhost", "localhost.localdomain")


class RemotePythonRuntime(runtime_python.PythonRuntime):
    # What tells a caller that this sandbox wants to be told what a command
    # writes. Read rather than isinstance-checked, so that a caller says "if it
    # exchanges files" instead of naming this class.
    EXCHANGES_FILES = True

    def __init__(self, ctx, version=None, image=None, endpoint=None):
        if image is None:
            from . import runtime_python_docker

            image = runtime_python_docker.image_for(version or runtime_python.sandbox_versions.DEFAULT_PYTHON_VERSION)
        super().__init__(ctx, "remote-" + _short(image), version)

        self.image = image
        self.endpoint = endpoint or getattr(ctx.user_config, "remote_sandbox", None)
        if not self.endpoint:
            raise runtime.SandboxUnavailable(
                "The 'remote' sandbox needs a service to run its containers, and none is configured. "
                "Start 'partcad-service-remote-docker' and set 'remoteSandbox' (or PC_REMOTE_SANDBOX) "
                "to its host:port."
            )

        # What the environment over there has to hold. Collected as callers ask
        # for it and sent with every request: the service installs what it does
        # not already have, and a list it has seen before costs a dictionary
        # lookup rather than a round trip.
        self.requirements = []

        # Nothing is provisioned here, so nothing has to be found here.
        self.exec_name = "python"
        self.exec_path = None

    # ------------------------------------------------------------ provisioning --
    #
    # All of it is somebody else's, so all of it is a note to self. The service
    # builds the environment on the first request that names one.

    def once(self):
        self.provisioned = True

    async def once_async(self):
        self.provisioned = True

    def ensure(self, python_package, session=None, path=None, force=False):
        self._want(python_package)

    async def ensure_async(self, python_package, session=None, path=None, force=False):
        self._want(python_package)

    async def prepare_for_package(self, project, session=None):
        for dep in runtime_python.package_requirements(project):
            self._want(dep)

    async def prepare_for_shape(self, config, session=None):
        for req in runtime_python.shape_requirements(config):
            self._want(req)

    def _want(self, requirement) -> None:
        requirement = str(requirement)
        if requirement and requirement not in self.requirements:
            self.requirements.append(requirement)

    # --------------------------------------------------------------- running --

    def _token(self):
        """The shared secret the service was started with, if the user set one.

        Read at request time rather than kept from construction, so that a
        `pc --python-sandbox remote` run and a long-lived daemon both see what
        the configuration says now.
        """
        return getattr(self.ctx.user_config, "remote_sandbox_token", None)

    def _client(self) -> RuntimeJsonRpcClient:
        """Who to talk to, and whether it may be talked to in the clear.

        'remoteSandbox' is 'host:port', optionally with a scheme in front of it.
        The scheme is what a deployment behind a TLS-terminating proxy needs, and
        the absence of one means plain HTTP -- which is what a container on this
        machine speaks and what a tunnel's near end speaks.
        """
        endpoint = str(self.endpoint)
        scheme = "http"
        for prefix in ("https://", "http://"):
            if endpoint.lower().startswith(prefix):
                scheme = prefix[:-3]
                endpoint = endpoint[len(prefix) :]
                break
        host, _, port = endpoint.rpartition(":")
        # The port as well as the host: 'remoteSandbox' is something a person
        # typed, and 'host:' or 'host:abc' would otherwise reach int() and come
        # back as a traceback rather than as the sentence below.
        if not host or not port.isdigit():
            raise runtime.SandboxUnavailable(
                "'%s' does not name a host and a port for the remote sandbox service." % self.endpoint
            )
        # Every request carries the shared secret and the package's own source,
        # and plain HTTP carries both in the clear. Loopback is nobody else's
        # business -- it is a container on this machine, or the near end of a
        # tunnel, which is how a remote service is reached securely. Anything
        # else has to say 'https://', and a deployment that has not got that far
        # is told so rather than quietly shipping its token across a network.
        if scheme == "http" and not _loopback(host):
            raise runtime.SandboxUnavailable(
                "'%s' would send this machine's requests -- the shared secret among them -- to another "
                "machine in the clear. Put the service behind TLS and say 'https://%s', or reach it "
                "through a tunnel and point 'remoteSandbox' at the near end of that." % (self.endpoint, endpoint)
            )
        return RuntimeJsonRpcClient(host, int(port), token=self._token(), scheme=scheme)

    def _params(self, cmd, stdin, cwd, input_files, output_files, input_dirs) -> dict:
        if input_dirs is None:
            input_dirs = input_dirs_for(cmd, cwd)
        params = self._rpc_params(stdin, cwd, input_files or [], output_files or [], input_dirs)
        params["image"] = self.image
        params["python_version"] = self.version
        params["requirements"] = list(self.requirements)
        return params

    def _answer(self, cmd, response, output_files):
        if not response:
            return self._no_response(self.name)
        if response.get("error"):
            return 1, "", str(response["error"].get("message") or response["error"])
        if "result" not in response:
            # Neither an answer nor an error is still a failure, and saying so
            # is better than the KeyError that reading it blind produced.
            return 1, "", "The remote sandbox service answered without a result: %s" % response
        # The service answers with the container's payload rather than its
        # envelope, and '_rpc_result' reads an envelope -- so it is given one.
        stdout, stderr, returncode = self._rpc_result({"result": response["result"]}, output_files or [])
        return self._finished(cmd, stdout, stderr, returncode)

    def run(self, cmd, stdin="", cwd=None, session=None, input_files=None, output_files=None, input_dirs=None):
        params = self._params(cmd, stdin, cwd, input_files, output_files, input_dirs)
        return self._answer(cmd, self._client().execute(list(cmd), params), output_files)

    async def run_async(
        self,
        cmd,
        stdin="",
        cwd=None,
        session=None,
        timeout=None,
        input_files=None,
        output_files=None,
        input_dirs=None,
    ):
        params = self._params(cmd, stdin, cwd, input_files, output_files, input_dirs)
        # The bound the caller was given, honoured. Dropped, it meant an
        # unresponsive service held the render open with nothing to wait for.
        answer = await self._client().execute_async(list(cmd), params, timeout=timeout)
        return self._answer(cmd, answer, output_files)
