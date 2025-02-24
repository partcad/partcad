from flask import Flask, request, jsonify
from flask_jsonrpc import JSONRPC
import subprocess
import base64
import logging
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
    response = jsonify({'code': ex.code, 'message': ex.message})
    response.status_code = 400  # Bad Request
    return response


# Define allowed commands
ALLOWED_COMMANDS = {
    "kicad-cli": "/usr/bin/kicad-cli",
    "cat": "/usr/bin/cat",
    "ls": "/usr/bin/ls",
    # Add more allowed commands with their full paths
}


@jsonrpc.method("execute")
def handle_execute_command(command: t.List[str],
                           stdin: str = None,
                           cwd: str = None,
                           input_files: t.Dict[str, str] = {},
                           output_files: t.List[str] = [],
                           ) -> t.Dict[str, t.Union[int, str, t.Dict[str, str]]]:
    if not command:
        raise PartcadJsonRpcException(-32602, "Command parameter is required")

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
            "output_files": {k: base64.b64encode(open(v.name, "rb").read()).decode("utf-8") for k, v in temp_output_files.items()},
        }
    except Exception as e:
        raise PartcadJsonRpcException(-32000, f"Execution error: {str(e)}")



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
