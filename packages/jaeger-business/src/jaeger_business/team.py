"""Autonomous business team roster, budgets, SOP playbooks, and projects (SQLite WAL)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TeamRole:
    role_id: str
    title: str
    mission: str
    default_model: str
    allowed_tools: list[str]
    requires_owner_approval_for: list[str]
    status: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_TEAM_ROLES: tuple[TeamRole, ...] = (
    TeamRole(
        role_id="producer",
        title="Executive Producer / CEO",
        mission="Breaks down owner goals into weekly production plans, assigns team roles, tracks deadlines and budgets.",
        default_model="gemma4:12b",
        allowed_tools=["plan_project", "assign_role", "check_budget", "request_approval"],
        requires_owner_approval_for=["budget_increase", "public_launch", "contract"],
    ),
    TeamRole(
        role_id="researcher",
        title="Audience & Market Researcher",
        mission="Analyzes competitor channels, trends, playlists, viewer retention hooks, and builds the local KB.",
        default_model="gemma4:12b",
        allowed_tools=["youtube_research", "web_search", "memory_recall", "write_brief"],
        requires_owner_approval_for=[],
    ),
    TeamRole(
        role_id="scriptwriter",
        title="Scriptwriter & Copywriter",
        mission="Writes high-retention video scripts, cold opens, titles, descriptions, newsletters, and sponsor reads.",
        default_model="gemma4:12b",
        allowed_tools=["read_brief", "write_script", "ab_title_variants"],
        requires_owner_approval_for=[],
    ),
    TeamRole(
        role_id="designer",
        title="Visual & Thumbnail Designer",
        mission="Designs thumbnail concepts, storyboards, visual b-roll shot lists, and channel brand assets.",
        default_model="qwen3-vl:8b",
        allowed_tools=["generate_storyboard", "inspect_frames", "thumbnail_brief"],
        requires_owner_approval_for=["paid_asset_purchase"],
    ),
    TeamRole(
        role_id="editor",
        title="Video & Audio Studio Editor",
        mission="Assembles multi-track timelines, voiceovers (Kokoro MLX), captions, silence trims, and loudness checks.",
        default_model="gemma4:12b",
        allowed_tools=["build_timeline", "ffmpeg_render", "kokoro_tts", "loudness_check"],
        requires_owner_approval_for=[],
    ),
    TeamRole(
        role_id="publisher",
        title="Publisher & Growth Operator",
        mission="Prepares upload packages, chapters, SEO tags, and schedules releases AFTER explicit owner approval.",
        default_model="gemma4:12b",
        allowed_tools=["prepare_upload_pack", "schedule_release", "analytics_pull"],
        requires_owner_approval_for=["youtube_publish", "social_post", "send_newsletter"],
    ),
    TeamRole(
        role_id="ops",
        title="Community, Ops & Finance",
        mission="Drafts sponsor replies, community responses, invoices, and enforces daily/monthly spend limits.",
        default_model="gemma4:12b",
        allowed_tools=["draft_reply", "log_expense", "channel_notify"],
        requires_owner_approval_for=["send_email", "send_dm", "spend_money"],
    ),
    TeamRole(
        role_id="engineer",
        title="Automation & Software Engineer",
        mission="Builds landing pages, scripts, integrations, and robotics/software demos featured in content.",
        default_model="gemma4:12b",
        allowed_tools=["read_file", "write_file", "run_tests", "git_status"],
        requires_owner_approval_for=["deploy_prod", "git_push"],
    ),
)


@dataclass(slots=True)
class BusinessProject:
    project_id: str
    name: str
    kind: str
    stage: str
    owner_role: str
    budget_usd: float
    spent_usd: float
    approval_required: bool
    approved: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BusinessStore:
    """SQLite WAL backing store for autonomous business teams, budgets, SOPs, and projects."""

    def __init__(self, state_dir: Path, *, daily_spend_cap_usd: float = 25.0) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "business.sqlite3"
        self._lock = threading.RLock()
        self._daily_cap_usd = max(0.0, float(daily_spend_cap_usd))
        self._roles = {r.role_id: r for r in DEFAULT_TEAM_ROLES}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    owner_role TEXT NOT NULL,
                    budget_usd REAL NOT NULL,
                    spent_usd REAL NOT NULL,
                    approval_required INTEGER NOT NULL,
                    approved INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spend_ledger (
                    entry_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    description TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def list_team(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._roles.values()]

    def get_role(self, role_id: str) -> TeamRole | None:
        return self._roles.get(role_id)

    def check_action_requires_approval(self, role_id: str, action: str) -> bool:
        role = self._roles.get(role_id)
        if role is None:
            return True  # fail-closed for unknown role
        if action in role.requires_owner_approval_for:
            return True
        # Universal high-risk external actions always require owner approval
        return action in {
            "youtube_publish",
            "social_post",
            "send_email",
            "send_dm",
            "spend_money",
            "deploy_prod",
            "public_launch",
        }

    def create_project(
        self,
        *,
        name: str,
        kind: str = "youtube_channel",
        stage: str = "planning",
        owner_role: str = "producer",
        budget_usd: float = 50.0,
        approval_required: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> BusinessProject:
        pid = f"biz_{uuid.uuid4().hex[:10]}"
        now = time.time()
        proj = BusinessProject(
            project_id=pid,
            name=name.strip() or "Untitled Business Initiative",
            kind=kind,
            stage=stage,
            owner_role=owner_role if owner_role in self._roles else "producer",
            budget_usd=max(0.0, float(budget_usd)),
            spent_usd=0.0,
            approval_required=bool(approval_required),
            approved=False,
            metadata=dict(metadata or {}),
            updated_at=now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    project_id, name, kind, stage, owner_role, budget_usd,
                    spent_usd, approval_required, approved, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proj.project_id,
                    proj.name,
                    proj.kind,
                    proj.stage,
                    proj.owner_role,
                    proj.budget_usd,
                    proj.spent_usd,
                    1 if proj.approval_required else 0,
                    0,
                    json.dumps(proj.metadata),
                    proj.updated_at,
                ),
            )
        return proj

    def list_projects(self, *, limit: int = 50) -> list[BusinessProject]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT project_id, name, kind, stage, owner_role, budget_usd,
                       spent_usd, approval_required, approved, metadata_json, updated_at
                FROM projects ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            BusinessProject(
                project_id=r[0],
                name=r[1],
                kind=r[2],
                stage=r[3],
                owner_role=r[4],
                budget_usd=float(r[5]),
                spent_usd=float(r[6]),
                approval_required=bool(r[7]),
                approved=bool(r[8]),
                metadata=json.loads(r[9] or "{}"),
                updated_at=float(r[10]),
            )
            for r in rows
        ]

    def record_spend(
        self,
        *,
        project_id: str,
        role_id: str,
        amount_usd: float,
        description: str,
        approved_by: str = "",
    ) -> tuple[bool, str]:
        amt = float(amount_usd)
        if amt < 0:
            return False, "negative_amount_disallowed"
        if amt > 0 and not approved_by:
            return False, "owner_approval_required_for_spend"
        now = time.time()
        day_start = now - 86400.0
        with self._lock, self._connect() as conn:
            daily_spent = float(
                conn.execute(
                    "SELECT COALESCE(SUM(amount_usd), 0.0) FROM spend_ledger WHERE created_at >= ?",
                    (day_start,),
                ).fetchone()[0]
            )
            if daily_spent + amt > self._daily_cap_usd:
                return False, f"daily_cap_exceeded ({daily_spent + amt:.2f} > {self._daily_cap_usd:.2f})"
            row = conn.execute(
                "SELECT budget_usd, spent_usd FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is not None:
                budget, spent = float(row[0]), float(row[1])
                if spent + amt > budget:
                    return False, f"project_budget_exceeded ({spent + amt:.2f} > {budget:.2f})"
                conn.execute(
                    "UPDATE projects SET spent_usd = ?, updated_at = ? WHERE project_id = ?",
                    (spent + amt, now, project_id),
                )
            conn.execute(
                """
                INSERT INTO spend_ledger (entry_id, project_id, role_id, amount_usd, description, approved_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"sp_{uuid.uuid4().hex[:10]}", project_id, role_id, amt, description, approved_by, now),
            )
        return True, "recorded"

    def budget_summary(self) -> dict[str, Any]:
        day_start = time.time() - 86400.0
        with self._lock, self._connect() as conn:
            daily = float(
                conn.execute(
                    "SELECT COALESCE(SUM(amount_usd), 0.0) FROM spend_ledger WHERE created_at >= ?",
                    (day_start,),
                ).fetchone()[0]
            )
            total = float(
                conn.execute("SELECT COALESCE(SUM(amount_usd), 0.0) FROM spend_ledger").fetchone()[0]
            )
        return {
            "daily_cap_usd": self._daily_cap_usd,
            "daily_spent_usd": round(daily, 2),
            "daily_remaining_usd": round(max(0.0, self._daily_cap_usd - daily), 2),
            "lifetime_spent_usd": round(total, 2),
        }


__all__ = ["BusinessProject", "BusinessStore", "DEFAULT_TEAM_ROLES", "TeamRole"]
