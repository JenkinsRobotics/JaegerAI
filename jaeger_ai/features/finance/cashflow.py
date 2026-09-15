"""Cash flow engine: liquidity runway, upcoming obligations, and shortfall warnings."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import AccountType
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.cashflow")


class CashFlowEngine:
    """Evaluates checking balances, recurring obligations, and liquidity runway."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    def calculate_runway(self, days_ahead: int = 30) -> dict[str, Any]:
        """Project liquidity and forecast whether upcoming bills could cause a shortfall."""
        accounts = self.store.get_accounts()

        liquid_checking = 0.0
        liquid_savings = 0.0
        credit_card_debt = 0.0
        loan_debt = 0.0
        investments = 0.0

        for acct in accounts:
            bal = acct.balance
            if acct.type == AccountType.DEPOSITORY:
                if "checking" in acct.name.lower():
                    liquid_checking += bal
                else:
                    liquid_savings += bal
            elif acct.type == AccountType.CREDIT:
                credit_card_debt += abs(bal)
            elif acct.type == AccountType.LOAN:
                loan_debt += abs(bal)
            elif acct.type == AccountType.INVESTMENT:
                investments += bal

        total_liquid = liquid_checking + liquid_savings
        net_worth = total_liquid + investments - (credit_card_debt + loan_debt)

        # Estimate average monthly outflow from recent non-transfer transactions
        txs = self.store.get_transactions(limit=500)
        expense_txs = [t for t in txs if t.amount > 0 and not t.is_transfer]

        total_recent_spend = sum(t.amount for t in expense_txs)
        # Approximate 30-day burn rate
        burn_rate_30d = total_recent_spend if total_recent_spend > 0 else 3500.0
        daily_burn = burn_rate_30d / 30.0

        runway_days_checking = int(liquid_checking / daily_burn) if daily_burn > 0 else 999
        runway_days_total = int(total_liquid / daily_burn) if daily_burn > 0 else 999

        shortfall_warning = None
        if liquid_checking < credit_card_debt:
            shortfall_warning = (
                f"Liquid checking (${liquid_checking:,.2f}) is lower than current credit card balances "
                f"(${credit_card_debt:,.2f}). Paying off credit card balances in full would require "
                f"drawing ${credit_card_debt - liquid_checking:,.2f} from savings."
            )
        elif runway_days_checking < 14:
            shortfall_warning = (
                f"Checking account runway is only {runway_days_checking} days based on current spending pace. "
                "Upcoming bills may require a transfer from savings."
            )

        return {
            "liquid_checking": round(liquid_checking, 2),
            "liquid_savings": round(liquid_savings, 2),
            "total_liquid": round(total_liquid, 2),
            "credit_card_debt": round(credit_card_debt, 2),
            "loan_debt": round(loan_debt, 2),
            "investments": round(investments, 2),
            "net_worth": round(net_worth, 2),
            "estimated_daily_burn": round(daily_burn, 2),
            "checking_runway_days": runway_days_checking,
            "total_liquid_runway_days": runway_days_total,
            "shortfall_warning": shortfall_warning,
        }
