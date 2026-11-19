from types import SimpleNamespace

from jaeger_agent.skill_registry.tool_selection import ToolSelection, budget_visible_tools


class _Tool:
    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size

    def to_openai_schema(self):
        return {"name": self.name, "description": "x" * self.size}


class _Guard:
    budget = SimpleNamespace(prompt_budget=7936)

    @staticmethod
    def estimate_text_tokens(value: str) -> int:
        return len(value) // 4


def test_intent_tool_fits_when_core_catalog_exceeds_remaining_prompt_budget():
    tools = [
        _Tool("session_search", 800),
        _Tool("tool_search", 800),
        *[_Tool(name, 1600) for name in ("read_file", "write_file", "terminal", "web_search")],
    ]
    selection = ToolSelection(scoped=True, inferred={"session_search"})

    visible = budget_visible_tools(tools, selection, _Guard(), "s" * 20_000, "count chat sessions")

    assert "session_search" in {tool.name for tool in visible}
    cost = sum(_Guard.estimate_text_tokens(__import__('json').dumps(tool.to_openai_schema())) + 2 for tool in visible)
    assert cost <= 1400
