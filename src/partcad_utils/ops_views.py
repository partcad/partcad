#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Operations views, declared once: which kinds of subject each applies to, and how each surface names it.

Operations is four questions -- Revisions, Dependencies, Used By, Impact --
asked of a subject: a package or one object of it. Each is a tab of the IDE's
Operations group, a 'pc ops' command or two, an MCP tool for each command, and a
daemon method for each. Which of them a subject has depends on its kind, and
that is said here, once, for everyone who asks: the daemon answers 'ops.views'
from it (which the IDE draws its tabs from, and 'pc ops summary' prints), and
refuses a method for a kind it does not apply to in words taken from it.

It is in 'partcad_utils' because both ends read it: the daemon, and the clients
that say what a command applies to before they ask.
"""

from partcad_utils.object_names import NAMED_KINDS, describe

PACKAGE = "package"
# Every kind a subject can be.
SUBJECT_KINDS = (PACKAGE,) + tuple(NAMED_KINDS)
# The kinds that name nothing of their own -- what a software object depends on
# is its own business -- and so have no Dependencies or Impact.
_NO_REFERENCES = ("software",)

# One entry per command: its view, the command, its MCP tool, its daemon method,
# the kinds it applies to, and whether it changes anything.
COMMANDS = (
    {"view": "revisions", "command": "pc ops rev list", "tool": "ops_rev_list", "method": "ops.rev.list"},
    {"view": "revisions", "command": "pc ops rev diff", "tool": "ops_rev_diff", "method": "ops.rev.diff"},
    {"view": "revisions", "command": "pc ops rev status", "tool": "ops_rev_status", "method": "ops.rev.status"},
    {
        "view": "revisions",
        "command": "pc ops rev stage",
        "tool": "ops_rev_stage",
        "method": "ops.rev.stage",
        "writes": True,
    },
    {"view": "revisions", "command": "pc ops rev new", "tool": "ops_rev_new", "method": "ops.rev.new", "writes": True},
    {"view": "dependencies", "command": "pc ops deps list", "tool": "ops_deps_list", "method": "ops.deps.list"},
    {
        "view": "dependencies",
        "command": "pc ops deps add",
        "tool": "ops_deps_add",
        "method": "ops.deps.add",
        "kinds": (PACKAGE,),
        "writes": True,
    },
    {
        "view": "dependencies",
        "command": "pc ops deps remove",
        "tool": "ops_deps_remove",
        "method": "ops.deps.remove",
        "kinds": (PACKAGE,),
        "writes": True,
    },
    {
        "view": "dependencies",
        "command": "pc ops deps update",
        "tool": "ops_deps_update",
        "method": "ops.deps.update",
        "kinds": (PACKAGE,),
        "writes": True,
    },
    {"view": "usedby", "command": "pc ops used-by", "tool": "ops_used_by", "method": "ops.used_by"},
    {"view": "impact", "command": "pc ops impact", "tool": "ops_impact", "method": "ops.impact"},
)

# The views, in the order the IDE's Operations group shows them.
VIEWS = (
    {"id": "revisions", "label": "Revisions", "kinds": SUBJECT_KINDS},
    {
        "id": "dependencies",
        "label": "Dependencies",
        "kinds": tuple(kind for kind in SUBJECT_KINDS if kind not in _NO_REFERENCES),
    },
    {"id": "usedby", "label": "Used By", "kinds": SUBJECT_KINDS},
    {"id": "impact", "label": "Impact", "kinds": tuple(kind for kind in SUBJECT_KINDS if kind not in _NO_REFERENCES)},
)


def view(view_id: str) -> dict:
    for view in VIEWS:
        if view["id"] == view_id:
            return view
    raise KeyError(view_id)


def command_kinds(entry: dict) -> tuple:
    """The kinds of subject a command applies to: its own list, or its view's."""
    return entry.get("kinds") or view(entry["view"])["kinds"]


def views_for(kind: str) -> list:
    """The views a subject of 'kind' has, each with the commands that apply to it: what 'ops.views' answers."""
    found = []
    for view in VIEWS:
        if kind not in view["kinds"]:
            continue
        commands = [
            {key: entry[key] for key in ("command", "tool", "method")} | {"writes": bool(entry.get("writes"))}
            for entry in COMMANDS
            if entry["view"] == view["id"] and kind in command_kinds(entry)
        ]
        found.append({"id": view["id"], "label": view["label"], "commands": commands})
    return found


def by_method(method: str) -> dict:
    for entry in COMMANDS:
        if entry["method"] == method:
            return entry
    raise KeyError(method)


def refusal(method: str, kind: str, subject: str) -> str:
    """Why 'method' does not apply to a subject of 'kind', in the words every surface says it in; '' when it does."""
    entry = by_method(method)
    kinds = command_kinds(entry)
    if kind in kinds:
        return ""
    command = entry["command"].replace("pc ops ", "")
    applies = " or ".join(describe(each) if each != PACKAGE else "a package" for each in kinds)
    return "%s applies to %s; %s is %s" % (
        command,
        applies,
        subject,
        describe(kind) if kind != PACKAGE else "a package",
    )
