"""Anomaly detector: duplicate charges, spend spikes, price hikes, and new merchants."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from .models import Transaction
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.anomaly")

LARGE_TRANSACTION_THRESHOLD = 150.0


class AnomalyDetector:
    """Scans transactions to detect duplicates, large spikes, fee increases, and new merchants."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    def detect_anomalies(self, days: int = 30) -> dict[str, Any]:
        txs = self.store.get_transactions(limit=500)
        duplicates: list[dict[str, Any]] = []
        large_transactions: list[dict[str, Any]] = []
        uncategorized: list[dict[str, Any]] = []
        fee_charges: list[dict[str, Any]] = []
        subscription_hikes: list[dict[str, Any]] = []

        # 1. Exact / Fuzzy duplicate detection
        seen_charges: dict[str, list[Transaction]] = defaultdict(list)
        for tx in txs:
            if tx.is_transfer:
                continue
            key = f"{tx.merchant.lower().strip()}:{abs(tx.amount):.2f}"
            seen_charges[key].append(tx)

        for key, group in seen_charges.items():
            if len(group) > 1:
                # Flag as potential duplicate
                primary = group[0]
                for dup in group[1:]:
                    duplicates.append({
                        "original_id": primary.id,
                        "duplicate_id": dup.id,
                        "merchant": dup.merchant,
                        "amount": dup.amount,
                        "date1": primary.date,
                        "date2": dup.date,
                        "account": dup.account_name,
                    })

        # 2. Large transactions & Uncategorized & Fees
        merchant_history: dict[str, list[float]] = defaultdict(list)
        for tx in txs:
            amt = abs(tx.amount)
            m_lower = tx.merchant.lower()
            merchant_history[m_lower].append(amt)

            if amt >= LARGE_TRANSACTION_THRESHOLD and not tx.is_transfer:
                large_transactions.append(tx.to_dict())

            cat_clean = (tx.category or "").lower()
            if not cat_clean or cat_clean in {"uncategorized", "unknown", "needs review"}:
                uncategorized.append(tx.to_dict())

            if any(f in m_lower for f in ("fee", "interest charge", "service charge", "overdraft")):
                fee_charges.append(tx.to_dict())

        # 3. Detect subscription / recurring price increases
        for m_name, amounts in merchant_history.items():
            if len(amounts) >= 2:
                # If amounts differed and increased
                latest = amounts[0]
                prior = amounts[1]
                if latest > prior and (latest - prior) >= 1.0:
                    # Check if looks like recurring subscription
                    if any(k in m_name for k in ("netflix", "spotify", "apple", "prime", "gym", "sub", "cloud")):
                        subscription_hikes.append({
                            "merchant": m_name.title(),
                            "prior_amount": prior,
                            "current_amount": latest,
                            "increase": round(latest - prior, 2),
                        })

        return {
            "duplicate_count": len(duplicates),
            "duplicates": duplicates[:10],
            "large_count": len(large_transactions),
            "large_transactions": large_transactions[:10],
            "uncategorized_count": len(uncategorized),
            "uncategorized": uncategorized[:10],
            "fee_count": len(fee_charges),
            "fee_charges": fee_charges[:10],
            "subscription_hike_count": len(subscription_hikes),
            "subscription_hikes": subscription_hikes,
        }
