"""Unit tests for shared_memory.honcho_client."""

from __future__ import annotations

import json
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from jaeger_ai.features.shared_memory.honcho_client import HonchoClient


def test_honcho_client_serializes_empty_dict():
    client = HonchoClient(base_url="http://test-honcho:8088", workspace="test-ws")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # Calling with empty dict {}
        res = client._request("POST", "/test", {})
        assert res == {"status": "ok"}

        # Verify body passed to urllib.request.Request was b"{}" (not None)
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        assert isinstance(req, urllib.request.Request)
        assert req.data == b"{}"


def test_honcho_client_none_data():
    client = HonchoClient(base_url="http://test-honcho:8088", workspace="test-ws")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = client._request("GET", "/test")
        assert res == {"status": "ok"}

        args, kwargs = mock_urlopen.call_args
        req = args[0]
        assert req.data is None


def test_honcho_client_methods():
    client = HonchoClient(base_url="http://test-honcho:8088", workspace="test-ws")

    with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
        client.create_peer("hermes")
        mock_req.assert_called_with("POST", "/v3/workspaces/test-ws/peers", {"id": "hermes", "metadata": {}})

        client.get_peer_card("hermes")
        mock_req.assert_called_with("GET", "/v3/workspaces/test-ws/peers/hermes/card")

        client.search("test query", session_id="sess-1")
        mock_req.assert_called_with("POST", "/v3/workspaces/test-ws/sessions/sess-1/search", {"query": "test query"})
