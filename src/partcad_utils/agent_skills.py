#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The AI agent skills PartCAD ships, read as text: where they are and what they say.

Two readers need this and they are on opposite sides of the import boundary.
`partcad.ai_agents` installs the skills into a repository, for `pc init`; and
`pc mcp` (`partcad_client.mcp_server`) serves the same skills as MCP prompts, as
resources and through a tool -- and a client must stay cheap to import, so it
may not import `partcad` to find them. So the rule for what a skill is called
once it has left its plugin namespace, and how a copy says which PartCAD wrote
it, is here, once: a copy per reader is a copy whose renaming disagrees with the
other's, and then a cross-reference in one of them names a skill that does not
exist.

Nothing here imports `partcad`. The skills are package data of `partcad`
(`partcad/ai_agents/skills`, through a symlink into `ai-agents/common/skills` in
a checkout), and that directory is found beside this package rather than by
importing that one: `partcad` and `partcad_utils` are siblings in a checkout's
`src`, in `site-packages`, and in a frozen bundle alike.
"""

import os
import re
from typing import Optional

# Where the skills are: `partcad/ai_agents/skills`, next to this package.
SKILLS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "partcad", "ai_agents", "skills")
)

# What a skill of ours is called where there is no plugin to namespace it. The
# prefix is the Claude plugin's name because they are the same skill: `/pc:init`
# in Claude Code is `pc-init` everywhere else -- in Cursor's skills directory,
# in GitHub Copilot's, in Codex's, and as an MCP prompt.
PREFIX = "pc-"

ISSUES_TEXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_issues.md")


def issues_instruction() -> str:
    """What every agent is told about PartCAD's own defects, as one line."""
    with open(ISSUES_TEXT, "r", encoding="utf-8") as f:
        return " ".join(f.read().split())


# The front matter key a copy of a skill is stamped with, under `metadata:`.
# Two things depend on it and neither has another way to know: which PartCAD
# wrote the copy (so `pc healthcheck` can say it is stale), and that PartCAD
# wrote it at all (so `pc init` may retire it when the skill behind it is gone).
# The value is always `__version__`, read at install time -- never a literal; see
# the note on this in `partcad.ai_agents`.
STAMP_KEY = "partcad"
STAMP_SECTION = "metadata"


def available_skills(skills_dir: str = SKILLS_DIR) -> list[str]:
    """Every skill shipped, by directory name -- which is also its name."""
    if not os.path.isdir(skills_dir):
        return []
    return sorted(name for name in os.listdir(skills_dir) if os.path.isfile(os.path.join(skills_dir, name, "SKILL.md")))


