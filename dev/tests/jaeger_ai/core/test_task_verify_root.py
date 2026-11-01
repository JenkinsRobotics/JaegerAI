"""J-087: tasks admitted without a workspace verify receipts against the instance workspace."""
import hashlib, time
from types import SimpleNamespace
from jaeger_ai.core.tasks.owner import GatewayTaskOwner


def _task(workspace, created):
    return SimpleNamespace(payload={"execution": {"workspace": workspace}, "artifacts": []}, created_at=created, goal="reply DONE")


def test_empty_workspace_uses_instance_workspace(tmp_path, monkeypatch):
    inst = tmp_path / "inst"; (inst / "workspace").mkdir(parents=True)
    monkeypatch.setattr("jaeger_ai.core.instance.instance.resolve_instance_dir", lambda name=None: inst)
    t0 = time.time() - 5
    f = inst / "workspace" / "done.txt"; f.write_text("DONE")
    rec = {"kind": "file_sha256", "path": str(f), "sha256": hashlib.sha256(b"DONE").hexdigest()}
    ok, receipts = GatewayTaskOwner.verify(_task("", t0), {"task_completion": {"ok": True, "verification_receipts": [rec]}})
    assert ok is True and receipts == [rec]


def test_outside_instance_workspace_still_rejected(tmp_path, monkeypatch):
    inst = tmp_path / "inst"; (inst / "workspace").mkdir(parents=True)
    monkeypatch.setattr("jaeger_ai.core.instance.instance.resolve_instance_dir", lambda name=None: inst)
    f = tmp_path / "elsewhere.txt"; f.write_text("x")
    rec = {"kind": "file_sha256", "path": str(f), "sha256": hashlib.sha256(b"x").hexdigest()}
    ok, msg = GatewayTaskOwner.verify(_task("", time.time() - 5), {"task_completion": {"ok": True, "verification_receipts": [rec]}})
    assert ok is False and "outside workspace" in msg
