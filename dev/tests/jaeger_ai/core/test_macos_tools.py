import pytest
from unittest.mock import patch, MagicMock
from jaeger_ai.core.runtime.macos_tools import (
    macos_automation,
    apple_shortcuts,
    spotlight_search,
)


def test_spotlight_search_empty_query():
    res = spotlight_search("")
    assert res["success"] is False
    assert "empty" in res["error"]


@patch("subprocess.run")
def test_spotlight_search_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="/path/to/note1.md\n/path/to/note2.md\n")
    res = spotlight_search("note", limit=5)
    assert res["success"] is True
    assert res["total_matches"] == 2
    assert res["paths"] == ["/path/to/note1.md", "/path/to/note2.md"]


@patch("subprocess.run")
def test_apple_shortcuts_list(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="Take Screenshot\nLog Water\n")
    res = apple_shortcuts("list")
    assert res["success"] is True
    assert res["count"] == 2
    assert "Log Water" in res["shortcuts"]


@patch("subprocess.run")
def test_apple_shortcuts_run(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="Done")
    res = apple_shortcuts("run", name="Log Water")
    assert res["success"] is True
    assert res["output"] == "Done"


@patch("subprocess.run")
def test_macos_automation_notification(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    res = macos_automation("notification", title="Test Alert", message="Done")
    assert res["success"] is True
    assert res["target"] == "notification"


@patch("subprocess.run")
def test_macos_automation_music(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    res = macos_automation("music", action="play")
    assert res["success"] is True
    assert res["state"] == "playing"
