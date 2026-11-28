"""Tests for deterministic DataSensitivity & Cloud Egress privacy classifier."""

from __future__ import annotations

from jaeger_authority import (
    DataSensitivity,
    classify_sensitivity,
    evaluate_cloud_egress,
    filter_items_for_egress,
)


def test_classify_sensitivity_and_cloud_egress() -> None:
    assert classify_sensitivity("Hello world", {"source": "public"}) == DataSensitivity.PUBLIC
    assert classify_sensitivity("My bank account number is 12345") == DataSensitivity.SENSITIVE
    assert classify_sensitivity("Here is my api_key=sk-abc12345") == DataSensitivity.SECRET

    # Financial/secret content blocked from cloud by default
    dec_fin = evaluate_cloud_egress("Please review my tax return and mortgage")
    assert dec_fin.cloud_allowed is False and dec_fin.sensitivity == DataSensitivity.SENSITIVE

    dec_sec = evaluate_cloud_egress("token: ghp_supersecret12345")
    assert dec_sec.cloud_allowed is False and dec_sec.sensitivity == DataSensitivity.SECRET

    # Normal coding/project text allowed unless local_only_mode is forced
    dec_ok = evaluate_cloud_egress("Refactor the React Virtual Office canvas")
    assert dec_ok.cloud_allowed is True

    dec_local = evaluate_cloud_egress("Refactor the React Virtual Office canvas", local_only_mode=True)
    assert dec_local.cloud_allowed is False


def test_filter_items_for_egress_produces_redacted_manifest() -> None:
    items = [
        {"content": "Build a wooden shelter in Minecraft"},
        {"content": "Patient diagnosis and prescription details"},
        {"content": "private_key = -----BEGIN RSA PRIVATE KEY-----"},
    ]
    kept, blocked = filter_items_for_egress(items)
    assert len(kept) == 1 and "Minecraft" in kept[0]["content"]
    assert len(blocked) == 2
    assert {b["sensitivity"] for b in blocked} == {"sensitive", "secret"}
