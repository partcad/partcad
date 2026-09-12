#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import asyncio
import base64
import contextlib
import gzip
import io
import os
import subprocess
import tarfile
import time

import docker

from . import logging as pc_logging
from . import sandbox_lock
from .process_output import decode as decode_output
from .runtime_json_rpc import RuntimeJsonRpcClient


async def communicate(p, stdin: bytes, timeout=None):
    """``p.communicate(stdin)``, bounded by ``timeout`` and never orphaning ``p``.

    Two things asyncio does not do for a subprocess it stops waiting for, and
    both have cost this project a wedged CI job.

    It does not bound the wait, so a sandbox interpreter that never finishes
    holds its caller forever. ``timeout`` (seconds, ``None`` for no bound) is
    that bound, and raises ``asyncio.TimeoutError`` when it passes.

    And it does not kill the child when the await is cancelled -- by that
    timeout, by a Ctrl-C, or by a runner cancelling the job. The process keeps
    running, detached from anything that would reap it, which is what the
    "Terminate orphan process: pid (7107) (python)" lines at the end of a
    cancelled Actions run are. So kill it on the way out, whatever the way out
    is. The event loop's child watcher reaps it from there.
    """
    try:
        if timeout is None:
            return await p.communicate(input=stdin)
        return await asyncio.wait_for(p.communicate(input=stdin), timeout)
    except BaseException:
        if p.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                p.kill()
        raise


async def wait_for_port(host, port, timeout=30):
    """
    Asynchronously waits for a port to become open on the specified host.

    Args:
        host (str): The hostname or IP address to check.
        port (int): The port number to check.
        timeout (int, optional): The maximum time to wait in seconds. Defaults to 30.

    Returns:
        bool: True if the port is open within the timeout, False otherwise.
    """
    start_time = asyncio.get_event_loop().time()
    while True:
        writer = None
        try:
            _, writer = await asyncio.open_connection(host, port)
            return True
        except (ConnectionRefusedError, TimeoutError):
            if asyncio.get_event_loop().time() - start_time > timeout:
                return False
            await asyncio.sleep(1)
        finally:
            if writer:
                writer.close()
                await writer.wait_closed()


def pack_directory(path: str) -> str:
    """A directory as a base64 gzipped tar, for sending to a container.

    What `input_files` cannot carry. Anything that runs *code* needs its
    siblings: an implementation script imports the module it shares with the
    rest of its package, and so does the wrapper that runs it, so sending the
    one file the command names leaves it unable to start.

    Deterministic where it can be: entries sorted, and the mtimes and ownership
    left out, so that packing the same directory twice produces the same bytes.
    That is not for reproducibility's sake -- nothing compares these -- but so
    that a diff between two runs is a difference in the package rather than in
    the clock.

    The gzip *wrapper* has an mtime of its own, and that is why this builds the
    two layers itself instead of asking `tarfile` for "w:gz": that mode hands
    `gzip.GzipFile` no mtime, so it stamps the current time into the header and
    two packs of one directory came out differing in bytes 4 through 8 and
    nowhere else. Every promise above was kept and the function was still not
    deterministic -- which `test_packing_is_deterministic` caught only when its
    two calls happened to straddle a second.
    """
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:

            def sanitize(info: tarfile.TarInfo) -> tarfile.TarInfo:
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                return info

            for entry in sorted(os.listdir(path)):
                if entry in (".git", "__pycache__", ".venv"):
                    # Never wanted in a sandbox, and '.git' alone can be most of
                    # what a package weighs.
                    continue
                tar.add(os.path.join(path, entry), arcname=entry, filter=sanitize)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class SandboxUnavailable(Exception):
    """The sandbox mechanism an implementation asked for is not on this machine.

    Not a statement about the implementation, which may be perfectly good, nor
    about the part: it is the absence of a *runtime*, and PartCAD is the only
    thing that can tell, since the implementation never gets to run and so
    cannot report it itself.

    What `pc test` makes of it is not decided here but by the implementation:
    one that declares a `container:` or a `dockerImage` is saying that a
    container is how its dependencies arrive, so a machine with no container
    runtime is a machine that could never have run it, and the verdict is a
    skip. One that declares neither said it runs in an ordinary sandbox, and a
    machine with a working sandbox is a machine it was supposed to work on, so
    the verdict is a failure. What the type buys either way is the message:
    `CaeTest` reads it to add both remedies, which no other failure gets. See
    `partcad.test.cae.CaeTest._verdict()`.
    """


