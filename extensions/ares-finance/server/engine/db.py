"""Local SQLite store for ARES Finance.

Paths are resolved on every call so tests can isolate via
``ARES_FINANCE_DATA_DIR`` / ``ARES_FINANCE_DB`` without reloading modules.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

LIABILITY_TYPES = frozenset({"credit", "loan"})


def data_dir() -> str:
    override = os.environ.get("ARES_FINANCE_DATA_DIR")
    if override:
        return override
    return os.path.join(os.path.dirname(__file__), "..", "data")


def db_path() -> str:
    override = os.environ.get("ARES_FINANCE_DB")
    if override:
        return override
    return os.path.join(data_dir(), "finance.db")


def session_file_path() -> str:
    override = os.environ.get("ARES_FINANCE_SESSION")
    if override:
        return override
    return os.path.join(data_dir(), ".mm_session")


def get_db() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(*, seed: bool = True) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path())) or ".", exist_ok=True)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                subtype TEXT,
                current_balance REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'demo',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                account_id TEXT,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                merchant_name TEXT,
                category TEXT,
                notes TEXT,
                pending INTEGER DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'demo',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                group_id TEXT,
                group_name TEXT,
                icon TEXT DEFAULT '📁',
                is_system INTEGER DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'demo',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id TEXT PRIMARY KEY,
                category_id TEXT NOT NULL,
                category_name TEXT NOT NULL,
                amount REAL NOT NULL,
                spent REAL DEFAULT 0.0,
                remaining REAL DEFAULT 0.0,
                period TEXT,
                source TEXT NOT NULL DEFAULT 'demo',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recurring_bills (
                id TEXT PRIMARY KEY,
                merchant_name TEXT NOT NULL,
                category_name TEXT,
                amount REAL NOT NULL,
                frequency TEXT DEFAULT 'monthly',
                next_date TEXT,
                status TEXT DEFAULT 'active',
                account_id TEXT,
                source TEXT NOT NULL DEFAULT 'demo',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                issuer TEXT NOT NULL,
                reward_structure TEXT NOT NULL,
                spend_cap_monthly REAL DEFAULT 0,
                quarterly_category TEXT,
                notes TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                source TEXT NOT NULL DEFAULT 'demo',
                last_sync_at TIMESTAMP,
                last_status TEXT,
                last_error TEXT,
                synced_accounts INTEGER DEFAULT 0,
                synced_transactions INTEGER DEFAULT 0
            )
        """)
        cursor.execute(
            "INSERT OR IGNORE INTO sync_state (id, source, last_status) "
            "VALUES (1, 'demo', 'never_synced')"
        )

        for table in ("accounts", "transactions", "categories", "budgets", "recurring_bills"):
            cols = {r[1] for r in cursor.execute(f"PRAGMA table_info({table})")}
            if "source" not in cols:
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN source TEXT NOT NULL DEFAULT 'demo'"
                )

        if seed:
            _seed_if_empty(cursor)

        conn.commit()


