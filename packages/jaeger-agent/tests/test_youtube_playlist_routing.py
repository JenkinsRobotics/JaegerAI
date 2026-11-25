from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from jaeger_agent.skill_registry.tool_selection import ToolSelection
from jaeger_agent.tools import media_studio
from jaeger_agent.tools.youtube_playlist import list_playlist_api, mentions_youtube_playlist

LID = "PL_Test_123456789"
URL = f"https://www.youtube.com/playlist?list={LID}"


def test_playlist_link_match_is_limited_to_youtube():
    assert mentions_youtube_playlist(f"Read [this]({URL}).")
    assert not mentions_youtube_playlist(f"https://www.youtube.com.example/playlist?list={LID}")
    assert not mentions_youtube_playlist("https://www.youtube.com/watch?v=01234567890")


def test_playlist_listing_preserves_total_and_excludes_unavailable_items():
    def fetch(url):
        parsed = urlsplit(url)
        assert parsed.hostname == "www.googleapis.com"
        assert parse_qs(parsed.query)["key"] == ["test-key"]
        page = parsed.path.rsplit("/", 1)[-1]
        if page == "playlists":
            return {"items": [{"snippet": {"title": "Demo"}, "contentDetails": {"itemCount": 2863}}]}
        if page == "playlistItems":
            return {"items": [
                {"snippet": {"title": "Private video"}, "status": {"privacyStatus": "private"}},
                {"snippet": {"title": "Sample"}, "contentDetails": {"videoId": "01234567890"}},
            ]}
        return {"items": [{"id": "01234567890", "contentDetails": {"duration": "PT5M"}}]}

    result = list_playlist_api(LID, 1, "test-key", fetch)
    assert result["item_count"] == 2863
    assert [x["duration"] for x in result["entries"]] == [300]


def test_chat_tool_reuses_connector_and_does_not_leak_failed_request_url(monkeypatch):
    monkeypatch.setattr(media_studio, "read_api_key", lambda _root: "private-fixture-key")

    def listing(lid, limit, key, _fetch):
        assert (lid, limit, key) == (LID, 50, "private-fixture-key")
        return {"entries": [{"id": "01234567890"}], "item_count": 2863}

    monkeypatch.setattr(media_studio, "list_playlist_api", listing)
    result = media_studio.youtube_studio("playlist", url_or_id=URL, limit=200)
    assert result["ok"] and result["listed_count"] == 1 and result["item_count"] == 2863

    def denied(*_args):
        raise HTTPError("https://example.test/?key=private-fixture-key", 403, "Forbidden", {}, None)

    monkeypatch.setattr(media_studio, "list_playlist_api", denied)
    result = media_studio.youtube_studio("playlist", url_or_id=URL, limit=200)
    assert result["http_status"] == 403
    assert "private-fixture-key" not in str(result)


def test_only_matches_registered_tool_for_the_current_authorized_turn(monkeypatch):
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    from jaeger_agent.skill_registry import toolset_scoping

    agent = SimpleNamespace(_tools_filter_locked=False, _tool_selection=ToolSelection(),
                            _all_tools=[SimpleNamespace(name="youtube_studio")])
    route = JaegerAgent._select_playlist_tool
    route(agent, URL)
    assert agent._tool_selection.inferred == {"youtube_studio"}
    assert agent._tool_selection.reasons["youtube_studio"] == "YouTube playlist URL"
    route(agent, "Next question")
    assert not agent._tool_selection.inferred
    agent._tools_filter_locked = True
    route(agent, URL)
    assert not agent._tool_selection.inferred
    agent._tools_filter_locked = False
    monkeypatch.setattr(toolset_scoping, "is_untrusted_content", lambda: True)
    route(agent, URL)
    assert not agent._tool_selection.inferred
