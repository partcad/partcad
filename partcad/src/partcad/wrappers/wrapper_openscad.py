import os
import shutil
import tempfile
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    """
    Preprocess an SCAD file:
      - Copy it to a temp file
      - Resolve 'use' and 'include' directives by copying their files to /tmp
      - Append a method call if it doesn't already exist
    """
    build_parameters = {}
    if "build_parameters" in request:
        build_parameters = request["build_parameters"]
    if not build_parameters:
        return {"success": False, "exception": "No build parameters provided"}
    method = build_parameters.get("method", "")
    # delete the method from the build parameters
    build_parameters.pop("method", None)

    if build_parameters is None:
        build_parameters = {}

    tmp_fd, tmp_file_path = tempfile.mkstemp(suffix=".scad", dir="/tmp")
    os.close(tmp_fd)  # We only need the path; close the file descriptor.

    shutil.copy(path, tmp_file_path)

    if isinstance(build_parameters, list):
        # If args is a list, join it as a comma-separated string
        args_str = ", ".join(map(str, build_parameters))
    elif isinstance(build_parameters, dict):
        # If args is a dictionary, format it as key=value pairs
        args_str = ", ".join(f"{k}={v}" for k, v in build_parameters.items())
    else:
        # Handle strings, numbers, or any other type by converting to string
        args_str = str(build_parameters)

    new_line = f"{method}({args_str});"

    with open(tmp_file_path, "r") as f:
        lines = f.readlines()

    base_dir = os.path.dirname(path)
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith("use <") or line_stripped.startswith("include <"):

            file_name = line_stripped.split("<")[1].split(">")[0]
            file_path = os.path.join(base_dir, file_name)

            if os.path.exists(file_path):
                shutil.copy(file_path, "/tmp")
                print(f"Copied {file_name} to /tmp")
            else:
                print(f"File {file_name} not found in {base_dir}")

    original_content_str = "".join(lines)

    if new_line in original_content_str:
        print("The method call already exists in the file. No changes made.")
        return

    updated_content = f"{original_content_str}\n{new_line}"

    with open(tmp_file_path, "w") as f:
        f.write(updated_content)

    return {
        "success": True,
        # "exception": "",
        "newPath": tmp_file_path,
    }


path, request = wrapper_common.handle_input()

# Call CadQuery
model = process(path, request)

wrapper_common.handle_output(model)
