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
import base64

from .user_config import user_config

from .runtime_json_rpc import RuntimeJsonRpcClient
from . import logging as pc_logging

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
        try:
            _, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, TimeoutError):
            if asyncio.get_event_loop().time() - start_time > timeout:
                return False
            await asyncio.sleep(1)

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
                    time.sleep(1)

            pc_logging.debug("Container properties are: %s" % container.attrs)
            host = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
            pc_logging.debug("The docker container is running at: %s" % host)
        else:
            raise Exception("Remote docker sandboxes are not supported yet")

        self.rpc_client = RuntimeJsonRpcClient(host, port)

    def run(self, cmd, stdin=None, cwd=None, input_files=[], output_files=[]):
        if self.rpc_client:
            file_contents = dict(map(lambda x: (x, base64.b64encode(open(x, "rb").read()).decode("utf-8")), input_files))
            response = self.rpc_client.execute(cmd, {"stdin": stdin, "cwd": cwd, "input_files": file_contents, "output_files": output_files,},)
            if not response:
                return None, None
            stdout = response["result"]["stdout"]
            stdout = base64.b64decode(stdout).decode("utf-8") if stdout else None
            stderr = response["result"]["stderr"]
            stderr = base64.b64decode(stderr).decode("utf-8") if stderr else None
            if response["result"]["output_files"]:
                for file_name, file_contents in response["result"]["output_files"].items():
                  if file_name in output_files:
                    with open(file_name, "wb") as f:
                        f.write(base64.b64decode(file_contents))
                  else:
                    pc_logging.error(f"Unsolicited output file: {file_name}")
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

    async def run_async(self, cmd, stdin=None, cwd=None, input_files=[], output_files=[]):
        if self.rpc_client:
            # Load the contents of the given files
            file_contents = dict(map(lambda x: (x, base64.b64encode(open(x, "rb").read()).decode("utf-8")), input_files))
            response = await self.rpc_client.execute_async(cmd, {"stdin": stdin, "cwd": cwd, "input_files": file_contents, "output_files": output_files,},)
            if not response:
                return None, None
            stdout = response["result"]["stdout"]
            stdout = base64.b64decode(stdout).decode("utf-8") if stdout else None
            stderr = response["result"]["stderr"]
            stderr = base64.b64decode(stderr).decode("utf-8") if stderr else None
            if response["result"]["output_files"]:
                for file_name, file_contents in response["result"]["output_files"].items():
                  if file_name in output_files:
                    with open(file_name, "wb") as f:
                        f.write(base64.b64decode(file_contents))
                  else:
                    pc_logging.error(f"Unsolicited output file: {file_name}")
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
