"""Tests for tool call repair middleware."""
from jaeger_ai.core.runtime.tool_repair import (
    repair_json_string,
    safe_parse_tool_arguments,
    extract_xml_tool_call,
    repair_tool_call,
)


def test_repair_clean_json():
    clean = '{"path": "foo/bar.txt", "content": "hello"}'
    assert safe_parse_tool_arguments(clean) == {"path": "foo/bar.txt", "content": "hello"}


def test_repair_markdown_fences():
    fenced = """```json
    {
        "query": "search term"
    }
    ```"""
    parsed = safe_parse_tool_arguments(fenced)
    assert parsed == {"query": "search term"}


def test_repair_single_quotes_and_trailing_commas():
    malformed = "{'file_path': 'test.py', 'mode': 'write',}"
    parsed = safe_parse_tool_arguments(malformed)
    assert parsed["file_path"] == "test.py"
    assert parsed["mode"] == "write"


def test_repair_python_literals():
    pythonic = '{"enabled": True, "dry_run": False, "backup": None}'
    parsed = safe_parse_tool_arguments(pythonic)
    assert parsed["enabled"] is True
    assert parsed["dry_run"] is False
    assert parsed["backup"] is None


def test_repair_truncated_json():
    truncated = '{"goal": "run audit", "params": {"recursive": true'
    parsed = safe_parse_tool_arguments(truncated)
    assert parsed["goal"] == "run audit"
    assert parsed["params"]["recursive"] is True


def test_extract_xml_tool_call():
    xml_call = '<tool_call name="read_file">{"path": "/tmp/log.txt"}</tool_call>'
    result = extract_xml_tool_call(xml_call)
    assert result is not None
    name, args = result
    assert name == "read_file"
    assert args == {"path": "/tmp/log.txt"}


def test_repair_tool_call_aliases():
    name, args = repair_tool_call(
        "functions.write_file",
        "{'path': 'notes.md', 'data': 'contents'}",
        parameter_aliases={"path": "file_path", "data": "content"},
    )
    assert name == "write_file"
    assert args == {"file_path": "notes.md", "content": "contents"}
