#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Write the Gemini CLI extension beside the Claude plugin in a materialized marketplace.

`materialize.sh` builds the tree the `plugin-dist` branch is published from: a
Claude Code marketplace at its root. A Gemini CLI extension is a directory with
`gemini-extension.json` at its root -- the *absolute* root of the repository or
archive it is installed from, never a subdirectory -- so the same branch can be
both, and

    gemini extensions install https://github.com/partcad/partcad --ref plugin-dist

installs the same skills, the same MCP server and the same release as
`/plugin install pc@partcad` does. What this writes at the root of OUT_DIR:

    gemini-extension.json        the manifest: name, version, `pc mcp`, context file
    GEMINI.md                    what the extension tells the model before anything else
    skills/pc-<skill>/SKILL.md   every skill, as every agent without a plugin namespace gets it

The skills are renamed and stamped exactly as `pc init` renames them for
`.agents/skills` (`partcad_utils.agent_skills.rename_skill`), so that a skill is
`pc-<skill>` in Gemini whichever way it got there. That module is loaded by its
path: this runs on a bare runner, where `partcad_utils` is not installed and
importing its package would pull in more than this needs.

The version is the Claude plugin manifest's, which `dev-tools/bumpversion.toml`
moves with the release: no second literal to bump.

It also writes the extension as release archives, for

    gemini extensions install https://github.com/partcad/partcad

which installs from the latest GitHub release rather than from a branch, and is
what `gemini extensions update` then follows. Gemini CLI takes the release asset
whose name starts with `<platform>.<arch>.` or `<platform>.` (`linux`, `darwin`,
`win32`), and uses an unprefixed one only when it is the release's *only* asset
-- a PartCAD release has dozens -- so the one platform-independent extension is
written three times, once under each prefix (`ARCHIVE_PLATFORMS`). The archives
hold the extension at their root, which is where Gemini CLI looks.

Usage:

    python3 ai-agents/scripts/gemini_extension.py OUT_DIR [--archives]
"""

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tarfile
import textwrap

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SKILLS_DIR = os.path.join(ROOT, "ai-agents", "common", "skills")
PLUGIN_MANIFEST = os.path.join(ROOT, "ai-agents", "claude", ".claude-plugin", "plugin.json")
AGENT_SKILLS = os.path.join(ROOT, "src", "partcad_utils", "agent_skills.py")

# The extension's name, which is also the directory Gemini CLI installs it into
# and the name `gemini extensions update` and `uninstall` take. Lowercase and
# dashes only.
NAME = "partcad"

# The platforms Gemini CLI names a release asset after (Node's `os.platform()`).
ARCHIVE_PLATFORMS = ("linux", "darwin", "win32")

# What an extension archive holds, out of OUT_DIR -- which is also the Claude
# marketplace, none of which belongs in it.
EXTENSION_FILES = ("gemini-extension.json", "GEMINI.md", "skills")

# What Gemini CLI reads into every session the extension is enabled in. Short,
# because it is in every session: what PartCAD is, how to run it so its output
# can be read, and that the skills exist. The skills say the rest.
CONTEXT = """# PartCAD