def docker_available() -> bool:
    """Whether a container sandbox can be started here.

    Asked before an implementation that declares one is run, and again by
    `pc test` to decide whether it is looking at an unavailable runtime or a
    failing implementation. Cached: this shells out to the daemon, and a run
    over a package tree would otherwise ask once per part.

    Deliberately a real ping rather than "is the module importable" or "is
    /var/run/docker.sock there": the `docker` package installs with PartCAD on
    every platform, and a socket can exist with nothing behind it. The question
    is whether a container can be started, and only the daemon answers that.

    And not only that a container can be started -- that one of *ours* can.
    Every image PartCAD builds, pulls or documents is a Linux image, and a
    Docker daemon on Windows runs Windows containers unless it has been switched
    to the WSL2 backend. Such a daemon answers a ping perfectly happily and then
    fails every pull with "no matching manifest for windows/amd64", which is a
    container runtime by the letter of the question and not by its point. So the
    daemon is asked what it runs, once, in the same cached call.
    """
    global _docker_available
    if _docker_available is None:
        try:
            client = docker.from_env()
            client.ping()
            os_type = str(client.info().get("OSType", "")).lower()
            if os_type and os_type != "linux":
                pc_logging.debug(
                    "The container runtime on this machine runs %s containers, and every image PartCAD"
                    " uses is a Linux image." % os_type
                )
                _docker_available = False
            else:
                _docker_available = True
        except Exception as e:
            pc_logging.debug("No container runtime on this machine: %s" % e)
            _docker_available = False
    return _docker_available


# None until something asks. Not reset: a run that started without Docker and
# would have finished with it is not worth the ping per part.
_docker_available = None


