"""Pre-configured durable financial review mission for JaegerAI."""

from __future__ import annotations

from typing import Any

from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore

from jaeger_ai.features.missions.service import MissionService


def create_financial_audit_mission(store: Any = None) -> dict[str, Any]:
    """Create a structured durable mission for an end-to-end financial health audit."""
    if store is None:
        store = SqliteCommitmentStore()
    service = MissionService(store)
    return service.create(
        title="Weekly Financial Health & Budget Pacing Audit",
        goals=[
            {
                "title": "Account Balancing & Net Worth Ingestion",
                "steps": [
                    "Fetch live balances across depository, investment, and debt accounts via Monarch",
                    "Verify total liquid cash and available emergency runway",
                ],
            },
            {
                "title": "Budget Category Pacing Review",
                "steps": [
                    "Calculate elapsed percentage of current billing cycle",
                    "Compare actual spending vs budgeted limits across all envelopes",
                    "Flag categories pacing more than 15% ahead of schedule",
                ],
            },
            {
                "title": "Transaction Anomaly & Duplicate Detection",
                "steps": [
                    "Scan 7-day cleared and pending transactions for duplicate charges",
                    "Highlight high-value transactions (> $150)",
                    "Queue unreviewed or uncategorized charges for operator confirmation",
                ],
            },
            {
                "title": "Knowledge & Shared Memory Sync",
                "steps": [
                    "Persist executive briefing into Honcho shared memory",
                    "Surface actionable alerts to desktop notification or chat transcript",
                ],
            },
        ],
        metadata={"category": "finance", "automation": "weekly_scheduled"},
    )
