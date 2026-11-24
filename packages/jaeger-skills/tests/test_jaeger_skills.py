from __future__ import annotations

import pytest
from jaeger_skills import SkillSummary, SkillValidationError, clean_skill_name, parse_frontmatter, rank_skills, validate_skill_markdown


def test_validate_and_rank_skills():
    assert clean_skill_name("My Skill") == "my-skill"
    md = "---\nname: my-skill\ndescription: Organize Apple Mail inboxes safely\n---\n\n# Steps\n"
    assert parse_frontmatter(md)["name"] == "my-skill"
    assert validate_skill_markdown("my-skill", md).endswith("\n")
    with pytest.raises(SkillValidationError):
        validate_skill_markdown("other", md)

    ranked = rank_skills("clean apple mail inbox", [
        SkillSummary("docker-ops", "Manage containers"),
        SkillSummary("macos-mail-organizer", "Organize Apple Mail inboxes"),
    ])
    assert ranked[0].name == "macos-mail-organizer"
