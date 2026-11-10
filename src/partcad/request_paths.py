#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The paths a wrapper's request names, made to reach a sandbox that is sent files.

A wrapper is handed two things: a command line and a request on standard input.
A sandbox that shares this machine's files -- a local environment, a container
with them mounted -- sees every path in either. One that exchanges them rather
than sharing them -- the ``remote`` sandbox, ``docker`` with ``useDockerRemote``
(``EXCHANGES_FILES``) -- sees only what it is sent: it works out which
directories to send from the command line (`runtime_python_remote.input_dirs_for`),
unpacks them somewhere of its own choosing, and rewrites every argument naming
something it unpacked. The request it cannot rewrite: it is one opaque string,
and a path in it names a file where it is on PartCAD's side, which over there is
nowhere. That is how a reader whose script, source file and search paths travel
in the request failed in upload mode with "No such file or directory" naming a
file that exists, and how a sketch read from a DXF did.

So the paths go on the command line as well, after everything else, behind
`ARGUMENT` -- which sends what they are in and has them rewritten -- and the
request says which of its values they are (`KEY`). The wrapper puts the
rewritten spellings back into the request before anything reads it, and spells
the paths it answers with as PartCAD spelled them
(`wrappers/wrapper_common.adopt_paths`, `to_host`): a reader's tree names the
files its parts are read from, and those are read on this side.

What a command writes is not in the command, so a directory the wrapper writes
into is named to the runtime besides (`written`), and it comes back.

A sandbox that shares the files is handed the same command and rewrites
nothing, so the paths are the ones in the request and nothing changes.
"""

import os

# The request's record of which of its values are paths: '[key, index]' each,
# the index None for a value that is a path itself and a position for one in a
# list. Twin of 'wrapper_common.PATHS_KEY'.
KEY = "__paths__"

# The command line argument the paths follow, after every other argument. Twin
# of 'wrapper_common.PATHS_ARGUMENT'.
ARGUMENT = "--request-paths"


def carry(command, request: dict, keys) -> list:
    """`command` with the paths `request` holds under `keys` after it, and `request` told where they came from.

    A value under one of `keys` is a path, or a list of them; anything else
    there (None, a number) is not a path and is left alone. Each path is made
    absolute in the request as well as on the command line, because a sandbox
    rewrites an argument by the directory it is in, and a relative one is in
    none -- and because the two spellings have to be one path for the wrapper to
    pair them.

    A request with no path under any of `keys` is not changed, and neither is
    the command.
    """
    places, paths = [], []
    for key in keys:
        value = request.get(key)
        if isinstance(value, str) and value:
            request[key] = os.path.abspath(value)
            places.append([key, None])
            paths.append(request[key])
        elif isinstance(value, (list, tuple)):
            value = list(value)
            for index, item in enumerate(value):
                if isinstance(item, str) and item:
                    value[index] = os.path.abspath(item)
                    places.append([key, index])
                    paths.append(value[index])
            request[key] = value
    if not paths:
        return list(command)
    request[KEY] = places
    return list(command) + [ARGUMENT] + paths


def written(runtime, *directories) -> dict:
    """The keyword arguments telling `runtime` which directories a command writes into, if it has to be told.

    Only a runtime that exchanges files is: it sends back what it was told
    comes back, and a directory that was written into and not named stays in
    the sandbox. Every other runtime is handed nothing, because the ones that
    share files override 'run_async' with a narrower signature that takes no
    such argument.
    """
    if not getattr(runtime, "EXCHANGES_FILES", False):
        return {}
    return {"output_dirs": [os.path.abspath(directory) for directory in directories if directory]}
