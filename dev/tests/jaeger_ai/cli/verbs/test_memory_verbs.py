"""DB-10 — ``jaeger memory export`` / ``stats`` verbs.

The export bundle's primary consumer is the training-data pipeline:
it must dump every populated table in a portable shape (json/jsonl/
csv), redact secrets, and write a manifest. ``stats`` is the small
diagnostic verb for the daemon's --doctor view.
"""

from __future__ import annotations

import csv
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.memory import memory as mem
from jaeger_ai.core.memory import sqlite_store
from jaeger_ai.cli.verbs import memory_verbs


@pytest.fixture(autouse=True)
def _isolate_store():
    sqlite_store.close()
    yield
    sqlite_store.close()


@pytest.fixture
def live_instance(tmp_path, monkeypatch):
    """Build a populated instance + wire HOME so the resolver finds
    it. Populates each table with at least one row so the export
    verb has something to dump."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    inst = tmp_path / ".jaeger_os" / "instances" / "default"
    inst.mkdir(parents=True)
    (inst / "memory").mkdir()
    (inst / "logs").mkdir()
    (inst / "credentials").mkdir()
    (inst / "skills").mkdir()
    (inst / "workspace").mkdir()
    (inst / "run").mkdir()
    (inst / "home").mkdir()
    (inst / "identity.yaml").write_text(
        "name: Test\nrole: r\npersonality: p\n", encoding="utf-8",
    )
    (inst / "config.yaml").write_text(
        "instance_name: default\nmodel:\n  model_path: x\n  ctx: 32768\n",
        encoding="utf-8",
    )
    (inst / "manifest.json").write_text(
        '{"instance_name":"default","schema_version":"1.2.0"}', encoding="utf-8",
    )

    # Populate the SQL store with a sample row per table.
    layout = SimpleNamespace(
        memory_dir=inst / "memory",
        logs_dir=inst / "logs",
        audit_log_path=inst / "logs" / "audit.log",
    )
    mem.bind(layout)
    mem.remember("greeting", "hello world")
    mem.append_episodic({
        "user": "q", "decision_raw": "a",
        "answer": "a", "session_key": "default",
    })
    mem.add_schedule("* * * * *", "ping", name="every_min")
    mem.record_tool_call(
        session_key="default", tool_name="run_shell",
        args={"cmd": "ls"}, result={"ok": True, "stdout": "x\n"},
    )
    mem.record_audit_event(
        event="file_write", payload={"path": "foo.py", "bytes": 12},
    )
    sqlite_store.close()
    return inst


# ── dispatcher ───────────────────────────────────────────────────


def test_dispatcher_help_returns_zero(capsys):
    rc = memory_verbs._cmd_memory_argv(["-h"])
    assert rc == 0


def test_dispatcher_no_args_returns_two(capsys):
    rc = memory_verbs._cmd_memory_argv([])
    assert rc == 2


def test_dispatcher_unknown_verb_returns_two(capsys):
    rc = memory_verbs._cmd_memory_argv(["unknown"])
    err = capsys.readouterr().err
    assert "unknown verb" in err
    assert rc == 2


# ── export — JSON (default) ──────────────────────────────────────


def test_export_writes_manifest_and_all_default_tables(live_instance, tmp_path):
    out = tmp_path / "dump"
    rc = memory_verbs._cmd_memory_argv(["export", str(out)])
    assert rc == 0
    assert (out / "manifest.json").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "json"
    assert manifest["instance"] == "default"
    # Each default table got a file with at least one row.
    for tbl in ("facts", "episodic", "schedules", "tool_calls", "audit_log"):
        assert tbl in manifest["tables"]
        f = out / f"{tbl}.json"
        assert f.exists()
        decoded = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(decoded, list)
        assert len(decoded) >= 1, f"table {tbl} should have ≥1 row"


def test_export_json_decodes_args_and_result(live_instance, tmp_path):
    """The export pass decodes args_json / result_json so the
    consumer sees structured data."""
    out = tmp_path / "dump"
    memory_verbs._cmd_memory_argv(["export", str(out)])
    rows = json.loads((out / "tool_calls.json").read_text(encoding="utf-8"))
    assert rows[0]["args_json"] == {"cmd": "ls"}
    assert rows[0]["result_json"] == {"ok": True, "stdout": "x\n"}


def test_export_can_select_subset_of_tables(live_instance, tmp_path):
    out = tmp_path / "dump"
    rc = memory_verbs._cmd_memory_argv(
        ["export", str(out), "--tables", "facts,tool_calls"],
    )
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["tables"].keys()) == {"facts", "tool_calls"}
    # episodic.json must NOT be present.
    assert not (out / "episodic.json").exists()


def test_export_rejects_unknown_table(live_instance, tmp_path, capsys):
    out = tmp_path / "dump"
    rc = memory_verbs._cmd_memory_argv(
        ["export", str(out), "--tables", "facts,bogus"],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown table" in err.lower()


def test_export_creates_output_directory(live_instance, tmp_path):
    out = tmp_path / "dump" / "nested" / "deep"
    rc = memory_verbs._cmd_memory_argv(["export", str(out)])
    assert rc == 0
    assert out.is_dir()


def test_export_no_path_returns_two(live_instance, capsys):
    rc = memory_verbs._cmd_memory_argv(["export"])
    assert rc == 2


# ── export — JSONL ───────────────────────────────────────────────


def test_export_jsonl_format_writes_one_row_per_line(live_instance, tmp_path):
    out = tmp_path / "dump"
    rc = memory_verbs._cmd_memory_argv(
        ["export", str(out), "--format", "jsonl", "--tables", "facts"],
    )
    assert rc == 0
    lines = (out / "facts.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines, "JSONL output should have at least one line"
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


# ── export — CSV ─────────────────────────────────────────────────


def test_export_csv_format_writes_header(live_instance, tmp_path):
    out = tmp_path / "dump"
    rc = memory_verbs._cmd_memory_argv(
        ["export", str(out), "--format", "csv", "--tables", "facts"],
    )
    assert rc == 0
    text = (out / "facts.csv").read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    assert rows
    assert "key" in rows[0]
    assert "value" in rows[0]


def test_export_csv_encodes_nested_values_as_json(live_instance, tmp_path):
    """CSV cells holding dicts/lists get JSON-encoded so the file
    stays parseable. Pin this — Pandas / spreadsheet tools need a
    string here."""
    out = tmp_path / "dump"
    memory_verbs._cmd_memory_argv(
        ["export", str(out), "--format", "csv", "--tables", "tool_calls"],
    )
    text = (out / "tool_calls.csv").read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    # args_json was decoded to a dict, then re-encoded for the cell.
    decoded = json.loads(rows[0]["args_json"])
    assert decoded == {"cmd": "ls"}


# ── export — redaction ───────────────────────────────────────────


def test_export_redacts_secrets_in_args(live_instance, tmp_path):
    """Belt-and-braces: export passes a fresh redact_obj over each
    row even though writes already redacted. A secret slipped in
    pre-redactor (audit row from an old build) must still be hidden."""
    # Add a tool call with a secret already in plaintext via raw SQL
    # (bypassing the redactor that record_tool_call applies).
    layout = SimpleNamespace(
        memory_dir=live_instance / "memory",
        logs_dir=live_instance / "logs",
        audit_log_path=live_instance / "logs" / "audit.log",
    )
    mem.bind(layout)
    with sqlite_store.writer() as conn:
        conn.execute(
            "INSERT INTO tool_calls "
            "(session_key, tool_name, args_json, result_json, ok, ts)"
            " VALUES ('default', 't',"
            ' \'{"api_key": "sk-PLAIN-SECRET-XYZ"}\','
            " null, 1, '2026-01-01T00:00:00+00:00')"
        )
    sqlite_store.close()

    out = tmp_path / "dump"
    memory_verbs._cmd_memory_argv(
        ["export", str(out), "--tables", "tool_calls"],
    )
    text = (out / "tool_calls.json").read_text(encoding="utf-8")
    assert "sk-PLAIN-SECRET-XYZ" not in text


# ── stats ─────────────────────────────────────────────────────────


def test_stats_prints_counts(live_instance, capsys):
    rc = memory_verbs._cmd_memory_argv(["stats"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "facts" in out
    assert "tool_calls" in out
    assert "db_path" in out
    assert "db_size" in out


def test_stats_reports_vec_extension_state(live_instance, capsys):
    """Either 'loaded' or 'fallback' — must not crash either way."""
    memory_verbs._cmd_memory_argv(["stats"])
    out = capsys.readouterr().out
    assert "vec_ext" in out


# ── dispatcher integration ───────────────────────────────────────


def test_cli_dispatcher_routes_memory_subcommand():
    """``jaeger memory`` (no verb) gets picked up by ``cli.dispatch``."""
    from jaeger_ai.cli.verbs import dispatch as cli
    assert "memory" in cli.SUBCOMMANDS
    assert cli.is_daemon_subcommand(["memory", "stats"]) is True
    assert cli.is_daemon_subcommand(["memory", "export", "/tmp/x"]) is True
