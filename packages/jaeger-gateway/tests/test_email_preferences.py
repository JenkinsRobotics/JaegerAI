"""Run and task notifications must survive a restart and enqueue only once."""
from jaeger_channels import ChannelHub
from jaeger_gateway.store import GatewayStore


def test_completion_subscriptions_are_opt_in_and_idempotent(tmp_path):
    store = GatewayStore(tmp_path / "gateway.sqlite")
    channels = ChannelHub(tmp_path)
    sid = store.main_chat_session()["session_id"]
    store.admit_request(sid, "fixture", request_id="before")
    store.settle_request("before", "completed", {})
    store.stage_notification_emails(channels)
    assert not channels.list_outbox()

    store.save_email_preferences("owner@example.invalid", True, True)
    store.admit_request(sid, "fixture", request_id="after")
    store.settle_request("after", "completed", {})
    store.settle_request("after", "completed", {})
    job = store.create_scheduled_job(session_id=sid, prompt="fixture", due_at=1)
    assert store.claim_due_job()["job_id"] == job["job_id"]
    store.settle_scheduled_job(job["job_id"], status="done", result={})

    reopened = GatewayStore(tmp_path / "gateway.sqlite")
    # Simulate a crash after committing to the outbox but before removing the event.
    channels.stage_notification("run:after", "owner@example.invalid", "Jaeger finished a response.")
    reopened.stage_notification_emails(channels)
    assert len(channels.list_outbox()) == 2
    assert all(message.status == "queued_for_approval" for message in channels.list_outbox())
