#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The skills as text: where `partcad_utils.agent_skills` finds them, and what it makes of them.

Its two readers are on either side of the import boundary -- `partcad.ai_agents`
installing them for `pc init`, and `pc mcp` serving them -- so what is checked
first is that they read the same directory, and that this module can be used
without importing `partcad` at all.
"""

import os
import subprocess
import sys

import pytest

from partcad_utils import agent_skills


def test_it_finds_the_skills_partcad_installs():
    import partcad.ai_agents as ai_agents

    assert os.path.realpath(agent_skills.SKILLS_DIR) == os.path.realpath(ai_agents.SKILLS_DIR)
    assert agent_skills.available_skills() == ai_agents.available_skills()
    assert "gen-part" in agent_skills.available_skills()


def test_reading_the_skills_does_not_import_partcad():
    """`pc mcp` is a client, and a client must stay cheap to import."""
    code = (
        "import sys\n"
        "from partcad_utils import agent_skills\n"
        "skills = agent_skills.available_skills()\n"
        "agent_skills.front_matter(agent_skills.read_skill(skills[0]))\n"
        "assert skills and 'partcad' not in sys.modules, sorted(m for m in sys.modules if m.startswith('partcad'))\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_body_is_what_follows_the_front_matter():
    assert agent_skills.body("---\nname: x\n---\n\n# Title\n") == "# Title\n"
    assert agent_skills.body("# No front matter\n") == "# No front matter\n"


def test_references_into_the_plugin_namespace_are_renamed_and_nothing_else():
    text = "Run /pc:gen-sketch first, then `pc render` and pc:unknown."
    assert agent_skills.rename_references(text, ["gen-sketch", "gen"]) == (
        "Run /pc-gen-sketch first, then `pc render` and pc:unknown."
    )


@pytest.mark.parametrize(
    "description, expected",
    [
        ("Do a thing. Use it when asked.", "Do a thing."),
        ("Convert a file - STEP, STL - with pc convert", "Convert a file."),
        ("Make a scene (a room - or a world) from text", "Make a scene."),
        ("Read it from renders, and (for a part - one solid) a drawing", "Read it from renders."),
        ("Runs measure.py on it", "Runs measure.py on it."),
    ],
)
def test_a_summary_is_the_first_clause(description, expected):
    assert agent_skills.summary(description) == expected


def test_every_shipped_skill_has_a_summary_of_its_own():
    """`AGENTS.md` and the `skill` tool list the skills by it."""
    summaries = [
        agent_skills.summary(agent_skills.front_matter(agent_skills.read_skill(skill))["description"])
        for skill in agent_skills.available_skills()
    ]
    assert all(len(summary) > 20 for summary in summaries)
    assert len(set(summaries)) == len(summaries)
