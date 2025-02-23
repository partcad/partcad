#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import asyncio
import docker
import os
import subprocess
import time

from .user_config import user_config

from .runtime_json_rpc import RuntimeJsonRpcClient
from . import logging as pc_logging


class Runtime:
    @staticmethod
    def get_internal_state_dir():
        return os.path.join(
            user_config.internal_state_dir,
            "sandbox",
        )

    def __init__(self, ctx, name):
        self.ctx = ctx
        self.name = name
        self.sandbox_dir = "pc-" + name  # Leave "pc-" for UX (e.g. in VS Code)
        self.path = os.path.join(
            Runtime.get_internal_state_dir(),
            self.sandbox_dir,
        )
        self.initialized = os.path.exists(self.path)

        self.rpc_client = None

    def use_docker(self, image_name: str, container_name: str, port: int, host: str = "localhost"):
        if self.rpc_client:
            return

        if not host or host == "localhost":
            docker_client = docker.from_env()
            pc_logging.debug("Got a docker client")
            try:
                container = docker_client.containers.get(container_name)
            except docker.errors.NotFound:
                pc_logging.debug("Starting a docker container")
                container = docker_client.containers.run(
                    image_name,
                    name=container_name,
                    detach=True,
                    # ports={f"{str(port)}/tcp": ("127.0.0.1", port)},
                    # TODO: Mount the root and .partcad directories
                    volumes={self.path: {"bind": "/data", "mode": "rw"}},
                )
            pc_logging.debug("Got a docker container: %s" % container)
            if container.status == "exited" or container.status == "stopped" or container.status == "created":
                pc_logging.debug("Starting the container")
                container.start()

            while True:
                container.reload()
                if container.status == "running":
                    pc_logging.debug("Container is running")
                    break
                elif container.status == "exited":
                    pc_logging.error("Container exited")
                    return
                else:
                    pc_logging.debug("Container is starting...")
                    time.sleep(1)

            pc_logging.debug("Container properties are: %s" % container.attrs)
            host = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
            pc_logging.debug("The docker container is running at: %s" % host)
        else:
            raise Exception("Remote docker sandboxes are not supported yet")

        self.rpc_client = RuntimeJsonRpcClient(host, port)

    def run(self, cmd, stdin=None, cwd=None):
        if self.rpc_client:
            response = self.rpc_client.execute(cmd, {"stdin": stdin, "cwd": cwd})
            if not response:
                return None, None
            stdout = response["stdout"]
            stderr = response["stderr"]
        else:
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                encoding="utf-8",
                # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=cwd,
            )
            stdout, stderr = p.communicate(
                input=stdin,
                # TODO(clairbee): add timeout
            )

            # if stdout:
            #     pc_logging.debug("Output of %s: %s" % (cmd, stdout))
        if stderr:
            pc_logging.debug("Error in %s: %s" % (cmd, stderr))

        # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
        # f = open("/tmp/log", "w")
        # f.write("Completed: %s\n" % cmd)
        # f.write(" stdin: %s\n" % stdin)
        # f.write(" stderr: %s\n" % stderr)
        # f.write(" stdout: %s\n" % stdout)
        # f.close()

        return stdout, stderr

    async def run_async(self, cmd, stdin=None, cwd=None):
        if self.rpc_client:
            response = await self.rpc_client.execute_async(cmd, {"stdin": stdin, "cwd": cwd})
            if not response:
                return None, None
            stdout = response["stdout"]
            stderr = response["stderr"]
        else:
            p = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=cwd,
            )
            stdout, stderr = await p.communicate(
                # TODO(clairbee): add timeout
                input=stdin.encode(),
                # TODO(clairbee): add timeout
            )

            stdout = stdout.decode()
            stderr = stderr.decode()

            # if stdout:
            #     pc_logging.debug("Output of %s: %s" % (cmd, stdout))
            if stderr:
                pc_logging.error("Error in %s: %s" % (cmd, stderr))

            # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
            # f = open("/tmp/log", "w")
            # f.write("Completed: %s\n" % cmd)
            # f.write(" stdin: %s\n" % stdin)
            # f.write(" stderr: %s\n" % stderr)
            # f.write(" stdout: %s\n" % stdout)
            # f.close()

            return stdout, stderr
