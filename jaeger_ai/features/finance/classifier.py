"""Hierarchical, explainable transaction classifier and review inbox manager."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from .models import ReviewStatus, Rule, Transaction
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.classifier")

# Common recurring subscription keywords
RECURRING_PATTERNS: dict[str, tuple[str, list[str]]] = {
    "netflix": ("Subscriptions", ["streaming", "entertainment"]),
    "spotify": ("Subscriptions", ["streaming", "music"]),
    "apple.com/bill": ("Subscriptions", ["apple", "software"]),
    "google *storage": ("Subscriptions", ["cloud", "software"]),
    "amazon prime": ("Subscriptions", ["shopping", "annual"]),
    "github": ("Subscriptions", ["dev", "software"]),
    "gym": ("Fitness", ["gym", "health"]),
    "planet fitness": ("Fitness", ["gym", "health"]),
    "equinox": ("Fitness", ["gym", "health"]),
    "electric": ("Utilities", ["home", "electric"]),
    "coned": ("Utilities", ["home", "electric"]),
    "water": ("Utilities", ["home", "water"]),
}

# Transfer / Credit Card Payment patterns
TRANSFER_PATTERNS = [
    re.compile(r"credit\s*card\s*payment", re.IGNORECASE),
    re.compile(r"autopay\s*(payment)?", re.IGNORECASE),
    re.compile(r"chase\s*credit\s*crd\s*epay", re.IGNORECASE),
    re.compile(r"payment\s*to\s*chase", re.IGNORECASE),
    re.compile(r"payment\s*to\s*amex", re.IGNORECASE),
    re.compile(r"american\s*express\s*payment", re.IGNORECASE),
    re.compile(r"online\s*banking\s*transfer", re.IGNORECASE),
    re.compile(r"transfer\s*to\s*share", re.IGNORECASE),
    re.compile(r"venmo\s*cashout", re.IGNORECASE),
]


class TransactionClassifier:
    """Classifies transactions using a strict 7-tier confidence hierarchy."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    def detect_transfer(self, tx: Transaction) -> bool:
        """Identify credit card payments and transfers to prevent double counting."""
        if tx.is_transfer:
            return True
        text = f"{tx.merchant} {tx.raw_statement} {tx.notes}".lower()
        for pat in TRANSFER_PATTERNS:
            if pat.search(text):
                return True
        if "credit card payment" in tx.category.lower():
            return True
        return False

    def classify_transaction(self, tx: Transaction) -> Transaction:
        """Apply the 7-tier classification hierarchy to a single transaction."""
        # Check transfer first
        if self.detect_transfer(tx):
            tx.is_transfer = True
            tx.suggested_category = "Credit Card Payment"
            tx.classification_confidence = 0.95
            tx.classification_explanation = (
                "Deterministic rule: detected as credit card payment or account transfer. Excluded from spending totals."
            )
            return tx

        text_to_match = f"{tx.merchant} {tx.raw_statement}".lower()

        # Tier 1: Exact user-approved merchant rule
        rules = self.store.get_rules()
        for rule in rules:
            if rule.approved_by_user and rule.pattern.lower() in text_to_match:
                tx.suggested_category = rule.target_category
                tx.classification_confidence = max(rule.confidence, 0.95)
                tx.classification_explanation = f"Tier 1: Matches exact user-approved rule '{rule.name}'."
                tx.matching_rule_id = rule.id
                if rule.target_tags:
                    tx.tags = list(set(tx.tags + rule.target_tags))
                return tx

        # Tier 2: Existing Monarch rule / category
        if tx.category and tx.category.lower() not in {"uncategorized", "unknown", "needs review", ""}:
            tx.suggested_category = tx.category
            tx.classification_confidence = 0.85
            tx.classification_explanation = f"Tier 2: Retained existing Monarch category '{tx.category}'."
            return tx

        # Tier 3: Known recurring-transaction rule
        for pat_str, (cat_target, tags_target) in RECURRING_PATTERNS.items():
            if pat_str in text_to_match:
                tx.suggested_category = cat_target
                tx.classification_confidence = 0.85
                tx.classification_explanation = f"Tier 3: Matches known recurring service pattern for '{pat_str}'."
                tx.tags = list(set(tx.tags + tags_target))
                return tx

        # Tier 4: Historical pattern for the same merchant and account
        all_prior = self.store.get_transactions(limit=500)
        merchant_prior = [
            p for p in all_prior
            if p.merchant.lower() == tx.merchant.lower()
            and p.category
            and p.category.lower() not in {"uncategorized", "unknown", "needs review", ""}
            and p.id != tx.id
        ]
        if len(merchant_prior) >= 2:
            cat_counts: dict[str, int] = {}
            for p in merchant_prior:
                cat_counts[p.category] = cat_counts.get(p.category, 0) + 1
            top_cat, top_count = max(cat_counts.items(), key=lambda x: x[1])
            consistency = top_count / len(merchant_prior)
            if consistency >= 0.80:
                tx.suggested_category = top_cat
                tx.classification_confidence = round(0.75 + (consistency * 0.15), 2)
                tx.classification_explanation = (
                    f"Tier 4: Historical pattern: {int(consistency * 100)}% of prior charges at {tx.merchant} "
                    f"were categorized as '{top_cat}' ({top_count}/{len(merchant_prior)})."
                )
                return tx

        # Tier 5: Deterministic metadata rule (Keywords)
        merchant_lower = tx.merchant.lower()
        if any(k in merchant_lower for k in ("trader joe", "safeway", "kroger", "whole foods", "grocery")):
            tx.suggested_category = "Groceries"
            tx.classification_confidence = 0.88
            tx.classification_explanation = "Tier 5: Deterministic metadata: merchant is a known grocery retailer."
            return tx
        if any(k in merchant_lower for k in ("restaurant", "cafe", "coffee", "bistro", "starbucks", "diner")):
            tx.suggested_category = "Dining"
            tx.classification_confidence = 0.85
            tx.classification_explanation = "Tier 5: Deterministic metadata: merchant is a known dining/cafe venue."
            return tx
        if any(k in merchant_lower for k in ("chevron", "shell", "exxon", "gas station", "fuel")):
            tx.suggested_category = "Auto & Gas"
            tx.classification_confidence = 0.88
            tx.classification_explanation = "Tier 5: Deterministic metadata: merchant is a fuel provider."
            return tx

        # Tier 6: Model-generated / Heuristic suggestion
        # Safe fallback without external cloud call
        tx.suggested_category = "General Merchandise" if tx.amount > 0 else "Income"
        tx.classification_confidence = 0.50
        tx.classification_explanation = (
            "Tier 6: Heuristic suggestion. Low confidence; please review in Transaction Inbox."
        )

        # Tier 7: Flag for Review in Inbox
        tx.review_status = ReviewStatus.NEW
        return tx

    def classify_all_new(self) -> int:
        """Classify all unreviewed transactions currently in store."""
        new_txs = self.store.get_transactions(review_status=ReviewStatus.NEW, limit=500)
        updated_count = 0
        for tx in new_txs:
            classified = self.classify_transaction(tx)
            # If high-confidence (>= 0.90) and matches Tier 1 rule, can auto-label
            if classified.classification_confidence >= 0.90 and classified.matching_rule_id:
                self.store.update_transaction_review(
                    classified.id,
                    status=ReviewStatus.APPROVED,
                    category=classified.suggested_category,
                    tags=classified.tags,
                )
            else:
                self.store.update_transaction_review(
                    classified.id,
                    status=ReviewStatus.NEW,
                    category=classified.suggested_category or classified.category,
                    tags=classified.tags,
                )
            updated_count += 1
        return updated_count

    def get_inbox_items(self) -> list[dict[str, Any]]:
        """Retrieve transactions requiring operator attention."""
        txs = self.store.get_transactions(limit=300)
        inbox: list[dict[str, Any]] = []

        seen_amounts: dict[str, Transaction] = {}

        for tx in txs:
            needs_attention = False
            reasons: list[str] = []

            # 1. New or Uncategorized
            if tx.review_status == ReviewStatus.NEW:
                needs_attention = True
                reasons.append("New unreviewed charge")

            cat_clean = (tx.category or "").lower()
            if not cat_clean or cat_clean in {"uncategorized", "unknown", "needs review"}:
                needs_attention = True
                reasons.append("Uncategorized")

            # 2. Low confidence
            if tx.classification_confidence < 0.80 and tx.classification_confidence > 0.0:
                needs_attention = True
                reasons.append(f"Low confidence ({int(tx.classification_confidence * 100)}%)")

            # 3. Duplicate check
            key = f"{tx.merchant.lower()}:{abs(tx.amount):.2f}"
            if key in seen_amounts:
                needs_attention = True
                reasons.append(f"Potential duplicate of transaction on {seen_amounts[key].date}")
            else:
                seen_amounts[key] = tx

            # 4. Large unexpected charge (> $200)
            if abs(tx.amount) >= 200.0 and not tx.is_transfer:
                reasons.append("High value charge (> $200)")

            if needs_attention:
                inbox.append({
                    "transaction": tx.to_dict(),
                    "reasons": reasons,
                    "proposed_action": {
                        "category": tx.suggested_category or tx.category,
                        "confidence": tx.classification_confidence,
                        "explanation": tx.classification_explanation,
                        "tags": tx.tags,
                    },
                })

        return inbox
