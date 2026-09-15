"""CLI interface for Jaeger Personal Finance Assistant (`jaeger finance`)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .approval import ApprovalEngine
from .briefing import BriefingEngine
from .budget import BudgetEngine
from .cashflow import CashFlowEngine
from .classifier import TransactionClassifier
from .memory import FinanceMemory
from .models import ReviewStatus
from .providers.importer import ImportProvider
from .providers.monarch import MonarchProvider
from .store import FinanceStore
from .sync import SyncEngine


def _format_json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def cmd_summary(args: argparse.Namespace, store: FinanceStore) -> int:
    cashflow = CashFlowEngine(store)
    runway = cashflow.calculate_runway()
    accounts = store.get_accounts()

    print("\n💳 Financial Summary & Cash Runway")
    print(f"  Net Worth:        ${runway['net_worth']:,.2f}")
    print(f"  Liquid Checking:  ${runway['liquid_checking']:,.2f} (~{runway['checking_runway_days']} days runway)")
    print(f"  Liquid Savings:   ${runway['liquid_savings']:,.2f}")
    print(f"  Credit Card Debt: ${runway['credit_card_debt']:,.2f}")
    print(f"  Total Accounts:   {len(accounts)}")
    if runway.get("shortfall_warning"):
        print(f"\n  ⚠️  Notice: {runway['shortfall_warning']}")
    print()
    return 0


def cmd_briefing(args: argparse.Namespace, store: FinanceStore) -> int:
    briefing = BriefingEngine(store)
    cadence = getattr(args, "cadence", "weekly") or "weekly"
    if cadence == "daily":
        res = briefing.generate_daily_briefing()
    elif cadence == "monthly":
        res = briefing.generate_monthly_close()
    else:
        res = briefing.generate_weekly_briefing()
    print("\n" + res["markdown"] + "\n")
    return 0


def cmd_inbox(args: argparse.Namespace, store: FinanceStore) -> int:
    classifier = TransactionClassifier(store)
    classifier.classify_all_new()
    inbox = classifier.get_inbox_items()

    print(f"\n📥 Transaction Review Inbox ({len(inbox)} items requiring attention)\n")
    if not inbox:
        print("  ✅ Inbox is clear. No unreviewed transactions or anomalies.")
        print()
        return 0

    for i, item in enumerate(inbox[:15], 1):
        tx = item["transaction"]
        action = item["proposed_action"]
        reasons = ", ".join(item["reasons"])
        print(f"  [{i}] {tx['date']} | ${tx['amount']:,.2f} | {tx['merchant']}")
        print(f"      Account:  {tx['account_name'] or tx['account_id']}")
        print(f"      Reasons:  {reasons}")
        print(f"      Proposed: {action['category']} (Confidence: {int(action['confidence'] * 100)}%)")
        print(f"      Reason:   {action['explanation']}")
        print()
    return 0


def cmd_sync(args: argparse.Namespace, store: FinanceStore) -> int:
    print("\n🔄 Synchronizing financial data...")
    monarch = MonarchProvider()
    if monarch.is_available():
        provider: Any = monarch
        print("  Using Monarch Money provider.")
    else:
        provider = ImportProvider()
        print("  Using local import/cached provider (Monarch session missing).")

    engine = SyncEngine(store, provider)
    summary = asyncio.run(engine.sync(days=args.days))
    if summary.ok:
        classifier = TransactionClassifier(store)
        classified = classifier.classify_all_new()
        print(f"  ✅ Sync complete: {summary.transactions_synced} transactions ingested ({summary.duplicates_skipped} duplicates skipped).")
        print(f"  ✅ Classified {classified} new transactions.")
    else:
        print(f"  ❌ Sync failed: {summary.error}")
    print()
    return 0 if summary.ok else 1


def cmd_import(args: argparse.Namespace, store: FinanceStore) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"❌ File not found: {path}")
        return 1

    print(f"\n📥 Importing transactions from {path.name}...")
    importer = ImportProvider(csv_path=path)
    engine = SyncEngine(store, importer)
    summary = asyncio.run(engine.sync())
    classifier = TransactionClassifier(store)
    classified = classifier.classify_all_new()

    print(f"  ✅ Ingested {summary.transactions_synced} transactions ({summary.duplicates_skipped} duplicates skipped).")
    print(f"  ✅ Classified {classified} transactions.")
    print()
    return 0


def cmd_seed_demo(args: argparse.Namespace, store: FinanceStore) -> int:
    print("\n🌱 Seeding 100% synthetic demonstration data (zero external credentials required)...")
    importer = ImportProvider.create_synthetic_fixture()
    engine = SyncEngine(store, importer)
    summary = asyncio.run(engine.sync())
    classifier = TransactionClassifier(store)
    classified = classifier.classify_all_new()

    print(f"  ✅ Seeded {summary.accounts_synced} accounts, {summary.transactions_synced} transactions, and {summary.budgets_synced} budgets.")
    print(f"  ✅ Classified {classified} transactions.")
    print("  Run `jaeger finance briefing` or `jaeger finance inbox` to explore.\n")
    return 0


def cmd_purge(args: argparse.Namespace, store: FinanceStore) -> int:
    if not args.force:
        print("⚠️  Warning: This will permanently delete all locally stored financial records, accounts, and audit entries.")
        print("   To proceed, re-run with --force.")
        return 1
    store.purge_all()
    print("✅ All local financial records have been purged securely.\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jaeger finance",
        description="Private, Mac-based Home Finance Assistant (Monarch Copilot)",
    )
    sub = parser.add_subparsers(dest="command", help="Financial command")

    # summary
    sub.add_parser("summary", help="Show net worth, liquid cash, debt, and cash-flow runway")

    # briefing
    p_briefing = sub.add_parser("briefing", help="Generate executive financial briefing")
    p_briefing.add_argument("--daily", dest="cadence", action="store_const", const="daily")
    p_briefing.add_argument("--weekly", dest="cadence", action="store_const", const="weekly", default="weekly")
    p_briefing.add_argument("--monthly", dest="cadence", action="store_const", const="monthly")

    # inbox
    sub.add_parser("inbox", help="Review unreviewed charges, duplicates, and classification suggestions")

    # sync
    p_sync = sub.add_parser("sync", help="Synchronize accounts and transactions idempotently")
    p_sync.add_argument("--days", type=int, default=30, help="Days of history to fetch")

    # import
    p_import = sub.add_parser("import", help="Import transactions from Monarch CSV export")
    p_import.add_argument("path", help="Path to CSV file")

    # seed-demo
    sub.add_parser("seed-demo", help="Seed realistic synthetic demonstration data")

    # purge
    p_purge = sub.add_parser("purge", help="Purge all local financial records (Privacy control)")
    p_purge.add_argument("--force", action="store_true", help="Confirm deletion")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    store = FinanceStore()

    dispatch = {
        "summary": cmd_summary,
        "briefing": cmd_briefing,
        "inbox": cmd_inbox,
        "sync": cmd_sync,
        "import": cmd_import,
        "seed-demo": cmd_seed_demo,
        "purge": cmd_purge,
    }

    handler = dispatch.get(args.command)
    if handler:
        return handler(args, store)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
