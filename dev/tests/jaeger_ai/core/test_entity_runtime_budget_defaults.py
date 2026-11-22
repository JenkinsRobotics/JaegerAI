import inspect

from jaeger_ai.core.entity.runtime import EntityRuntime


def test_owner_agent_defaults_match_framework_work_budget():
    parameters = inspect.signature(EntityRuntime.run_subordinate_react).parameters

    assert parameters["max_iterations"].default == 50
    assert parameters["max_tool_calls"].default == 24
