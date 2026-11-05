# Shared integration helpers

This directory contains scripts and files that are shared between integration solutions for different third-party tools.

Two of them are copies of files in `src/`, kept byte-for-byte the same by a test, because a Docker build cannot
reach outside this directory to read the originals. Edit the one in `src/` and copy it over:

- `pc-container-json-rpc.py` is `src/partcad_utils/container_service.py`, the service every container runs.
- `cadmpeg_tool.py` is `src/partcad/builtin/import/cadmpeg_tool.py`, which pins cadmpeg and installs it into
  the Python sandbox image (`python3 cadmpeg_tool.py /usr/local/bin`).
