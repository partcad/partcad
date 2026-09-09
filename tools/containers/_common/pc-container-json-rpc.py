from flask import Flask, request, jsonify
from flask_jsonrpc import JSONRPC
import subprocess
import base64
import io
import json
import logging
import shutil
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

# Where a `remote` sandbox keeps its virtual environments, when this container
# is serving one. `partcad-service-remote-docker` mounts a volume there and says
# so, because where those environments live is its decision and not the image's;
# the default is the same path, for a container somebody started by hand.
SANDBOX_ROOT = os.environ.get("PC_CONTAINER_SANDBOX_ROOT", "/pc-sandbox")


def _sandbox_interpreter(name):
    """`name`, if it is the interpreter of an environment under the sandbox root.

    The allowlist names the commands an image was *built* to run, and an
    environment built at run time cannot be in it: its path carries a Python
    version nobody told the image about. So this is the second way in, and a
    narrow one -- the file has to be called `python` or `python3`, has to sit in
    a `bin` directory under the sandbox root, and has to already be there.

    It is not a widening of what a caller can do. The allowlist is what stops a
    caller running binaries the image was not built for; in an image whose
    allowlist already holds an interpreter, a caller can run whatever Python it
    likes through that, and everything under the sandbox root was put there by
    this service running exactly that interpreter.
    """
    # Absolute, and `os.path.isabs` rather than a leading "/": this service runs
    # inside a Linux image, where the two are the same thing, but the test suite
    # runs it in process on whichever machine the suite is running on -- and on
    # Windows every path it builds begins with a drive letter, so a leading "/"
    # refused every one of them and three of the tests below passed for the
    # wrong reason.
    if not isinstance(name, str) or not os.path.isabs(name):
        return None
    root = os.path.normpath(SANDBOX_ROOT)
    path = os.path.normpath(name)
    if not path.startswith(root + os.sep):
        return None
    if os.path.basename(path) not in ("python", "python3"):
        return None
    if os.path.basename(os.path.dirname(path)) != "bin":
        return None
    # The shape is not enough: a path that looks right and is not there would be
    # reported as a command that failed rather than as one that never ran.
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        return None
    return path


def _within(path, prefix):
    """The parts of `path` below `prefix`, or None if it is not below it.

    Separator-agnostic in both directions, and that is the whole point of it.
    The paths a caller sends are the caller's: a Windows client names
    `D:\\pkg` and `D:\\pkg\\solve.py`, and this server runs inside a Linux
    image where `os.sep` is `/`. Matching on `os.sep` alone left every one of
    those unsubstituted -- so the command kept naming a directory on a machine
    that is not this one, and the implementation was a path to nothing.

    Returns `()` for the prefix itself, so "it is the directory" and "it is not
    below it" stay distinguishable.
    """
    if path == prefix:
        return ()
    for separator in ("/", "\\"):
        if path.startswith(prefix + separator):
            tail = path[len(prefix) + 1 :]
            return tuple(part for part in tail.replace("\\", "/").split("/") if part)
    return None


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
            inside = _within(command[i], host_path)
            if inside is not None:
                command[i] = os.path.join(extracted[host_path], *inside) if inside else extracted[host_path]
                break

    # TODO(clairbee): input data validation for output files

    # The files this call exchanges with the caller, in one directory of their
    # own so that the whole lot goes away together.
    #
    # Plain files rather than 'tempfile.NamedTemporaryFile', which holds the
    # file open: on Windows nothing else may then open it by name, so writing
    # an input, or handing an output to the command, fails with "Permission
    # denied". This server runs inside a Linux image and would never meet that
    # -- but the code is also exercised directly by
    # 'tests/partcad/unit/test_container_execute.py', which is where it showed
    # up, and a file that is only open when something is reading or writing it
    # is the simpler thing in any case.
    exchange = tempfile.mkdtemp()

    def exchanged(index, name):
        """A path in the exchange directory, named after where it is used."""
        return os.path.join(exchange, "%d%s" % (index, os.path.splitext(name)[1]))

    for i in range(1, len(command)):
        if not isinstance(command[i], str):
            raise PartcadJsonRpcException(-32602, f"Command parameter at index {i} is not a string")
        if command[i] in input_files:
            temp_file = exchanged(i, command[i])
            with open(temp_file, "wb") as f:
                f.write(base64.b64decode(input_files[command[i]]))
            command[i] = temp_file

    temp_output_files = {}
    for i in range(1, len(command)):
        if not isinstance(command[i], str):
            raise PartcadJsonRpcException(-32602, f"Command parameter at index {i} is not a string")
        if command[i] in output_files:
            temp_output_files[command[i]] = exchanged(i, command[i])
            command[i] = temp_output_files[command[i]]

    # Check if command is in allowlist, or is an environment's own interpreter
    command_path = ALLOWED_COMMANDS.get(command[0]) or _sandbox_interpreter(command[0])
    if command_path is None:
        raise PartcadJsonRpcException(
            -32602,
            f"Command '{command[0]}' is not allowed. Allowed commands: {', '.join(ALLOWED_COMMANDS.keys())}"
            f", and the interpreter of an environment under {SANDBOX_ROOT}",
        )

    try:
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
            # Only the ones the command actually wrote: an implementation that
            # failed has left nothing there, and reporting an empty file for it
            # would be a path to nothing rather than a refusal.
            "output_files": {
                name: base64.b64encode(open(path, "rb").read()).decode("utf-8")
                for name, path in temp_output_files.items()
                if os.path.isfile(path)
            },
        }
    except Exception as e:
        raise PartcadJsonRpcException(-32000, f"Execution error: {str(e)}")
    finally:
        # Everything this call unpacked and everything it exchanged. The server
        # is long-lived -- one container serves every analysis a machine runs --
        # so a directory per call that is never removed is a disk that fills up.
        for directory in list(extracted.values()) + [exchange]:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