[PartCAD](https://partcad.org) documents manufacturable products as code. A package is a directory with a
`partcad.yaml` that declares parts, sketches, assemblies, scenes and interfaces, each made by a script
(build123d, CadQuery, OpenSCAD, ...) or read from a file (STEP, STL, ...). Objects are named
`//package/path:name`.

- This extension needs PartCAD's command line tool, `pc`, on `PATH`. Where it is missing, follow the `pc-setup`
  skill to install it.
- Drive PartCAD with the `partcad` MCP server this extension starts (`pc mcp`), or with `pc` in a shell: run it
  as `pc --no-ansi <command>` and capture both streams (`2>&1`), or its progress bars corrupt the output.
- Check every change: `pc qual test <object>` proves an object builds and meets its declared requirements, not
  that it is the shape that was asked for -- render it from more than one angle and look.
{issues}
- Before generating, validating, rendering, exporting or converting, follow PartCAD's skill for that kind of
  work. `/pc:<skill>` and `pc-<skill>` name the same skill. The skills are:

{skills}
"""


def _load_agent_skills():
    spec = importlib.util.spec_from_file_location("partcad_agent_skills", AGENT_SKILLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _version() -> str:
    with open(PLUGIN_MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)["version"]


def manifest(version: str) -> dict:
    """`gemini-extension.json`.

    The server is `pc mcp` for the workspace Gemini CLI is working in:
    `${workspacePath}` is the variable an extension's configuration has for it.
    """
    return {
        "name": NAME,
        "version": version,
        "description": "Mechanical and robotics engineering with PartCAD: the skills, and the MCP server (pc mcp)",
        "contextFileName": "GEMINI.md",
        "mcpServers": {"partcad": {"command": "pc", "args": ["-p", "${workspacePath}", "mcp"]}},
    }


def write(out_dir: str) -> list:
    """Write the extension into `out_dir`, and return the names of the skills it carries."""
    agent_skills = _load_agent_skills()
    version = _version()
    skills = agent_skills.available_skills(SKILLS_DIR)
    if not skills:
        raise SystemExit("ERROR: no skills under %s" % SKILLS_DIR)

    target = os.path.join(out_dir, "skills")
    shutil.rmtree(target, ignore_errors=True)
    names = []
    for skill in skills:
        name = agent_skills.PREFIX + skill
        # Gemini CLI, like the other agents that read `SKILL.md` folders, takes
        # lowercase letters, digits and single hyphens, and drops a skill whose
        # name is anything else without a word.
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
            raise SystemExit("ERROR: '%s' is not a name Gemini CLI accepts" % name)
        shutil.copytree(os.path.join(SKILLS_DIR, skill), os.path.join(target, name))
        text = agent_skills.read_skill(skill, SKILLS_DIR)
        with open(os.path.join(target, name, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(agent_skills.rename_skill(text, name, skills, version))
        names.append(name)

    with open(os.path.join(out_dir, "gemini-extension.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest(version), f, indent=2)
        f.write("\n")
    with open(os.path.join(out_dir, "GEMINI.md"), "w", encoding="utf-8", newline="\n") as f:
        issues = textwrap.fill(
            agent_skills.issues_instruction(),
            width=114,
            initial_indent="- ",
            subsequent_indent="  ",
            break_on_hyphens=False,
        )
        f.write(CONTEXT.format(issues=issues, skills="\n".join("  - `%s`" % name for name in names)))
    return names


def archive_name(platform: str, version: str) -> str:
    return "%s.%s-gemini-extension-%s.tar.gz" % (platform, NAME, version)


def write_archives(out_dir: str) -> list:
    """Write the extension in `out_dir` as one `.tar.gz` per platform prefix, beside it. Returns their paths.

    Built in memory once and written three times, so the three are the same
    bytes; every entry is stamped with the same time and owner, so a rebuild of
    one tree is the same archive.
    """
    version = _version()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:

        def normalized(info):
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            return info

        for name in EXTENSION_FILES:
            tar.add(os.path.join(out_dir, name), arcname=name, filter=normalized)
    paths = []
    for platform in ARCHIVE_PLATFORMS:
        path = os.path.join(out_dir, archive_name(platform, version))
        with open(path, "wb") as f:
            f.write(buffer.getvalue())
        paths.append(path)
    return paths


def main(argv: list) -> int:
    args = [arg for arg in argv[1:] if arg != "--archives"]
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    os.makedirs(args[0], exist_ok=True)
    names = write(args[0])
    print("==> Wrote the Gemini CLI extension '%s' (%d skills) into %s" % (NAME, len(names), args[0]))
    if "--archives" in argv[1:]:
        for path in write_archives(args[0]):
            print("==> Wrote the Gemini CLI extension archive: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
