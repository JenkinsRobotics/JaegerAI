from pathlib import Path
from types import SimpleNamespace

from api import route_checkpoints


def test_list_uses_session_workspace_and_strips_store_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(route_checkpoints, "_git_session_workspace", lambda handler, sid: Path("/safe/ws") if sid == "one" else None)
    def list_result(workspace, **options):
        seen.update(workspace=workspace, options=options)
        return {"checkpoints": [{"id": "abc", "message": "Saved", "date": "now", "date_display": "Today", "files": 2, "path": "/private/store"}]}
    monkeypatch.setattr(route_checkpoints, "list_checkpoints", list_result)
    monkeypatch.setattr(route_checkpoints, "get_checkpoint_diff", lambda *args, **kwargs: {"total_changes": 1})
    monkeypatch.setattr(route_checkpoints, "j", lambda handler, payload: payload)
    result = route_checkpoints.handle_checkpoints_get(None, SimpleNamespace(path="/api/checkpoints/list", query="session_id=one&workspace=/evil"))
    assert seen == {"workspace": "/safe/ws", "options": {"trusted_workspace": True}}
    assert result["checkpoints"] == [{"id": "abc", "message": "Saved", "date": "now", "date_display": "Today", "files": 2, "files_changed": 1}]


def test_diff_uses_session_workspace_and_checkpoint(monkeypatch):
    monkeypatch.setattr(route_checkpoints, "_git_session_workspace", lambda handler, sid: Path("/safe/ws"))
    monkeypatch.setattr(route_checkpoints, "get_checkpoint_diff", lambda workspace, checkpoint, **options: {"workspace": workspace, "checkpoint": checkpoint, "options": options})
    monkeypatch.setattr(route_checkpoints, "j", lambda handler, payload: payload)
    result = route_checkpoints.handle_checkpoints_get(None, SimpleNamespace(path="/api/checkpoints/diff", query="session_id=one&checkpoint=abc&workspace=/evil"))
    assert result == {"workspace": "/safe/ws", "checkpoint": "abc", "options": {"trusted_workspace": True}}


def test_missing_checkpoint_rejected(monkeypatch):
    monkeypatch.setattr(route_checkpoints, "_git_session_workspace", lambda handler, sid: Path("/safe/ws"))
    monkeypatch.setattr(route_checkpoints, "bad", lambda handler, message: message)
    assert route_checkpoints.handle_checkpoints_get(None, SimpleNamespace(path="/api/checkpoints/diff", query="session_id=one")) == "checkpoint required"
