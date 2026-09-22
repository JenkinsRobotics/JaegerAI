"""Optional live smoke against Monarch. Never mutates.

Run with:
    ARES_FINANCE_LIVE=1 ./.venv/bin/pytest -m live
"""

from __future__ import annotations

import asyncio
import os

import pytest

from server.engine.monarch_sync import MonarchSyncService

pytestmark = pytest.mark.live


def test_live_status_does_not_mutate():
    if os.environ.get("ARES_FINANCE_LIVE") != "1":
        pytest.skip("Set ARES_FINANCE_LIVE=1 (plus Monarch credentials/session) to hit the real API.")
    svc = MonarchSyncService()
    result = asyncio.run(svc.get_institution_health())
    assert result["status"] in {
        "success",
        "not_configured",
        "login_failed",
        "mfa_required",
        "network_error",
        "sdk_missing",
        "failed",
    }
    if result["status"] == "success":
        assert "total_institutions" in result
        cats = asyncio.run(svc.get_categories(sync_to_db=False))
        assert cats.get("status") == "success"
        assert isinstance(cats.get("categories"), list)
