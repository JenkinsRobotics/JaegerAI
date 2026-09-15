"""Encrypted SQLite persistence for the Jaeger Finance Engine."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    Account,
    AccountType,
    ApprovalTier,
    Category,
    CategoryBudget,
    PendingAction,
    ReviewStatus,
    Rule,
    Transaction,
)
from .security import FinanceCipher, SecuritySanitizer

logger = logging.getLogger("jaeger_ai.features.finance.store")


def _state_root() -> Path:
    raw = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".jaeger").resolve()


def default_database_path() -> Path:
    return _state_root() / "finance" / "finance.db"


class FinanceStore:
    """Local-first, encrypted SQLite database for all financial records and audit trail."""

    def __init__(self, db_path: Path | None = None, cipher: FinanceCipher | None = None) -> None:
        self.db_path = db_path or default_database_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = cipher or FinanceCipher(custom_dir=self.db_path.parent)
        self._init_schema()
        # Enforce 0600 on the database file
        try:
            if self.db_path.exists():
                self.db_path.chmod(0o600)
        except OSError:
            pass

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    balance REAL NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    mask TEXT,
                    subtype TEXT,
                    is_hidden INTEGER DEFAULT 0,
                    updated_at TEXT,
                    provider TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS categories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    group_name TEXT DEFAULT 'General',
                    is_income INTEGER DEFAULT 0,
                    is_system INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    merchant TEXT NOT NULL,
                    raw_statement_enc TEXT,
                    category TEXT NOT NULL,
                    category_id TEXT,
                    pending INTEGER DEFAULT 0,
                    is_split INTEGER DEFAULT 0,
                    parent_id TEXT,
                    notes_enc TEXT,
                    tags_json TEXT,
                    is_transfer INTEGER DEFAULT 0,
                    review_status TEXT DEFAULT 'new',
                    suggested_category TEXT,
                    classification_confidence REAL DEFAULT 0.0,
                    classification_explanation TEXT,
                    matching_rule_id TEXT,
                    account_name TEXT,
                    provider TEXT NOT NULL,
                    content_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tx_hash ON transactions(content_hash);
                CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
                CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
                CREATE INDEX IF NOT EXISTS idx_tx_review ON transactions(review_status);

                CREATE TABLE IF NOT EXISTS budgets (
                    category TEXT NOT NULL,
                    month TEXT NOT NULL,
                    budgeted REAL NOT NULL,
                    actual REAL NOT NULL,
                    remaining REAL NOT NULL,
                    spent_pct REAL DEFAULT 0.0,
                    category_id TEXT,
                    PRIMARY KEY (category, month)
                );

                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    target_category TEXT NOT NULL,
                    target_tags_json TEXT,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'user',
                    approved_by_user INTEGER DEFAULT 1,
                    scope TEXT DEFAULT 'all_accounts',
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT DEFAULT 'pending'
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_state (
                    provider TEXT PRIMARY KEY,
                    last_synced_at TEXT,
                    status TEXT,
                    details_json TEXT
                );
            """)

    # ---------------- Accounts ----------------
    def upsert_accounts(self, accounts: list[Account]) -> int:
        count = 0
        with self._get_conn() as conn:
            for acct in accounts:
                conn.execute(
                    """
                    INSERT INTO accounts (id, name, type, balance, currency, mask, subtype, is_hidden, updated_at, provider)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        type=excluded.type,
                        balance=excluded.balance,
                        currency=excluded.currency,
                        mask=excluded.mask,
                        subtype=excluded.subtype,
                        is_hidden=excluded.is_hidden,
                        updated_at=excluded.updated_at,
                        provider=excluded.provider
                    """,
                    (
                        acct.id,
                        SecuritySanitizer.sanitize_untrusted_text(acct.name),
                        acct.type.value,
                        acct.balance,
                        acct.currency,
                        SecuritySanitizer.mask_account_identifier(acct.mask),
                        acct.subtype,
                        1 if acct.is_hidden else 0,
                        acct.updated_at or datetime.now(UTC).isoformat(),
                        acct.provider,
                    ),
                )
                count += 1
        return count

    def get_accounts(self, include_hidden: bool = False) -> list[Account]:
        query = "SELECT * FROM accounts" if include_hidden else "SELECT * FROM accounts WHERE is_hidden = 0"
        accounts: list[Account] = []
        with self._get_conn() as conn:
            for row in conn.execute(query).fetchall():
                accounts.append(
                    Account(
                        id=row["id"],
                        name=row["name"],
                        type=AccountType(row["type"]),
                        balance=row["balance"],
                        currency=row["currency"],
                        mask=row["mask"],
                        subtype=row["subtype"],
                        is_hidden=bool(row["is_hidden"]),
                        updated_at=row["updated_at"],
                        provider=row["provider"],
                    )
                )
        return accounts

    # ---------------- Transactions ----------------
    def _compute_tx_hash(self, tx: Transaction) -> str:
        h = hashlib.sha256()
        h.update(f"{tx.provider}:{tx.account_id}:{tx.date}:{tx.amount:.2f}:{tx.merchant.lower()}".encode())
        return h.hexdigest()

    def upsert_transactions(self, transactions: list[Transaction]) -> tuple[int, int]:
        """Insert or update transactions idempotently.
        Returns: (inserted_or_updated_count, duplicates_skipped)
        """
        inserted = 0
        skipped = 0
        with self._get_conn() as conn:
            for tx in transactions:
                clean_merchant = SecuritySanitizer.sanitize_untrusted_text(tx.merchant)
                raw_stmt_enc = self.cipher.encrypt(SecuritySanitizer.sanitize_untrusted_text(tx.raw_statement))
                notes_enc = self.cipher.encrypt(SecuritySanitizer.sanitize_untrusted_text(tx.notes))
                content_hash = self._compute_tx_hash(tx)

                # Check if identical transaction ID exists
                existing = conn.execute(
                    "SELECT id, review_status FROM transactions WHERE id = ?",
                    (tx.id,),
                ).fetchone()

                if existing:
                    # Idempotent skip: transaction already ingested
                    skipped += 1
                    continue

                conn.execute(
                    """
                    INSERT INTO transactions (
                        id, account_id, date, amount, merchant, raw_statement_enc,
                        category, category_id, pending, is_split, parent_id,
                        notes_enc, tags_json, is_transfer, review_status,
                        suggested_category, classification_confidence,
                        classification_explanation, matching_rule_id, account_name,
                        provider, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        account_id=excluded.account_id,
                        date=excluded.date,
                        amount=excluded.amount,
                        merchant=excluded.merchant,
                        category=excluded.category,
                        pending=excluded.pending,
                        account_name=excluded.account_name,
                        content_hash=excluded.content_hash
                    """,
                    (
                        tx.id,
                        tx.account_id,
                        tx.date,
                        tx.amount,
                        clean_merchant,
                        raw_stmt_enc,
                        tx.category,
                        tx.category_id,
                        1 if tx.pending else 0,
                        1 if tx.is_split else 0,
                        tx.parent_id,
                        notes_enc,
                        json.dumps(tx.tags),
                        1 if tx.is_transfer else 0,
                        tx.review_status.value,
                        tx.suggested_category,
                        tx.classification_confidence,
                        tx.classification_explanation,
                        tx.matching_rule_id,
                        tx.account_name,
                        tx.provider,
                        content_hash,
                    ),
                )
                inserted += 1
        return inserted, skipped

    def get_transactions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        account_id: str | None = None,
        review_status: ReviewStatus | None = None,
        limit: int = 200,
    ) -> list[Transaction]:
        sql = "SELECT * FROM transactions WHERE 1=1"
        params: list[Any] = []
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        if account_id:
            sql += " AND account_id = ?"
            params.append(account_id)
        if review_status:
            sql += " AND review_status = ?"
            params.append(review_status.value)
        sql += " ORDER BY date DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))

        tx_list: list[Transaction] = []
        with self._get_conn() as conn:
            for row in conn.execute(sql, params).fetchall():
                tags = []
                try:
                    tags = json.loads(row["tags_json"]) if row["tags_json"] else []
                except Exception:
                    pass
                tx_list.append(
                    Transaction(
                        id=row["id"],
                        account_id=row["account_id"],
                        date=row["date"],
                        amount=row["amount"],
                        merchant=row["merchant"],
                        raw_statement=self.cipher.decrypt(row["raw_statement_enc"] or ""),
                        category=row["category"],
                        category_id=row["category_id"],
                        pending=bool(row["pending"]),
                        is_split=bool(row["is_split"]),
                        parent_id=row["parent_id"],
                        notes=self.cipher.decrypt(row["notes_enc"] or ""),
                        tags=tags,
                        is_transfer=bool(row["is_transfer"]),
                        review_status=ReviewStatus(row["review_status"]),
                        suggested_category=row["suggested_category"],
                        classification_confidence=row["classification_confidence"],
                        classification_explanation=row["classification_explanation"] or "",
                        matching_rule_id=row["matching_rule_id"],
                        account_name=row["account_name"] or "",
                        provider=row["provider"],
                    )
                )
        return tx_list

    def update_transaction_review(
        self,
        tx_id: str,
        status: ReviewStatus,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        sql = "UPDATE transactions SET review_status = ?"
        params: list[Any] = [status.value]
        if category is not None:
            sql += ", category = ?"
            params.append(category)
        if tags is not None:
            sql += ", tags_json = ?"
            params.append(json.dumps(tags))
        sql += " WHERE id = ?"
        params.append(tx_id)

        with self._get_conn() as conn:
            cur = conn.execute(sql, params)
            return cur.rowcount > 0

    # ---------------- Budgets ----------------
    def upsert_budgets(self, budgets: list[CategoryBudget], month: str) -> int:
        count = 0
        with self._get_conn() as conn:
            for b in budgets:
                spent_pct = (b.actual / b.budgeted * 100.0) if b.budgeted > 0 else 0.0
                conn.execute(
                    """
                    INSERT INTO budgets (category, month, budgeted, actual, remaining, spent_pct, category_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category, month) DO UPDATE SET
                        budgeted=excluded.budgeted,
                        actual=excluded.actual,
                        remaining=excluded.remaining,
                        spent_pct=excluded.spent_pct,
                        category_id=excluded.category_id
                    """,
                    (
                        b.category,
                        month,
                        b.budgeted,
                        b.actual,
                        b.remaining,
                        spent_pct,
                        b.category_id,
                    ),
                )
                count += 1
        return count

    def get_budgets(self, month: str) -> list[CategoryBudget]:
        budgets: list[CategoryBudget] = []
        with self._get_conn() as conn:
            for row in conn.execute("SELECT * FROM budgets WHERE month = ?", (month,)).fetchall():
                budgets.append(
                    CategoryBudget(
                        category=row["category"],
                        budgeted=row["budgeted"],
                        actual=row["actual"],
                        remaining=row["remaining"],
                        spent_pct=row["spent_pct"],
                        category_id=row["category_id"],
                    )
                )
        return budgets

    # ---------------- Rules ----------------
    def upsert_rule(self, rule: Rule) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO rules (
                    id, name, pattern, target_category, target_tags_json,
                    confidence, source, approved_by_user, scope, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    pattern=excluded.pattern,
                    target_category=excluded.target_category,
                    target_tags_json=excluded.target_tags_json,
                    confidence=excluded.confidence,
                    source=excluded.source,
                    approved_by_user=excluded.approved_by_user,
                    scope=excluded.scope,
                    last_used_at=excluded.last_used_at
                """,
                (
                    rule.id,
                    rule.name,
                    rule.pattern,
                    rule.target_category,
                    json.dumps(rule.target_tags),
                    rule.confidence,
                    rule.source,
                    1 if rule.approved_by_user else 0,
                    rule.scope,
                    rule.created_at,
                    rule.last_used_at,
                ),
            )

    def get_rules(self) -> list[Rule]:
        rules: list[Rule] = []
        with self._get_conn() as conn:
            for row in conn.execute("SELECT * FROM rules ORDER BY created_at DESC").fetchall():
                tags = []
                try:
                    tags = json.loads(row["target_tags_json"]) if row["target_tags_json"] else []
                except Exception:
                    pass
                rules.append(
                    Rule(
                        id=row["id"],
                        name=row["name"],
                        pattern=row["pattern"],
                        target_category=row["target_category"],
                        target_tags=tags,
                        confidence=row["confidence"],
                        source=row["source"],
                        approved_by_user=bool(row["approved_by_user"]),
                        scope=row["scope"],
                        created_at=row["created_at"],
                        last_used_at=row["last_used_at"],
                    )
                )
        return rules

    def delete_rule(self, rule_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            return cur.rowcount > 0

    # ---------------- Audit Log (Append-Only Hash Chain) ----------------
    def append_audit(self, action: str, actor: str, details: dict[str, Any]) -> str:
        """Append an immutable audit entry with SHA-256 cryptographic chain link."""
        with self._get_conn() as conn:
            last = conn.execute("SELECT record_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = last["record_hash"] if last else "0" * 64
            now_iso = datetime.now(UTC).isoformat()
            details_str = json.dumps(details, sort_keys=True, default=str)

            h = hashlib.sha256()
            h.update(f"{prev_hash}:{now_iso}:{action}:{actor}:{details_str}".encode())
            record_hash = h.hexdigest()

            conn.execute(
                """
                INSERT INTO audit_log (timestamp, action, actor, details_json, prev_hash, record_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now_iso, action, actor, details_str, prev_hash, record_hash),
            )
            return record_hash

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        with self._get_conn() as conn:
            for row in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall():
                try:
                    det = json.loads(row["details_json"])
                except Exception:
                    det = {}
                entries.append({
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "action": row["action"],
                    "actor": row["actor"],
                    "details": det,
                    "prev_hash": row["prev_hash"],
                    "record_hash": row["record_hash"],
                })
        return entries

    # ---------------- Sync State ----------------
    def update_sync_state(self, provider: str, status: str, details: dict[str, Any]) -> None:
        now_iso = datetime.now(UTC).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (provider, last_synced_at, status, details_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    last_synced_at=excluded.last_synced_at,
                    status=excluded.status,
                    details_json=excluded.details_json
                """,
                (provider, now_iso, status, json.dumps(details, default=str)),
            )

    def get_sync_state(self, provider: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sync_state WHERE provider = ?", (provider,)).fetchone()
            if not row:
                return None
            try:
                det = json.loads(row["details_json"]) if row["details_json"] else {}
            except Exception:
                det = {}
            return {
                "provider": row["provider"],
                "last_synced_at": row["last_synced_at"],
                "status": row["status"],
                "details": det,
            }

    # ---------------- Pending Actions ----------------
    def record_pending_action(self, action: PendingAction) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_actions (id, action_type, payload_json, rationale, tier, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status
                """,
                (
                    action.id,
                    action.action_type,
                    json.dumps(action.payload, default=str),
                    action.rationale,
                    action.tier.value,
                    action.created_at,
                    action.expires_at,
                    action.status,
                ),
            )

    def get_pending_actions(self, status: str = "pending") -> list[PendingAction]:
        actions: list[PendingAction] = []
        with self._get_conn() as conn:
            for row in conn.execute("SELECT * FROM pending_actions WHERE status = ?", (status,)).fetchall():
                payload = {}
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    pass
                actions.append(
                    PendingAction(
                        id=row["id"],
                        action_type=row["action_type"],
                        payload=payload,
                        rationale=row["rationale"],
                        tier=ApprovalTier(row["tier"]),
                        created_at=row["created_at"],
                        expires_at=row["expires_at"],
                        status=row["status"],
                    )
                )
        return actions

    def update_pending_action_status(self, action_id: str, status: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE pending_actions SET status = ? WHERE id = ?", (status, action_id))
            return cur.rowcount > 0

    # ---------------- Privacy & Data Purge ----------------
    def purge_all(self) -> None:
        """Completely wipe local financial records, adhering to privacy controls."""
        with self._get_conn() as conn:
            conn.executescript("""
                DELETE FROM accounts;
                DELETE FROM transactions;
                DELETE FROM budgets;
                DELETE FROM rules;
                DELETE FROM pending_actions;
                DELETE FROM audit_log;
                DELETE FROM sync_state;
                VACUUM;
            """)
        self.append_audit("purge_all", "operator", {"status": "all_financial_records_purged"})
