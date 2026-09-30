#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Entry point of the frozen PartCAD command line tools.

The wheels expose `pc`, `partcad`, and `partcad-json-rpc` as console scripts
generated from `[project.scripts]`. A frozen bundle has no console scripts, so
this module takes their place: it is the single script PyInstaller analyzes and
runs for all three executables in the bundle.

Which one ran is decided from `sys.argv[0]`: `partcad-json-rpc` starts the
JSON-RPC service, and any other name runs the CLI. `click`, in turn, derives its
program name from `sys.argv[0]`, so the same CLI code prints itself as `pc` or
as `partcad`.
"""

import os
import sys

from partcad_cli.click.command import main as cli_main

# Imported so PyInstaller follows it into the bundle; dispatched to only when the
# `partcad-json-rpc` executable is the one invoked.
from partcad_service_json_rpc.__main__ import main as service_main

# The banner and the box drawing characters in the help output are not
# encodable in the code page Windows hands a redirected stdout (cp1252), so
# `pc --help > out.txt` there dies with a UnicodeEncodeError before printing
# anything. A wheel inherits whatever encoding the user's Python was configured
# with; the bundle owns its interpreter, so it can settle the question itself.
# `errors="replace"` covers the streams that still cannot take UTF-8: garbled
# output beats a traceback.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")


def main():
    program = os.path.basename(sys.argv[0]).lower()
    if program.startswith("partcad-json-rpc"):
        return service_main()
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
