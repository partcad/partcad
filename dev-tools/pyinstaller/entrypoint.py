#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Entry point of the frozen PartCAD command line tools.

The wheels expose `pc` and `partcad` as console scripts generated from
`[project.scripts]`. A frozen bundle has no console scripts, so this module
takes their place: it is the script PyInstaller analyzes and runs.

`click` derives the program name from `sys.argv[0]`, so the same frozen code
prints itself as `pc` or as `partcad` depending on which of the two executables
in the bundle was invoked.
"""

import sys

from partcad_cli.click.command import main

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

if __name__ == "__main__":
    sys.exit(main())
