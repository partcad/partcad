from flask import Flask, request, jsonify
from flask_jsonrpc import JSONRPC
import subprocess
import base64
import io
import json
import logging
import tarfile
import typing as t
import tempfile
import os

logging.basicConfig(level=logging.DEBUG)

logging.info("Starting the PartCAD Container JSON-RPC Server...")

app = Flask(__name__)
jsonrpc = JSONRPC(app, "/jsonrpc", enable_web_browsable_api=True)


class PartcadJsonRpcException(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


@app.errorhandler(PartcadJsonRpcException)
def handle_partcad_exception(ex: PartcadJsonRpcException):
    response = jsonify({"code": ex.code, "message": ex.message})
    response.status_code = 400  # Bad Request
    return response


# Define allowed commands
ALLOWED_COMMANDS = {
    "kicad-cli": "/usr/bin/kicad-cli",
    "cat": "/usr/bin/cat",
    "ls": "/usr/bin/ls",
    # Add more allowed commands with their full paths
}

# What an image adds to the allowlist, as a JSON object of name -> full path.
# The allowlist is the whole of this server's isolation: a caller names a
# command and the server decides whether it exists. Which commands an image is
# for is the image's business -- the KiCad one allows `kicad-cli`, one built to
# run PartCAD implementations allows its sandbox interpreter -- and hardcoding
# every future image's tools in the shared server would mean editing this file
# to add a container that has nothing to do with the others.
#
# Set in the Dockerfile rather than by the caller, and read once at start-up, so
# that the running server's allowlist is a property of the image and not
# something a request can widen.
for _name, _path in json.loads(os.environ.get("PC_CONTAINER_ALLOWED_COMMANDS", "{}")).items():
    ALLOWED_COMMANDS[str(_name)] = str(_path)
logging.info("Allowed commands: %s", ", ".join(sorted(ALLOWED_COMMANDS)))


@jsonrpc.method("execute")
def handle_execute_command(
    command: t.List[str],
    stdin: t.Optional[str] = None,
    cwd: t.Optional[str] = None,
    input_files: t.Optional[t.Dict[str, str]] = None,
    output_files: t.Optional[t.List[str]] = None,
    input_dirs: t.Optional[t.Dict[str, str]] = None,
) -> t.Dict[str, t.Union[int, str, t.Dict[str, str]]]:
    if input_files is None:
        input_files = {}
    if output_files is None:
        output_files = []
    if input_dirs is None:
        input_dirs = {}
    if not command:
        raise PartcadJsonRpcException(-32602, "Command parameter is required")

    # Whole directories, as base64 gzipped tars, keyed by the path they had on
    # the caller's machine. `input_files` is not enough for anything that runs
    # *code*: a script imports its siblings, so sending the one file the command
    # names leaves it unable to start. A PartCAD implementation is exactly that
    # -- a script in a package, beside the module it shares with the package's
    # other scripts -- and so is the wrapper that runs it.
    #
    # Substituted by prefix rather than by equality, which is what lets one
    # directory cover both the script named in the command and the package
    # directory passed as an argument. Longest first, so a directory sent inside
    # another resolves to itself.
    extracted = {}
    for host_path, archive in input_dirs.items():
        target = tempfile.mkdtemp()
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(archive)), mode="r:gz") as tar:
            for member in tar.getmembers():
                # A member escaping the directory it is extracted into is how an
                # archive from elsewhere becomes a write to /usr/bin.
                resolved = os.path.realpath(os.path.join(target, member.name))
                if os.path.commonpath([os.path.realpath(target), resolved]) != os.path.realpath(target):
                    raise PartcadJsonRpcException(-32602, f"Archive member escapes its directory: {member.name}")
                if member.issym() or member.islnk():
                    raise PartcadJsonRpcException(-32602, f"Archive member is a link: {member.name}")
            tar.extractall(target)
        extracted[host_path] = target
    for i in range(1, len(command)):
        if not isinstance(command[i], str):
            raise PartcadJsonRpcException(-32602, f"Command parameter at index {i} is not a string")
        for host_path in sorted(extracted, key=len, reverse=True):
            if command[i] == host_path or command[i].startswith(host_path + os.sep):
                command[i] = extracted[host_path] + command[i][len(host_path) :]
                break

    # TODO(clairbee): input data validation for output files

    # Replace the file names with temporary files
    temp_files = []
    for i in range(1, len(command)):
        if not isinstance(command[i], str):
            raise PartcadJsonRpcException(-32602, f"Command parameter at index {i} is not a string")
        if command[i] in input_files:
            temp_file = tempfile.NamedTemporaryFile(delete=True, suffix=os.path.splitext(command[i])[1])
            temp_files.append(temp_file)
            with open(temp_file.name, "wb") as f:
                f.write(base64.b64decode(input_files[command[i]]))
            command[i] = temp_file.name

    temp_output_files = {}
    for i in range(1, len(command)):
        if not isinstance(command[i], str):
            raise PartcadJsonRpcException(-32602, f"Command parameter at index {i} is not a string")
        if command[i] in output_files:
            temp_output_file = tempfile.NamedTemporaryFile(delete=True, suffix=os.path.splitext(command[i])[1])
            temp_output_files[command[i]] = temp_output_file
            command[i] = temp_output_file.name

    # Check if command is in allowlist
    if command[0] not in ALLOWED_COMMANDS:
        raise PartcadJsonRpcException(
            -32602, f"Command '{command[0]}' is not allowed. Allowed commands: {', '.join(ALLOWED_COMMANDS.keys())}"
        )

    try:
        # Use full path from allowlist
        command_path = ALLOWED_COMMANDS[command[0]]

        # Decode base64 input if provided
        stdin_bytes = base64.b64decode(stdin) if stdin else None

        # Execute the command using full path
        process = subprocess.Popen(
            [command_path] + command[1:],
            stdin=subprocess.PIPE if stdin_bytes else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )

        # Send input data if provided
        stdout, stderr = process.communicate(input=stdin_bytes)

        return {
            "exit_code": process.returncode,
            "stdout": base64.b64encode(stdout).decode("utf-8"),
            "stderr": base64.b64encode(stderr).decode("utf-8"),
            "output_files": {
                k: base64.b64encode(open(v.name, "rb").read()).decode("utf-8") for k, v in temp_output_files.items()
            },
        }
    except Exception as e:
        raise PartcadJsonRpcException(-32000, f"Execution error: {str(e)}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
