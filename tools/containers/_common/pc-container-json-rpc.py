from flask import Flask, request, jsonify
import subprocess
import base64
import json

app = Flask(__name__)


class JsonRpcError(Exception):
    def __init__(self, code, message, data=None):
        self.code = code
        self.message = message
        self.data = data


@app.errorhandler(JsonRpcError)
def handle_json_rpc_error(error):
    response = {
        "jsonrpc": "2.0",
        "error": {"code": error.code, "message": error.message, "data": error.data},
        "id": None,  # Will be updated with actual request ID
    }
    return jsonify(response), 400


# Define allowed commands
ALLOWED_COMMANDS = {
    "echo": "/usr/bin/echo",
    "cat": "/usr/bin/cat",
    "ls": "/usr/bin/ls",
    # Add more allowed commands with their full paths
}


def handle_execute_command(params):
    if not isinstance(params, dict):
        raise JsonRpcError(-32602, "Invalid params")

    command = params.get("command")
    args = params.get("args", [])
    stdin_data = params.get("stdin_base64", "")

    if not command:
        raise JsonRpcError(-32602, "Command parameter is required")

    # Check if command is in allowlist
    if command not in ALLOWED_COMMANDS:
        raise JsonRpcError(
            -32602, f"Command '{command}' is not allowed. Allowed commands: {', '.join(ALLOWED_COMMANDS.keys())}"
        )

    try:
        # Use full path from allowlist
        command_path = ALLOWED_COMMANDS[command]

        # Decode base64 input if provided
        stdin_bytes = base64.b64decode(stdin_data) if stdin_data else None

        # Execute the command using full path
        process = subprocess.Popen(
            [command_path] + args,
            stdin=subprocess.PIPE if stdin_bytes else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Send input data if provided
        stdout, stderr = process.communicate(input=stdin_bytes)

        return {
            "exit_code": process.returncode,
            "stdout_base64": base64.b64encode(stdout).decode("utf-8"),
            "stderr_base64": base64.b64encode(stderr).decode("utf-8"),
        }
    except Exception as e:
        raise JsonRpcError(-32000, f"Execution error: {str(e)}")


@app.route("/jsonrpc", methods=["POST"])
def json_rpc():
    try:
        request_data = request.get_json()

        if not request_data:
            raise JsonRpcError(-32700, "Parse error")

        # Validate JSON-RPC request
        if request_data.get("jsonrpc") != "2.0":
            raise JsonRpcError(-32600, "Invalid Request")

        method = request_data.get("method")
        params = request_data.get("params", {})
        request_id = request_data.get("id")

        # Handle methods
        if method == "execute":
            result = handle_execute_command(params)
        else:
            raise JsonRpcError(-32601, f"Method '{method}' not found")

        # Prepare successful response
        response = {"jsonrpc": "2.0", "result": result, "id": request_id}

        return jsonify(response)

    except JsonRpcError as e:
        response = {
            "jsonrpc": "2.0",
            "error": {"code": e.code, "message": e.message, "data": e.data},
            "id": request_data.get("id") if request_data else None,
        }
        return jsonify(response), 400

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "error": {"code": -32603, "message": "Internal error", "data": str(e)},
            "id": request_data.get("id") if request_data else None,
        }
        return jsonify(response), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
