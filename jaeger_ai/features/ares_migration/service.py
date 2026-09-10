"""Idempotent ARES state absorption and retirement-gate rehearsal.

The source is always read-only. ARES remains runnable until the operator has a
verified backup and every reported blocker is resolved.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from jaeger_agent.background.board import Board
from jaeger_agent.delegates.health import DelegateObservation, get_delegate_health_store
from jaeger_agent.memory import memory

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.sessions import SessionStore
from jaeger_ai.features.history_import.ares import AresHistorySource
from jaeger_ai.features.history_import.service import HistoryImportService
from jaeger_ai.features.knowledge_library import KnowledgeLibrary, LibraryError

MAX_FILES = 100_000
MAX_COPY_BYTES = 64 * 1024 * 1024
SECRET_NAMES = frozenset({
    ".env",
    ".signing_key",
    "gateway.token",
    "passkeys.json",
    "providers.json",
})
DOCUMENT_DIRS = ("plans", "memory", "memories", "research_reports", "knowledge")


class MigrationError(RuntimeError):
    pass


class AresMigrationService:
    def __init__(
        self,
        source: Path,
        layout: InstanceLayout,
        sessions: SessionStore,
    ) -> None:
        self.source = Path(source).expanduser().resolve()
        self.layout = layout
        self.sessions = sessions
        self.state_dir = layout.memory_dir / "ares_migration"
        self.manifest_path = self.state_dir / "migration.json"

    def audit(self) -> dict[str, Any]:
        if not self.source.is_dir():
            raise MigrationError(f"ARES state directory does not exist: {self.source}")
        files = []
        bytes_total = 0
        secret_files = 0
        oversize_files = 0
        symlinks = 0
        for candidate in self.source.rglob("*"):
            if len(files) >= MAX_FILES:
                break
            try:
                if candidate.is_symlink():
                    symlinks += 1
                    continue
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve(strict=True)
                relative = str(resolved.relative_to(self.source))
                size = resolved.stat().st_size
            except (OSError, ValueError):
                continue
            secret = self._is_secret(relative)
            secret_files += int(secret)
            oversize_files += int(size > MAX_COPY_BYTES)
            bytes_total += size
            files.append({
                "path": relative,
                "bytes": size,
                "modified_ns": resolved.stat().st_mtime_ns,
                "secret": secret,
            })
        return {
            "source": str(self.source),
            "files": len(files),
            "bytes": bytes_total,
            "secret_files": secret_files,
            "oversize_files": oversize_files,
            "symlinks_skipped": symlinks,
            "truncated": len(files) >= MAX_FILES,
            "sessions": len(AresHistorySource(self.source / "webui" / "sessions").discover()),
            "scheduled_jobs": len(self._schedule_rows()),
            "worker_observations": len(self._worker_rows()),
            "document_roots": [
                name for name in DOCUMENT_DIRS if (self.source / name).is_dir()
            ],
            "fingerprint": self._fingerprint(files),
        }

    def migrate(self) -> dict[str, Any]:
        audit = self.audit()
        prior = self._read_manifest()
        if prior.get("status") == "completed" and prior.get("fingerprint") == audit["fingerprint"]:
            return {"ok": True, "idempotent": True, **prior}
        self.layout.ensure_dirs()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {
            "status": "running",
            "source": str(self.source),
            "fingerprint": audit["fingerprint"],
            "started_at": time.time(),
        }
        self._write_manifest(report)
        try:
            history = HistoryImportService(
                self.sessions,
                sources=(AresHistorySource(self.source / "webui" / "sessions"),),
            ).import_all()[0]
            report["sessions"] = {
                "discovered": history.discovered,
                "imported": history.imported,
                "skipped": history.skipped,
                "failed": history.failed,
                "messages": history.messages,
            }
            report["documents"] = self._migrate_documents()
            report["schedules"] = self._migrate_schedules()
            report["worker_health"] = self._migrate_worker_health()
            report["passkeys"] = self._migrate_passkeys()
            report["kanban"] = self._migrate_kanban()
            report.update(status="completed", completed_at=time.time())
            self._write_manifest(report)
            return {"ok": True, "idempotent": False, **report}
        except Exception as exc:
            report.update(status="failed", error=str(exc), failed_at=time.time())
            self._write_manifest(report)
            raise MigrationError(f"ARES migration failed: {exc}") from exc

    def create_backup(self, output: Path, *, include_secrets: bool = False) -> dict[str, Any]:
        """Create a permission-restricted source snapshot without following links."""
        audit = self.audit()
        target = Path(output).expanduser().resolve()
        try:
            target.relative_to(self.source)
        except ValueError:
            pass
        else:
            raise MigrationError("backup output must be outside the ARES source tree")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        included = skipped = 0
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for candidate in self.source.rglob("*"):
                    if candidate.is_symlink() or not candidate.is_file():
                        continue
                    resolved = candidate.resolve(strict=True)
                    relative = str(resolved.relative_to(self.source))
                    if self._is_secret(relative) and not include_secrets:
                        skipped += 1
                        continue
                    archive.write(resolved, arcname=relative)
                    included += 1
                archive.writestr(
                    "JAEGER_ARES_BACKUP_MANIFEST.json",
                    json.dumps(
                        {
                            **audit,
                            "backup": {
                                "included": included,
                                "skipped": skipped,
                                "includes_secrets": include_secrets,
                            },
                        },
                        sort_keys=True,
                    ),
                )
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {
            "path": str(target),
            "included": included,
            "skipped": skipped,
            "includes_secrets": include_secrets,
            "sha256": self._digest(target),
        }

    def rehearse_retirement(self, backup: Path | None = None) -> dict[str, Any]:
        """Evaluate retirement gates. This function never stops or deletes ARES."""
        blockers = []
        manifest = self._read_manifest()
        audit = self.audit()
        if manifest.get("status") != "completed":
            blockers.append("state migration has not completed")
        elif manifest.get("fingerprint") != audit["fingerprint"]:
            blockers.append("ARES state changed after the last migration")
        if backup is None or not Path(backup).expanduser().is_file():
            blockers.append("a verified ARES backup was not supplied")
        else:
            try:
                with zipfile.ZipFile(Path(backup).expanduser()) as archive:
                    if archive.testzip() is not None:
                        blockers.append("ARES backup failed CRC verification")
                    if "JAEGER_ARES_BACKUP_MANIFEST.json" not in archive.namelist():
                        blockers.append("ARES backup manifest is missing")
                    else:
                        backup_manifest = json.loads(
                            archive.read("JAEGER_ARES_BACKUP_MANIFEST.json")
                        )
                        details = backup_manifest.get("backup", {})
                        secrets_omitted = bool(backup_manifest.get("secret_files")) and not details.get(
                            "includes_secrets"
                        )
                        if secrets_omitted or details.get("skipped"):
                            blockers.append("ARES backup is partial; retirement requires all state and secrets")
            except (OSError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
                blockers.append("ARES backup is unreadable")
        if audit["truncated"]:
            blockers.append("source inventory exceeded the file limit")
        return {
            "ready": not blockers,
            "blockers": blockers,
            "source_untouched": True,
            "action": "keep ARES installed" if blockers else "operator may schedule a manual cutover",
        }

    def _migrate_documents(self) -> list[dict[str, Any]]:
        destination = self.state_dir / "documents"
        library = KnowledgeLibrary(self.layout.memory_dir / "library.db")
        reports = []
        try:
            for name in DOCUMENT_DIRS:
                source_root = self.source / name
                if not source_root.is_dir():
                    continue
                target_root = destination / name
                copied = self._copy_text_tree(source_root, target_root)
                try:
                    collection = library.add(str(target_root), f"ARES {name}")
                except LibraryError:
                    collection = next(
                        row for row in library.list() if row["root"] == str(target_root.resolve())
                    )
                indexed = library.index(collection["id"])
                reports.append({"root": name, "copied": copied, **indexed})
        finally:
            library.close()
        return reports

    def _copy_text_tree(self, source: Path, destination: Path) -> int:
        copied = 0
        for candidate in source.rglob("*"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(source.resolve())
            if resolved.stat().st_size > MAX_COPY_BYTES or self._is_secret(str(relative)):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copyfile(resolved, temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            copied += 1
        return copied

    def _migrate_schedules(self) -> dict[str, int]:
        existing = {str(row.get("name") or "") for row in memory.list_schedules()}
        imported = skipped = 0
        for row in self._schedule_rows():
            name = str(row.get("name") or row.get("id") or "").strip()
            prompt = str(row.get("prompt") or "").strip()
            schedule = str(row.get("schedule") or "").strip()
            if not name or not prompt or not schedule or name in existing:
                skipped += 1
                continue
            memory.add_schedule(cron_expr=schedule, prompt=prompt, name=name)
            existing.add(name)
            imported += 1
        return {"imported": imported, "skipped": skipped}

    def _migrate_worker_health(self) -> dict[str, int]:
        runtime_map = {
            "claude_local": "claude",
            "codex_local": "codex",
            "cursor_local": "cursor",
            "gemini_local": "gemini",
            "grok_local": "grok",
            "hermes_local": "hermes",
            "ollama_local": "ollama",
            "openclaw_local": "openclaw",
            "opencode_local": "opencode",
        }
        imported = skipped = 0
        store = get_delegate_health_store()
        for row in self._worker_rows():
            runtime_id = runtime_map.get(str(row.get("worker_id") or ""))
            if runtime_id is None:
                skipped += 1
                continue
            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            success_score = float(metrics.get("task_success") or 0)
            store.record(DelegateObservation(
                runtime_id=runtime_id,
                success=success_score >= 50,
                latency_ms=0,
                quality=max(0.0, min(float(row.get("effectiveness") or 0) / 100, 1.0)),
                capability=str(row.get("task_kind") or "general"),
                metadata={"source": "ares", "source_id": str(row.get("id") or "")},
            ))
            imported += 1
        return {"imported": imported, "skipped": skipped}

    def _migrate_passkeys(self) -> dict[str, Any]:
        source = self.source / "webui" / "passkeys.json"
        target = self.layout.memory_dir / "passkeys" / "passkeys.json"
        if not source.is_file():
            return {"imported": False, "reason": "no ARES passkeys found"}
        if target.exists():
            return {"imported": False, "reason": "Jaeger passkeys already exist"}
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return {"imported": True}

    def _migrate_kanban(self) -> dict[str, Any]:
        candidates = (self.source / "kanban" / "board.json", self.source / "kanban.json")
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            return {"imported": 0, "skipped": 0}
        raw = json.loads(source.read_text(encoding="utf-8"))
        rows = raw.get("cards", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return {"imported": 0, "skipped": 1}
        board = Board(self.layout.memory_dir / "board.json")
        existing = {card.title for card in board.list()}
        imported = skipped = 0
        for row in rows:
            if not isinstance(row, dict):
                skipped += 1
                continue
            title = str(row.get("title") or "").strip()
            if not title or title in existing:
                skipped += 1
                continue
            board.add(
                title,
                column=str(row.get("column") or row.get("status") or "backlog"),
                description=str(row.get("description") or ""),
                source="ares",
                tags=[str(tag) for tag in row.get("tags", []) if str(tag)],
                priority=str(row.get("priority") or "med"),
            )
            existing.add(title)
            imported += 1
        return {"imported": imported, "skipped": skipped}

    def _schedule_rows(self) -> list[dict[str, Any]]:
        return self._list_from_json(self.source / "cron" / "jobs.json", "jobs")

    def _worker_rows(self) -> list[dict[str, Any]]:
        return self._list_from_json(self.source / "webui" / "worker-rankings.json", "events")

    @staticmethod
    def _list_from_json(path: Path, key: str) -> list[dict[str, Any]]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = value.get(key, []) if isinstance(value, dict) else []
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def _read_manifest(self) -> dict[str, Any]:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_manifest(self, value: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.manifest_path)

    @staticmethod
    def _is_secret(relative: str) -> bool:
        path = Path(relative)
        return path.name in SECRET_NAMES or "credentials" in path.parts

    @staticmethod
    def _fingerprint(files: list[dict[str, Any]]) -> str:
        stable = [(row["path"], row["bytes"], row["modified_ns"]) for row in files]
        return hashlib.sha256(json.dumps(stable, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
