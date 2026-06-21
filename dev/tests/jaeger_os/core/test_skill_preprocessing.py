"""SKILL.md template-variable preprocessing (audit A6).

`core/skill_preprocessing.preprocess_skill` expands `{{var}}`
placeholders in a playbook body. Template variables only — inline shell
is deliberately not executed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from jaeger_os.agent.skill_registry.skill_preprocessing import preprocess_skill


def test_body_without_placeholders_is_unchanged():
    body = "Just plain instructions, no templating here."
    assert preprocess_skill(body) == body


def test_date_placeholder_is_expanded():
    out = preprocess_skill("Today is {{date}}.")
    assert re.search(r"Today is \d{4}-\d{2}-\d{2}\.", out), out
    assert "{{date}}" not in out


def test_skill_name_and_folder_are_expanded():
    out = preprocess_skill(
        "Skill {{skill_name}} lives at {{skill_folder}}.",
        skill_name="weather",
        skill_folder=Path("/inst/skills/weather"),
    )
    assert "Skill weather lives at /inst/skills/weather." == out


def test_os_placeholder_is_expanded():
    assert preprocess_skill("os={{os}}") == f"os={sys.platform}"


def test_whitespace_inside_braces_is_tolerated():
    out = preprocess_skill("at {{ skill_name }} now", skill_name="x")
    assert out == "at x now"


def test_unknown_placeholder_is_left_untouched():
    body = "this {{not_a_real_var}} stays"
    assert preprocess_skill(body) == body


def test_known_and_unknown_placeholders_mix():
    out = preprocess_skill(
        "{{skill_name}} / {{mystery}}", skill_name="alpha")
    assert out == "alpha / {{mystery}}"