def front_matter_bounds(text: str) -> Optional[tuple[int, int]]:
    """The offsets of the YAML front matter body, or None if there is none.

    Front matter is the block between the first two `---` lines, and it has to
    start at the very beginning of the file -- a `---` further down is a
    horizontal rule.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return 4, end + 1


def front_matter(text: str) -> dict:
    """The front matter of a skill, parsed; an empty mapping when it has none or it is not YAML."""
    # Imported here: `ai-agents/scripts` reads the skills with nothing but this
    # module on a bare runner, and renaming one needs no parser.
    import yaml

    bounds = front_matter_bounds(text)
    if bounds is None:
        return {}
    try:
        parsed = yaml.safe_load(text[bounds[0] : bounds[1]])
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def body(text: str) -> str:
    """A skill without its front matter: the instructions an agent follows."""
    bounds = front_matter_bounds(text)
    if bounds is None:
        return text
    # Past the closing `---` and the line break after it.
    return text[bounds[1] + 3 :].lstrip("\n")


def _stamp(front_matter_text: str, version: str) -> str:
    """Return `front_matter_text` carrying `metadata.partcad: <version>`.

    Inserted as text rather than by parsing and re-dumping the YAML: a round
    trip through a parser reflows the long `description:` line every skill has
    and reorders the keys, so every install would rewrite files it did not
    change. An existing `metadata:` block is added to rather than replaced --
    the skills in this repository have none, but an author's may.
    """
    line = "%s: %s" % (STAMP_KEY, version)

    section = re.search(r"^%s:[ \t]*$" % re.escape(STAMP_SECTION), front_matter_text, re.MULTILINE)
    if section is None:
        separator = "" if front_matter_text.endswith("\n") else "\n"
        return front_matter_text + separator + "%s:\n  %s\n" % (STAMP_SECTION, line)

    rest = front_matter_text[section.end() :]
    # The indentation the block already uses, so that this belongs to it.
    nested = re.match(r"\n([ \t]+)\S", rest)
    indent = nested.group(1) if nested else "  "

    existing = re.search(r"^%s%s:[ \t]*.*$" % (re.escape(indent), re.escape(STAMP_KEY)), rest, re.MULTILINE)
    if existing is not None:
        start = section.end() + existing.start()
        end = section.end() + existing.end()
        return front_matter_text[:start] + indent + line + front_matter_text[end:]

    return front_matter_text[: section.end()] + "\n" + indent + line + front_matter_text[section.end() :]


def stamped_version(text: str) -> Optional[str]:
    """The PartCAD version that wrote this skill, or None if nothing did.

    None is the answer for a skill a user wrote themselves *and* for one an
    older PartCAD installed before it stamped anything. Both are left alone by
    everything that reads this, which is the safe direction: the cost is a
    retired skill lingering for somebody who has not reinstalled since, and the
    alternative is deleting a file PartCAD may not have written.
    """
    # The field itself, parsed: a line reading `partcad: ...` can be anywhere
    # in front matter -- inside a block-scalar `description:`, for one -- and a
    # skill mistaken for PartCAD's is one `pc init` may delete.
    section = front_matter(text).get(STAMP_SECTION)
    if not isinstance(section, dict) or section.get(STAMP_KEY) is None:
        return None
    return str(section[STAMP_KEY])


def rename_references(text: str, skills: list[str]) -> str:
    """Return `text` with every `pc:<skill>` spelled `pc-<skill>`.

    `/pc:setup` in prose and `# pc:init` as a title name a skill through the
    Claude plugin's namespace, which exists nowhere else. Only the names in
    `skills` are rewritten, so a `pc:` that is something else, and the
    `pc render` and `pc adhoc convert` command lines that fill these files, are
    left alone.
    """
    if not skills:
        return text
    return re.sub(
        r"\bpc:(%s)\b" % "|".join(re.escape(skill) for skill in sorted(skills, key=len, reverse=True)),
        lambda match: PREFIX + match.group(1),
        text,
    )


def rename_skill(text: str, name: str, skills: list[str], version: Optional[str] = None) -> str:
    """Return `text` as the skill `name`, for an agent with no plugin namespace.

    Three things change, and only these three. The `name` in the front matter,
    which has to match the directory the skill is installed in or it answers to
    a command nobody typed. Every `pc:<skill>` in the text (`rename_references`).
    And the stamp, which says which PartCAD wrote the file and marks it as
    PartCAD's to replace or retire.
    """
    bounds = front_matter_bounds(text)
    if bounds is not None:
        start, end = bounds
        front_matter_text = re.sub(
            r"^name:[ \t]*\S.*$",
            "name: %s" % name,
            text[start:end],
            count=1,
            flags=re.MULTILINE,
        )
        if version is not None:
            front_matter_text = _stamp(front_matter_text, version)
        text = text[:start] + front_matter_text + text[end:]

    return rename_references(text, skills)


def read_skill(skill: str, skills_dir: str = SKILLS_DIR) -> str:
    """The `SKILL.md` of `skill`, as shipped."""
    with open(os.path.join(skills_dir, skill, "SKILL.md"), "r", encoding="utf-8") as f:
        return f.read()


def summary(description: str) -> str:
    """What a skill does, in one clause: its `description` up to the first break in it.

    A description says what the skill does and then how and when to use it, and
    the first is all a list of skills has room for. It ends at the end of the
    first sentence ('. ', not the '.' in 'measure.py') or at the first dash that
    starts an aside, whichever comes first -- and never inside a parenthesis,
    which is cut off before it opens instead.
    """
    description = " ".join(str(description or "").split())
    ends = [
        found for found in (description.find(". "), description.find(" - "), description.find(" — ")) if found != -1
    ]
    clause = description[: min(ends)] if ends else description
    if clause.count("(") > clause.count(")"):
        clause = clause[: clause.rfind(" (")]
    # And a list it cut short does not end on its conjunction.
    clause = re.sub(r",?\s+(and|or)$", "", clause)
    return clause.rstrip(".,;: ") + "."
