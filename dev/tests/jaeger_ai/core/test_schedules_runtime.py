"""JaegerAI schedule helpers map to the ARES WebUI job panel."""

from jaeger_ai.core.runtime.schedules import list_jobs


def test_list_jobs_returns_count_and_schedules():
    payload = list_jobs()
    assert "count" in payload
    assert isinstance(payload["schedules"], list)
    assert payload["count"] == len(payload["schedules"])