def _seed_if_empty(cursor: sqlite3.Cursor) -> None:
    cursor.execute("SELECT COUNT(*) FROM cards")
    if cursor.fetchone()[0] == 0:
        default_cards = [
            ("csp", "Chase Sapphire Preferred", "Chase", json.dumps({"dining": 3.0, "travel": 2.0, "streaming": 3.0, "online_grocery": 3.0, "default": 1.0}), 0, "", "3x on dining, select streaming, online groceries"),
            ("citi_cc", "Citi Custom Cash", "Citi", json.dumps({"gas": 5.0, "groceries": 5.0, "dining": 5.0, "travel": 5.0, "ev_charging": 5.0, "default": 1.0}), 500.0, "", "5x on top eligible spend category up to $500/mo"),
            ("amex_gold", "Amex Gold", "American Express", json.dumps({"dining": 4.0, "groceries": 4.0, "flights": 3.0, "default": 1.0}), 25000.0, "", "4x on worldwide dining & US supermarkets up to $25k/yr"),
            ("venture_x", "Capital One Venture X", "Capital One", json.dumps({"travel_portal": 10.0, "flights_portal": 5.0, "default": 2.0}), 0, "", "2x miles catch-all on all purchases"),
            ("apple_card", "Apple Card", "Goldman Sachs", json.dumps({"apple_pay": 2.0, "apple_merchants": 3.0, "default": 1.0}), 0, "", "2% Daily Cash with Apple Pay, 3% at Apple/Nike/Uber"),
        ]
        cursor.executemany(
            "INSERT INTO cards (id, name, issuer, reward_structure, spend_cap_monthly, quarterly_category, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            default_cards,
        )

    cursor.execute("SELECT COUNT(*) FROM accounts")
    if cursor.fetchone()[0] == 0:
        sample_accounts = [
            ("acc_checking", "Primary Checking", "depository", "checking", 5420.50),
            ("acc_savings", "High Yield Savings (4.5%)", "depository", "savings", 28500.00),
            ("acc_roth", "Roth IRA Portfolio", "investment", "ira", 42100.80),
            ("acc_brokerage", "Taxable Brokerage", "investment", "brokerage", 65300.00),
            ("acc_credit", "Sapphire Preferred", "credit", "credit_card", -412.30),
        ]
        cursor.executemany(
            "INSERT INTO accounts (id, name, type, subtype, current_balance) VALUES (?, ?, ?, ?, ?)",
            sample_accounts,
        )
        sample_tx = [
            ("tx_01", "acc_credit", -45.50, "2026-08-22", "Whole Foods Market", "Groceries", "Organic groceries", 0),
            ("tx_02", "acc_credit", -12.40, "2026-08-22", "Blue Bottle Coffee", "Dining", "Espresso", 0),
            ("tx_03", "acc_checking", -120.00, "2026-08-21", "EVgo Charging Station", "EV / Gas", "Fast charging", 0),
            ("tx_04", "acc_checking", 3200.00, "2026-08-15", "Direct Deposit Payroll", "Income", "Salary", 0),
            ("tx_05", "acc_credit", -14.99, "2026-08-10", "Spotify Premium", "Streaming", "Subscription", 0),
        ]
        cursor.executemany(
            "INSERT INTO transactions (id, account_id, amount, date, merchant_name, category, notes, pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            sample_tx,
        )

    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        sample_cats = [
            ("cat_groceries", "Groceries", "grp_food", "Food & Dining", "🛒", 1, "demo"),
            ("cat_dining", "Dining", "grp_food", "Food & Dining", "🍽️", 1, "demo"),
            ("cat_coffee", "Coffee Shops", "grp_food", "Food & Dining", "☕", 0, "demo"),
            ("cat_gas", "Gas & EV Charging", "grp_auto", "Auto & Transport", "⛽", 1, "demo"),
            ("cat_streaming", "Streaming & Entertainment", "grp_ent", "Entertainment", "📺", 0, "demo"),
            ("cat_ai_tools", "AI & Software", "grp_tech", "Tech & Subscriptions", "🤖", 0, "demo"),
            ("cat_housing", "Rent / Mortgage", "grp_home", "Housing", "🏠", 1, "demo"),
            ("cat_utilities", "Utilities & Bills", "grp_home", "Housing", "💡", 1, "demo"),
        ]
        cursor.executemany(
            "INSERT INTO categories (id, name, group_id, group_name, icon, is_system, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            sample_cats,
        )

    cursor.execute("SELECT COUNT(*) FROM budgets")
    if cursor.fetchone()[0] == 0:
        sample_budgets = [
            ("bgt_groceries", "cat_groceries", "Groceries", 600.00, 420.50, 179.50, "current", "demo"),
            ("bgt_dining", "cat_dining", "Dining", 400.00, 310.20, 89.80, "current", "demo"),
            ("bgt_gas", "cat_gas", "Gas & EV Charging", 150.00, 120.00, 30.00, "current", "demo"),
            ("bgt_streaming", "cat_streaming", "Streaming & Entertainment", 80.00, 54.97, 25.03, "current", "demo"),
            ("bgt_ai_tools", "cat_ai_tools", "AI & Software", 120.00, 60.00, 60.00, "current", "demo"),
        ]
        cursor.executemany(
            "INSERT INTO budgets (id, category_id, category_name, amount, spent, remaining, period, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            sample_budgets,
        )

    cursor.execute("SELECT COUNT(*) FROM recurring_bills")
    if cursor.fetchone()[0] == 0:
        sample_bills = [
            ("rec_spotify", "Spotify", "Streaming & Entertainment", 14.99, "monthly", "2026-09-10", "active", "acc_credit", "demo"),
            ("rec_claude", "Anthropic Claude Pro", "AI & Software", 20.00, "monthly", "2026-09-01", "active", "acc_credit", "demo"),
            ("rec_cursor", "Cursor AI", "AI & Software", 20.00, "monthly", "2026-09-04", "active", "acc_credit", "demo"),
            ("rec_pge", "PG&E Electric & Gas", "Utilities & Bills", 145.00, "monthly", "2026-09-18", "active", "acc_checking", "demo"),
            ("rec_icloud", "Apple iCloud 2TB", "Tech & Subscriptions", 9.99, "monthly", "2026-09-15", "active", "acc_credit", "demo"),
        ]
        cursor.executemany(
            "INSERT INTO recurring_bills (id, merchant_name, category_name, amount, frequency, next_date, status, account_id, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            sample_bills,
        )