class Runtime:
    @staticmethod
    def get_internal_state_dir(internal_state_dir):
        return os.path.join(
            internal_state_dir,
            "sandbox",
        )

    def __init__(self, ctx, name):
        self.ctx = ctx
        self.name = name
        self.sandbox_dir = "pc-" + name  # Leave "pc-" for UX (e.g. in VS Code)
        self.path = os.path.join(
            Runtime.get_internal_state_dir(self.ctx.user_config.internal_state_dir),
            self.sandbox_dir,
        )
        self.initialized = os.path.exists(self.path)

        self.rpc_client = None

    async def use_docker(self, image_name: str, container_name: str, port: int, host: str = "localhost"):
        if self.rpc_client:
            return

        if not host or host == "localhost":
            docker_client = docker.from_env()
            pc_logging.debug("Got a docker client")
            try:
                container = docker_client.containers.get(container_name)
            except docker.errors.NotFound:
                pc_logging.debug("Starting a docker container")

                # # Since .containers.run() fails to pull the image on some platforms, we do it manually
                # image_found = False
                # try:
                #     images = docker_client.api.images(image_name)
                #     if images:
                #         image_found = True
                # except docker.errors.ImageNotFound:
                #     pass
                # if not image_found:
                #     pc_logging.debug("Image not found: %s" % image_name)
                #     try:
                #         docker_client.api.pull(image_name)
                #     except docker.errors.ImageNotFound:
                #         pc_logging.error("Failed to pull the image: %s" % image_name)
                #         pass

                container = docker_client.containers.run(
                    image_name,
                    name=container_name,
                    detach=True,
                    # TODO(clairbee): mount data directories across docker containers
                    # TODO: Mount the root and .partcad directories
                    # volumes={self.path: {"bind": "/data", "mode": "rw"}},
                )
            pc_logging.debug("Got a docker container: %s" % container)
            pc_logging.debug("Container status: %s" % container.status)
            if container.status == "exited" or container.status == "stopped" or container.status == "created":
                pc_logging.debug("Starting the container")
                container.start()

            timeout = time.time() + 300
            while time.time() < timeout:
                container.reload()
                if container.status == "running":
                    pc_logging.debug("Container is running")
                    host = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
                    if await wait_for_port(host, port):
                        pc_logging.debug(f"{host}:{port} is open!")
                    else:
                        pc_logging.error(f"Timeout waiting for the container: {host}:{port}")
                    break
                elif container.status == "exited":
                    pc_logging.error("Container exited")
                    return
                else:
                    pc_logging.debug("Container is starting...")
                    await asyncio.sleep(1)

            pc_logging.debug("Container properties are: %s" % container.attrs)
            host = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
            pc_logging.debug("The docker container is running at: %s" % host)
        else:
            raise Exception("Remote docker sandboxes are not supported yet")

        self.rpc_client = RuntimeJsonRpcClient(host, port)

    # ----------------------------------------------------------------- #
    # What 'run' and 'run_async' both do                                  #
    # ----------------------------------------------------------------- #
    #
    # They are the same command run two ways, and the parts that are not the
    # subprocess call are the same in both. They used to be written out twice,
    # and the copies had drifted: the container half of 'run_async' invented its
    # exit code from whether anything reached stderr, read 'p.returncode' where
    # 'p' does not exist, sent its standard input unencoded to a server that
    # decodes base64, and returned two values on one path out of three. None of
    # that was noticed because no implementation ran in a container until now.
    # One copy of each is what keeps them from drifting again.

    def _rpc_params(self, stdin, cwd, input_files, output_files, input_dirs):
        """The parameters a container is asked with.

        'stdin' is base64 because the server decodes it as base64, which is not
        obvious from either end: 'base64.b64decode' does not refuse text that is
        not base64 -- it drops every character outside the alphabet and decodes
        what is left -- so an unencoded request arrives as noise rather than as
        an error.
        """
        file_contents = {}
        for file_path in input_files:
            with open(file_path, "rb") as f:
                file_contents[file_path] = base64.b64encode(f.read()).decode("utf-8")
        return {
            "stdin": base64.b64encode(stdin.encode("utf-8")).decode("utf-8") if stdin else None,
            "cwd": cwd,
            "input_files": file_contents,
            "output_files": output_files,
            "input_dirs": {path: pack_directory(path) for path in input_dirs},
        }

    def _rpc_result(self, response, output_files):
        """What a container answered, as (stdout, stderr, exit code).

        The output files it produced are written where the caller asked for
        them, which is the point of naming them: the file was written inside the
        container, under a name of the container's choosing.
        """
        result = response["result"]
        stdout = result["stdout"]
        stdout = base64.b64decode(stdout).decode("utf-8") if stdout else None
        stderr = result["stderr"]
        stderr = base64.b64decode(stderr).decode("utf-8") if stderr else None
        for file_name, file_contents in (result.get("output_files") or {}).items():
            if file_name in output_files:
                with open(file_name, "wb") as f:
                    f.write(base64.b64decode(file_contents))
            else:
                pc_logging.error(f"Unsolicited output file: {file_name}")
        # What the command exited with, which the server reports. The fallback
        # is for an image built before it did, and is what this used to do for
        # every container: read any stderr at all as a failure.
        returncode = result.get("exit_code")
        return stdout, stderr, int(bool(stderr)) if returncode is None else returncode

    def _finished(self, cmd, stdout, stderr, returncode):
        """The triple every run returns, having reported what was written.

        Anything on stderr from a command that succeeded is a warning and is
        cleared: a library that prints is not a library that failed, and a
        wrapper's sandbox deliberately moves everything that prints onto stderr
        so that it cannot corrupt the response (see wrappers/wrapper_common.py).
        That makes the exit code the only thing that says whether a run worked.
        """
        if stdout:
            pc_logging.debug("Output of %s: %s" % (cmd, stdout))
        if stderr:
            # TODO(azhar): remove this when the issue is fixed
            keywords = [
                "DEPRECATION: Wheel filename",
                "Invalid wheel filename (invalid version):",
                "pip 25.3 will enforce this behaviour change.",
            ]
            stderr_lines = [
                line.strip()
                for line in stderr.splitlines()
                if line.strip() and not any(keyword in line for keyword in keywords)
            ]
            if stderr_lines:
                stderr = "\n".join(stderr_lines)
                if returncode == 0:
                    pc_logging.warning("%s produced stderr: %s" % (cmd, stderr))
                    stderr = ""
                else:
                    pc_logging.error("Error in %s: %s" % (cmd, stderr))
            else:
                stderr = ""

        # [Temporary Fix] Ignore exit code 3221226356(0xc0000374) and 3221225477(0xc0000005)
        # This is a known and open issue on Windows related to the cadquery import
        # For more information, see: https://github.com/CadQuery/cadquery/issues/1564
        if returncode in [3221226356, 3221225477]:
            returncode = 0
        return returncode, stdout, stderr

    @staticmethod
    def _no_response(name):
        """Three values, like every other way out of a run.

        Two was an unpacking error at the call site rather than the report that
        a container answered nothing, which is a failure like any other.
        """
        return 1, None, "The container serving '%s' returned no response" % name

    def _spawn(self, cmd, cwd=None, env=None):
        """What to actually launch: the argv, the directory, the environment.

        The one seam a sandbox overrides when the process it wants is not the
        process it was handed. The 'docker' sandbox turns the argv into a
        'docker exec' of the same argv, and moves the working directory into a
        '-w' flag, because that directory belongs to the container rather than
        to whichever machine the 'docker' client runs on.

        It has to be here, and applied at every launch point, because there are
        two: this class runs a command with 'subprocess', and 'PythonRuntime'
        runs one with its own 'subprocess' call after prepending an interpreter.
        A sandbox that overrode a 'run' method instead would catch whichever of
        the two its caller happened to use -- which is how the 'docker' sandbox
        came to build its virtual environment with the host's interpreter while
        a container sat beside it doing nothing.
        """
        return cmd, cwd, env

    def run(
        self,
        cmd: list[str],
        stdin: str = None,
        cwd: str = None,
        input_files: list[str] = None,
        output_files: list[str] = None,
        env: dict = None,
        input_dirs: list[str] = None,
    ):
        # 'env' replaces this process's environment for the child, and is only
        # ever passed by a runtime that has to place something of its own on it
        # (see JavaScriptRuntime._subprocess_env(), which puts the sandbox's
        # Node.js on PATH so that the 'npm' script's '#!/usr/bin/env node' finds
        # it). It has no counterpart in the RPC path below: what a remote
        # executor's environment should be is that executor's business.
        if input_files is None:
            input_files = []
        if output_files is None:
            output_files = []
        if input_dirs is None:
            input_dirs = []

        if self.rpc_client:
            response = self.rpc_client.execute(cmd, self._rpc_params(stdin, cwd, input_files, output_files, input_dirs))
            if not response:
                return self._no_response(self.name)
            stdout, stderr, returncode = self._rpc_result(response, output_files)
        else:
            argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, env)
            with sandbox_lock.process_slots.slot():
                p = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    encoding="utf-8",
                    # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=spawn_cwd,
                    env=spawn_env,
                )
                stdout, stderr = p.communicate(
                    input=stdin,
                    # TODO(clairbee): add timeout
                )
            returncode = p.returncode

        return self._finished(cmd, stdout, stderr, returncode)

    async def run_async(
        self,
        cmd: list[str],
        stdin: str = None,
        cwd: str = None,
        input_files: list[str] = None,
        output_files: list[str] = None,
        env: dict = None,
        timeout: float = None,
        input_dirs: list[str] = None,
    ):
        if input_files is None:
            input_files = []
        if output_files is None:
            output_files = []
        if input_dirs is None:
            input_dirs = []

        if self.rpc_client:
            response = await self.rpc_client.execute_async(
                cmd, self._rpc_params(stdin, cwd, input_files, output_files, input_dirs)
            )
            if not response:
                return self._no_response(self.name)
            stdout, stderr, returncode = self._rpc_result(response, output_files)
        else:
            argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, env)
            async with sandbox_lock.process_slots.slot_async():
                p = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=spawn_cwd,
                    env=spawn_env,
                )
                stdout, stderr = await communicate(p, stdin.encode(), timeout)

            stdout = decode_output(stdout)
            stderr = decode_output(stderr)
            returncode = p.returncode

        return self._finished(cmd, stdout, stderr, returncode)
