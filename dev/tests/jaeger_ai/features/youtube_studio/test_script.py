from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from jaeger_ai.features.youtube_studio import script
from jaeger_ai.features.youtube_studio.channel_config import ChannelConfig, load_channel_config


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(captured: dict, content: str, finish: str = "stop"):
    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _Resp(json.dumps({"choices": [{"message": {"content": content},
                                              "finish_reason": finish}]}).encode())
    return opener


GOOD = """```markdown
# Ep 1
## Hook (0:00-0:30)
x
## Outline
1. a
## Shot list
| # | Shot | Source | Notes |
## Narration
HOST: Hello.
## Open questions for the operator
- ?
```"""


def test_settings_read_only_url_and_model(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("external_model:\n  base_url: http://h:1/v1\n  model: m:cloud\n  api_key: nope\n")
    assert script.load_model_settings(cfg) == script.ModelSettings("http://h:1/v1", "m:cloud")
    assert script.load_model_settings(tmp_path / "missing.yaml") == script.ModelSettings()


def test_channel_config_defaults_are_generic() -> None:
    """Default config has no personal references."""
    cfg = load_channel_config(Path("/nonexistent"))
    assert cfg.channel_name == "Your Channel Name"
    prompt = cfg.build_system_prompt()
    assert "ROBOT" in prompt
    assert "[TBD]" in prompt
    assert "never mention age" in prompt
    # No personal names in defaults
    assert "Matthew" not in prompt
    assert "Jenkins" not in prompt


def test_channel_config_custom_values() -> None:
    """Custom channel config generates custom prompt."""
    cfg = ChannelConfig(
        channel_name="My Build Channel",
        channel_description="a show about woodworking and robotics",
        host_description="an AI host that guides the build",
        robot_description="a sarcastic robot assistant",
    )
    prompt = cfg.build_system_prompt()
    assert "My Build Channel" in prompt
    assert "woodworking" in prompt
    assert "AI host that guides the build" in prompt
    assert "sarcastic robot assistant" in prompt


def test_prompt_keeps_show_off_personal_life() -> None:
    """Default prompt keeps personal life off the show."""
    messages = script.build_messages("brief text", ["log one"], "Episode 1")
    system = messages[0]["content"]
    assert "ROBOT" in system
    assert "never mention age" in system and "[TBD]" in system
    assert "log one" in messages[1]["content"] and "brief text" in messages[1]["content"]


def test_prompt_uses_custom_channel_config() -> None:
    """Custom channel config is used in generated messages."""
    cfg = ChannelConfig(channel_name="Test Channel", project_name="Test Project")
    messages = script.build_messages("brief", [], "Ep", channel_config=cfg)
    system = messages[0]["content"]
    assert "Test Channel" in system
    assert "Test Project" in system


def test_generate_script_writes_markdown_and_posts_to_configured_model(tmp_path: Path) -> None:
    brief = tmp_path / "brief.md"
    brief.write_text("Hab-1 brief")
    captured: dict = {}
    out = script.generate_script(
        brief, tmp_path / "ep1.md", episode="Ep 1",
        settings=script.ModelSettings("http://x:9/v1/", "glm-5.3-flash:cloud"),
        opener=_opener(captured, GOOD))
    text = out.read_text()
    assert captured["url"] == "http://x:9/v1/chat/completions"
    assert captured["body"]["model"] == "glm-5.3-flash:cloud"
    assert "```" not in text and "DRAFT" in text and "WARNING" not in text
    assert script.missing_sections(text) == []


def test_missing_sections_are_flagged(tmp_path: Path) -> None:
    brief = tmp_path / "b.md"
    brief.write_text("b")
    out = script.generate_script(brief, tmp_path / "o.md", episode="e",
                                 settings=script.ModelSettings(),
                                 opener=_opener({}, "# Title\n## Outline\n1. a"))
    assert "WARNING: missing sections: ## Hook, ## Shot list, ## Narration" in out.read_text()


def test_empty_reply_from_reasoning_model_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="raise --max-tokens"):
        script.chat(script.ModelSettings(), [], opener=_opener({}, "", "length"))


def test_reasoning_effort_sent_and_leaked_thinking_stripped() -> None:
    captured: dict = {}
    text = script.chat(script.ModelSettings(), [],
                       opener=_opener(captured, "I should reply.</think>READY"))
    assert text == "READY"
    assert captured["body"]["reasoning_effort"] == "low"
    script.chat(script.ModelSettings(), [], reasoning_effort=None,
                opener=_opener(captured, "ok"))
    assert "reasoning_effort" not in captured["body"]