# ── cards ────────────────────────────────────────────────────────────

def get_all_cards() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, issuer, reward_structure, spend_cap_monthly, quarterly_category, notes FROM cards"
        )
        cards = []
        for row in cursor.fetchall():
            cards.append({
                "id": row["id"],
                "name": row["name"],
                "issuer": row["issuer"],
                "rewards": json.loads(row["reward_structure"]),
                "spend_cap_monthly": row["spend_cap_monthly"],
                "quarterly_category": row["quarterly_category"],
                "notes": row["notes"],
            })
        return cards


def save_card(
    card_id: str,
    name: str,
    issuer: str,
    rewards: Dict[str, float],
    spend_cap: float = 0,
    quarterly: str = "",
    notes: str = "",
) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cards (id, name, issuer, reward_structure, spend_cap_monthly, quarterly_category, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                issuer=excluded.issuer,
                reward_structure=excluded.reward_structure,
                spend_cap_monthly=excluded.spend_cap_monthly,
                quarterly_category=excluded.quarterly_category,
                notes=excluded.notes
            """,
            (card_id, name, issuer, json.dumps(rewards), spend_cap, quarterly, notes),
        )
        conn.commit()


def delete_card(card_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        conn.commit()
        return cursor.rowcount > 0


# ── categories ───────────────────────────────────────────────────────

def get_all_categories() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, group_id, group_name, icon, is_system, source, updated_at "
            "FROM categories ORDER BY group_name, name"
        )
        return [dict(row) for row in cursor.fetchall()]


def find_category(query: str, *, monarch_only: bool = False) -> Optional[Dict[str, Any]]:
    """Resolve a category by id, exact name, then substring.

    When ``monarch_only`` is True, demo-seeded rows are ignored so a mutation
    cannot accidentally send ``cat_dining`` to Monarch GraphQL.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        source_sql = " AND source = 'monarch'" if monarch_only else ""
        cursor.execute(f"SELECT * FROM categories WHERE id = ?{source_sql}", (query,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        cursor.execute(
            f"SELECT * FROM categories WHERE LOWER(name) = LOWER(?){source_sql}",
            (query,),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        cursor.execute(
            f"SELECT * FROM categories WHERE LOWER(name) LIKE LOWER(?){source_sql} LIMIT 1",
            (f"%{query}%",),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def save_category(
    cat_id: str,
    name: str,
    group_id: Optional[str] = None,
    group_name: Optional[str] = None,
    icon: str = "📁",
    is_system: bool = False,
    source: str = "monarch",
) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO categories (id, name, group_id, group_name, icon, is_system, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                group_id=excluded.group_id,
                group_name=excluded.group_name,
                icon=excluded.icon,
                is_system=excluded.is_system,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP
            """,
            (cat_id, name, group_id, group_name, icon, 1 if is_system else 0, source),
        )
        conn.commit()


def delete_category_from_db(category_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        return cursor.rowcount > 0


# ── budgets ──────────────────────────────────────────────────────────

def get_all_budgets(period: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        if period:
            cursor.execute("SELECT * FROM budgets WHERE period = ? ORDER BY amount DESC", (period,))
        else:
            cursor.execute("SELECT * FROM budgets ORDER BY amount DESC")
        return [dict(row) for row in cursor.fetchall()]


def save_budget(
    budget_id: str,
    category_id: str,
    category_name: str,
    amount: float,
    spent: float = 0.0,
    remaining: float = 0.0,
    period: str = "current",
    source: str = "monarch",
) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO budgets (id, category_id, category_name, amount, spent, remaining, period, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                category_id=excluded.category_id,
                category_name=excluded.category_name,
                amount=excluded.amount,
                spent=excluded.spent,
                remaining=excluded.remaining,
                period=excluded.period,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP
            """,
            (budget_id, category_id, category_name, amount, spent, remaining, period, source),
        )
        conn.commit()


# ── recurring bills ──────────────────────────────────────────────────

def get_all_recurring_bills() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recurring_bills ORDER BY amount DESC")
        return [dict(row) for row in cursor.fetchall()]


def save_recurring_bill(
    bill_id: str,
    merchant_name: str,
    category_name: Optional[str],
    amount: float,
    frequency: str = "monthly",
    next_date: Optional[str] = None,
    status: str = "active",
    account_id: Optional[str] = None,
    source: str = "monarch",
) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO recurring_bills (id, merchant_name, category_name, amount, frequency, next_date, status, account_id, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                merchant_name=excluded.merchant_name,
                category_name=excluded.category_name,
                amount=excluded.amount,
                frequency=excluded.frequency,
                next_date=excluded.next_date,
                status=excluded.status,
                account_id=excluded.account_id,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP
            """,
            (bill_id, merchant_name, category_name, amount, frequency, next_date, status, account_id, source),
        )
        conn.commit()


# ── transactions ─────────────────────────────────────────────────────

def get_transaction(tx_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        return dict(row) if row else None


def save_transaction(
    tx_id: str,
    account_id: Optional[str],
    amount: float,
    date: str,
    merchant_name: str,
    category: Optional[str] = None,
    notes: str = "",
    pending: bool = False,
    source: str = "monarch",
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO transactions
                (id, account_id, amount, date, merchant_name, category, notes, pending, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                account_id=excluded.account_id,
                amount=excluded.amount,
                date=excluded.date,
                merchant_name=excluded.merchant_name,
                category=excluded.category,
                notes=excluded.notes,
                pending=excluded.pending,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                tx_id,
                account_id,
                amount,
                date,
                merchant_name,
                category,
                notes,
                1 if pending else 0,
                source,
            ),
        )
        conn.commit()


def update_transaction_in_db(
    tx_id: str,
    category: Optional[str] = None,
    merchant_name: Optional[str] = None,
    notes: Optional[str] = None,
) -> bool:
    updates, params = [], []
    if category is not None:
        updates.append("category = ?")
        params.append(category)
    if merchant_name is not None:
        updates.append("merchant_name = ?")
        params.append(merchant_name)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)
    if not updates:
        return False
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(tx_id)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE transactions SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return cursor.rowcount > 0


def search_transactions(query: Optional[str] = None, limit: int = 15) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        cur = conn.cursor()
        if query:
            pattern = f"%{query}%"
            cur.execute(
                "SELECT id, date, merchant_name, category, amount, notes "
                "FROM transactions WHERE merchant_name LIKE ? OR category LIKE ? "
                "ORDER BY date DESC LIMIT ?",
                (pattern, pattern, limit),
            )
        else:
            cur.execute(
                "SELECT id, date, merchant_name, category, amount, notes "
                "FROM transactions ORDER BY date DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]


def spending_by_category(
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    where = ["amount < 0"]
    params: list[Any] = []
    if since:
        where.append("date >= ?")
        params.append(since)
    if until:
        where.append("date <= ?")
        params.append(until)
    if category:
        where.append("LOWER(category) LIKE ?")
        params.append(f"%{category.lower()}%")
    sql = (
        "SELECT category, SUM(ABS(amount)) AS total_spent, COUNT(*) AS tx_count "
        f"FROM transactions WHERE {' AND '.join(where)} "
        "GROUP BY category ORDER BY total_spent DESC"
    )
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [
            {
                "category": row[0],
                "total_spent": round(row[1] or 0.0, 2),
                "transactions": row[2],
            }
            for row in cur.fetchall()
        ]




def search_transactions_advanced(
    query: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
    account_id: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    pending_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Enhanced transaction search with date range, amount, and account filters."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    where_clauses = []
    params: list[Any] = []

    if query:
        where_clauses.append("(merchant_name LIKE ? OR category LIKE ? OR notes LIKE ?)")
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])
    if since:
        where_clauses.append("date >= ?")
        params.append(since)
    if until:
        where_clauses.append("date <= ?")
        params.append(until)
    if category:
        where_clauses.append("LOWER(category) LIKE ?")
        params.append(f"%{category.lower()}%")
    if account_id:
        where_clauses.append("account_id = ?")
        params.append(account_id)
    if min_amount is not None:
        where_clauses.append("ABS(amount) >= ?")
        params.append(abs(min_amount))
    if max_amount is not None:
        where_clauses.append("ABS(amount) <= ?")
        params.append(abs(max_amount))
    if pending_only:
        where_clauses.append("pending = 1")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_db() as conn:
        cur = conn.cursor()
        count_sql = f"SELECT COUNT(*) FROM transactions {where_sql}"
        cur.execute(count_sql, params)
        total_count = cur.fetchone()[0]

        data_sql = (
            f"SELECT id, account_id, amount, date, merchant_name, category, notes, pending "
            f"FROM transactions {where_sql} ORDER BY date DESC LIMIT ? OFFSET ?"
        )
        cur.execute(data_sql, params + [limit, offset])
        results = [dict(row) for row in cur.fetchall()]

    return {
        "transactions": results,
        "count": len(results),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
    }


def get_cashflow_summary(
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Local cashflow summary from the SQLite store."""
    where_clauses = []
    params: list[Any] = []
    if since:
        where_clauses.append("date >= ?")
        params.append(since)
    if until:
        where_clauses.append("date <= ?")
        params.append(until)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT SUM(CASE WHEN amount >= 0 THEN amount ELSE 0 END) AS total_income, "
            f"SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS total_expenses, "
            f"COUNT(*) AS tx_count "
            f"FROM transactions {where_sql}",
            params,
        )
        row = cur.fetchone()
        income = round(row[0] or 0.0, 2)
        expenses = round(row[1] or 0.0, 2)
        tx_count = row[2] or 0

        cur.execute(
            f"SELECT category, SUM(ABS(amount)) AS total_spent "
            f"FROM transactions WHERE amount < 0 {' AND ' + ' AND '.join(where_clauses) if where_clauses else ''} "
            f"GROUP BY category ORDER BY total_spent DESC LIMIT 10",
            params,
        )
        top_cats = [
            {"category": r[0], "amount": round(r[1], 2)} for r in cur.fetchall()
        ]

    return {
        "total_income": income,
        "total_expenses": expenses,
        "net_cashflow": round(income - expenses, 2),
        "savings_rate": round((income - expenses) / income * 100, 1) if income else 0.0,
        "top_expense_categories": top_cats,
        "transaction_count": tx_count,
        "window": {"since": since, "until": until},
    }


def get_financial_summary() -> Dict[str, Any]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT type, SUM(current_balance) FROM accounts GROUP BY type")
        breakdown = {row[0]: round(row[1] or 0.0, 2) for row in cur.fetchall()}
        assets = 0.0
        liabilities = 0.0
        for acc_type, total in breakdown.items():
            if acc_type in LIABILITY_TYPES:
                liabilities += abs(total or 0.0)
            else:
                assets += total or 0.0
        cur.execute("SELECT COUNT(*) FROM transactions")
        tx_count = cur.fetchone()[0] or 0
    return {
        "net_worth": round(assets - liabilities, 2),
        "total_assets": round(assets, 2),
        "total_liabilities": round(liabilities, 2),
        "assets": round(assets, 2),
        "liabilities": round(liabilities, 2),
        "breakdown": breakdown,
        "total_transactions": tx_count,
    }


# ── auth tokens ──────────────────────────────────────────────────────

def get_auth_value(key: str) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM auth_tokens WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_auth_value(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO auth_tokens (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value),
        )
        conn.commit()


def clear_auth_value(key: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE key = ?", (key,))
        conn.commit()


# ── provenance ───────────────────────────────────────────────────────

def get_sync_state() -> Dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        state = dict(row) if row else {"source": "demo", "last_status": "never_synced"}
    state["is_demo"] = state.get("source") != "monarch"
    return state


def provenance() -> Dict[str, Any]:
    st = get_sync_state()
    if st["is_demo"]:
        note = (
            "DEMO DATA — these are seeded sample figures, NOT real accounts. "
            "Run monarch_setup then sync_monarch to use real data. Do not "
            "report these numbers to the user as their actual finances."
        )
    else:
        note = f"Real Monarch data, last synced {st['last_sync_at']} UTC."
    return {
        "is_demo": st["is_demo"],
        "source": st["source"],
        "last_sync_at": st["last_sync_at"],
        "last_status": st["last_status"],
        "note": note,
    }


def set_sync_state(
    *,
    source: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
    accounts: Optional[int] = None,
    transactions: Optional[int] = None,
    stamp_time: bool = False,
) -> None:
    sets, params = [], []
    if source is not None:
        sets.append("source = ?")
        params.append(source)
    if status is not None:
        sets.append("last_status = ?")
        params.append(status)
    sets.append("last_error = ?")
    params.append(error)
    if accounts is not None:
        sets.append("synced_accounts = ?")
        params.append(accounts)
    if transactions is not None:
        sets.append("synced_transactions = ?")
        params.append(transactions)
    if stamp_time:
        sets.append("last_sync_at = CURRENT_TIMESTAMP")
    with get_db() as conn:
        conn.execute(f"UPDATE sync_state SET {', '.join(sets)} WHERE id = 1", params)
        conn.commit()


def purge_demo_data() -> Dict[str, int]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM transactions WHERE source = 'demo'")
        tx = cur.rowcount
        cur.execute("DELETE FROM accounts WHERE source = 'demo'")
        acc = cur.rowcount
        cur.execute("DELETE FROM categories WHERE source = 'demo'")
        cat = cur.rowcount
        cur.execute("DELETE FROM budgets WHERE source = 'demo'")
        bgt = cur.rowcount
        cur.execute("DELETE FROM recurring_bills WHERE source = 'demo'")
        rec = cur.rowcount
        conn.commit()
    return {
        "accounts_removed": acc,
        "transactions_removed": tx,
        "categories_removed": cat,
        "budgets_removed": bgt,
        "recurring_bills_removed": rec,
    }
