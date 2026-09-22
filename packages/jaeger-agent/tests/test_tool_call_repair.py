"""Tests for tool_call_repair module."""

import json
import pytest

from jaeger_agent.parsing.tool_call_repair import repair_plain_text_tool_calls


def test_repair_xml_function_tags():
    raw = (
        "I'll run that command for you.\n"
        "<function=bash><parameter=command>ls -la</parameter></function>\n"
        "Let me know if you need more."
    )
    tool_calls, cleaned = repair_plain_text_tool_calls(raw)
    assert len(tool_calls) == 1
    call = tool_calls[0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "bash"
    args = json.loads(call["function"]["arguments"])
    assert args == {"command": "ls -la"}
    assert "<function=bash>" not in cleaned
    assert "I'll run that command for you." in cleaned
    assert "Let me know if you need more." in cleaned


def test_repair_tool_call_tags_json():
    raw = (
        "Let me check the files:\n"
        "<tool_call>\n"
        '{"name": "read_file", "arguments": {"path": "/workspace/main.py"}}\n'
        "</tool_call>"
    )
    tool_calls, cleaned = repair_plain_text_tool_calls(raw)
    assert len(tool_calls) == 1
    call = tool_calls[0]
    assert call["function"]["name"] == "read_file"
    args = json.loads(call["function"]["arguments"])
    assert args == {"path": "/workspace/main.py"}
    assert "<tool_call>" not in cleaned
    assert "Let me check the files:" in cleaned


def test_repair_markdown_json_block():
    raw = (
        "Searching for the symbol:\n"
        "```json\n"
        '{\n  "name": "grep_search",\n  "arguments": {\n    "pattern": "def main"\n  }\n}\n'
        "```"
    )
    tool_calls, cleaned = repair_plain_text_tool_calls(raw)
    assert len(tool_calls) == 1
    call = tool_calls[0]
    assert call["function"]["name"] == "grep_search"
    args = json.loads(call["function"]["arguments"])
    assert args == {"pattern": "def main"}
    assert "```json" not in cleaned
    assert "Searching for the symbol:" in cleaned


def test_repair_bracket_tool_call():
    raw = (
        "Fetching data: [call: fetch_url(url=\"https://api.github.com\")]"
    )
    tool_calls, cleaned = repair_plain_text_tool_calls(raw)
    assert len(tool_calls) == 1
    call = tool_calls[0]
    assert call["function"]["name"] == "fetch_url"
    args = json.loads(call["function"]["arguments"])
    assert args == {"url": "https://api.github.com"}
    assert "[call:" not in cleaned


def test_repair_json_trailing_commas_and_single_quotes():
    raw = (
        "<tool_call>\n"
        "{'name': 'write_file', 'arguments': {'path': 'test.txt', 'content': 'hello',}}\n"
        "</tool_call>"
    )
    tool_calls, cleaned = repair_plain_text_tool_calls(raw)
    assert len(tool_calls) == 1
    call = tool_calls[0]
    assert call["function"]["name"] == "write_file"
    args = json.loads(call["function"]["arguments"])
    assert args == {"path": "test.txt", "content": "hello"}


def test_repair_allowed_tool_names_filter():
    raw = (
        "<tool_call>\n"
        '{"name": "malicious_tool", "arguments": {"cmd": "rm -rf /"}}\n'
        "</tool_call>"
    )
    tool_calls, cleaned = repair_plain_text_tool_calls(raw, allowed_tool_names={"read_file", "write_file"})
    assert len(tool_calls) == 0
    assert cleaned == raw


def test_no_tool_call_plain_text():
    raw = "Just a friendly message without any tool calls at all."
    tool_calls, cleaned = repair_plain_text_tool_calls(raw)
    assert len(tool_calls) == 0
    assert cleaned == raw
