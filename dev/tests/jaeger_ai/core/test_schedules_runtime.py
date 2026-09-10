"""JaegerAI schedule helpers map to the ARES WebUI job panel."""

from jaeger_ai.core.runtime.schedules import cancel_job, create_job, list_jobs


def test_list_jobs_returns_count_and_schedules():
    payload = list_jobs()
    assert "count" in payload
    assert isinstance(payload["schedules"], list)
    assert payload["count"] == len(payload["schedules"])


def test_control_plane_schedule_mutations_use_memory_without_tool_approval(monkeypatch):
    from jaeger_agent.memory import memory

    calls = []
    monkeypatch.setattr(
        memory,
        "add_schedule",
        lambda **kwargs: calls.append(("add", kwargs)) or {
            "name": kwargs["name"],
            "cron": kwargs["cron_expr"],
            "prompt": kwargs["prompt"],
        },
    )
    monkeypatch.setattr(
        memory,
        "cancel_schedule",
        lambda name: calls.append(("cancel", name)) or True,
    )

    created = create_job(
        prompt="Brief me",
        schedule="0 9 * * *",
        name="morning",
    )
    cancelled = cancel_job("morning")

    assert created["scheduled"] is True
    assert cancelled == {"cancelled": True, "name": "morning"}
    assert calls == [
        ("add", {
            "cron_expr": "0 9 * * *",
            "prompt": "Brief me",
            "name": "morning",
            "at": None,
        }),
        ("cancel", "morning"),
    ]
