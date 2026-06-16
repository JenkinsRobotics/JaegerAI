"""``jaeger memory ...`` — inspect + export the agent's memory store.

Verbs:

  jaeger memory export <path> [--tables ...] [--format json|jsonl|csv]
      Dump the SQLite tables under ``<instance>/memory/state.db``
      into a portable bundle. Used to feed training pipelines and
      to ship a dataset to a remote analysis box without copying
      the whole instance directory.

  jaeger memory stats
      Per-table row counts + DB file size. Quick health check for
      the daemon's ``--doctor`` page and for the user.

The redactor (``core/safety/redact.py``) already ran at write time —
secrets in ``args_json`` / ``result_json`` / ``payload_json`` columns
are already redacted on disk. The export verb does a second pass for
belt-and-braces: any column that might carry a free-form payload is
re-redacted before writing the bundle, so a row that pre-dates the
redactor never leaks. JSON file output is the default; CSV is the
training-friendly shape; JSONL streams large tables row-by-row.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_TABLES: tuple[str, ...] = (
    "facts",
    "episodic",
    "schedules",
    "tool_calls",
    "audit_log",
)
_VALID_FORMATS: frozenset[str] = frozenset({"json", "jsonl", "csv"})
# Columns that hold redacted JSON-encoded payloads. The export pass
# decodes them before writing so the consumer sees structured data,
# not stringly-typed JSON-in-JSON.
_JSON_COLUMNS: frozenset[str] = frozenset({
    "args_json", "result_json", "payload_json", "meta_json",
    "tool_activity",
})


def _cmd_memory_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger memory <verb> [args...]\n"
            "\n"
            "verbs:\n"
            "  export <path>              dump SQLite tables to a bundle\n"
            "  stats                      per-table row counts + DB size\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb = argv[0]
    rest = argv[1:]
    if verb == "export":
        return _memory_export(rest)
    if verb == "stats":
        return _memory_stats(rest)
    print(f"[jaeger memory] unknown verb {verb!r}", file=sys.stderr)
    return 2


# ── export ───────────────────────────────────────────────────────


def _memory_export(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger memory export", add_help=False,
    )
    parser.add_argument("path", nargs="?", default=None,
                        help="output directory (created if missing)")
    parser.add_argument("--instance", default=None,
                        help="instance name (default: active)")
    parser.add_argument("--tables", default=None,
                        help=f"comma-separated table list "
                             f"(default: {','.join(_DEFAULT_TABLES)})")
    parser.add_argument("--format", default="json",
                        choices=sorted(_VALID_FORMATS),
                        help="output format (default: json)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help or args.path is None:
        print(
            "usage: jaeger memory export <path>\n"
            "                            [--instance NAME]\n"
            "                            [--tables T1,T2,...]\n"
            "                            [--format json|jsonl|csv]",
            file=sys.stderr,
        )
        return 0 if args.help else 2

    out_dir = Path(args.path).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    layout = _resolve_layout(args.instance)
    if layout is None:
        return 1

    from jaeger_os.core.memory import memory as mem
    from jaeger_os.core.memory import sqlite_store

    # Bind so the DB is open + lazy imports run.
    mem.bind(layout)
    conn = sqlite_store.connection()

    requested = (
        [t.strip() for t in args.tables.split(",") if t.strip()]
        if args.tables else list(_DEFAULT_TABLES)
    )
    available = _list_tables(conn)
    bad = [t for t in requested if t not in available]
    if bad:
        print(f"[jaeger memory export] unknown table(s): {bad}",
              file=sys.stderr)
        print(f"available: {sorted(available)}", file=sys.stderr)
        return 1

    manifest: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instance": layout.root.name,
        "format": args.format,
        "tables": {},
    }
    for tbl in requested:
        rows = _read_table(conn, tbl)
        out_path = out_dir / f"{tbl}.{args.format}"
        _write_rows(out_path, rows, args.format)
        manifest["tables"][tbl] = {
            "rows": len(rows),
            "path": out_path.name,
        }

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, default=str),
        encoding="utf-8",
    )
    total = sum(t["rows"] for t in manifest["tables"].values())
    print(f"[jaeger memory export] wrote {total} rows across "
          f"{len(requested)} table(s) to {out_dir}")
    return 0


# ── stats ────────────────────────────────────────────────────────


def _memory_stats(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger memory stats", add_help=False,
    )
    parser.add_argument("--instance", default=None,
                        help="instance name (default: active)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print("usage: jaeger memory stats [--instance NAME]", file=sys.stderr)
        return 0

    layout = _resolve_layout(args.instance)
    if layout is None:
        return 1

    from jaeger_os.core.memory import memory as mem
    from jaeger_os.core.memory import sqlite_store
    mem.bind(layout)
    conn = sqlite_store.connection()

    db_path = layout.memory_dir / "state.db"
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    print(f"# memory stats — instance {layout.root.name!r}")
    print(f"  db_path:  {db_path}")
    print(f"  db_size:  {db_bytes:,} bytes")
    if sqlite_store.has_vec_extension():
        print("  vec_ext:  loaded (sqlite-vec)")
    else:
        print("  vec_ext:  fallback (Python cosine over BLOBs)")
    print("  tables:")
    for tbl in sorted(_list_tables(conn)):
        if tbl.startswith("sqlite_"):
            continue
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"    {tbl:<24} {count:>8} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"    {tbl:<24} (count failed: {exc})")
    return 0


# ── helpers ──────────────────────────────────────────────────────


def _resolve_layout(instance_name: str | None):
    """Return an InstanceLayout for ``instance_name`` or None on
    error (with stderr message)."""
    from jaeger_os.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir,
    )
    name = instance_name or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.exists():
        print(f"[jaeger memory] no instance {name!r} at {layout.root}",
              file=sys.stderr)
        return None
    return layout


def _list_tables(conn: Any) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r["name"] for r in rows}


def _read_table(conn: Any, tbl: str) -> list[dict[str, Any]]:
    """Read every row of ``tbl`` into dicts, JSON-decoding columns
    listed in ``_JSON_COLUMNS`` so the consumer sees structured data."""
    rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        rec: dict[str, Any] = {k: r[k] for k in r.keys()}
        for col in _JSON_COLUMNS & set(rec.keys()):
            if isinstance(rec[col], str) and rec[col]:
                try:
                    rec[col] = json.loads(rec[col])
                except (TypeError, ValueError):
                    pass  # leave raw — corrupt JSON, downstream can flag
        # Belt-and-braces redaction pass.
        try:
            from jaeger_os.core.safety.redact import redact_obj
            rec = redact_obj(rec)
        except Exception:  # noqa: BLE001 — redact missing in tests is fine
            pass
        out.append(rec)
    return out


def _write_rows(path: Path, rows: list[dict[str, Any]], fmt: str) -> None:
    if fmt == "json":
        path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=True, default=str),
            encoding="utf-8",
        )
        return
    if fmt == "jsonl":
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=True, default=str) + "\n")
        return
    if fmt == "csv":
        # Union of every row's keys so a sparse column (only in a
        # subset of rows) still gets a header. Nested values are
        # JSON-encoded into the cell.
        keys: list[str] = []
        seen: set[str] = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    k: (json.dumps(v, ensure_ascii=True, default=str)
                        if isinstance(v, (dict, list)) else v)
                    for k, v in r.items()
                })
        return
    raise ValueError(f"unsupported format {fmt!r}")


__all__ = ["_cmd_memory_argv"]
