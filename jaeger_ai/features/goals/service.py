"""Goal service — operator-declared goals/projects over the commitment store.

A **goal** is what the operator wants done ("ship robot arm v2", "publish
episode 12"). A **project** is the parent the goal rolls up under. Both are
durable commitments (``jaeger_agent.cognition.commitments``) so they survive
restarts — the same store the MissionService uses, just with operator-facing
kinds (``goal`` / ``project``) and a ``tool_bundle`` payload that caps which
tools work on the goal may reach.

Persistence rides the bound memory database (``jaeger_agent.memory.sqlite_store``),
which lives under the operator state root (``~/.jaeger/``) — never in the repo.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from jaeger_agent.cognition.commitments import Commitment, CommitmentStore

from jaeger_ai.contract.tool_bundles import is_known_bundle


class GoalService:
    """Operator goals (root commitments) with optional project parents.

    ``tool_bundle`` is validated against
    :data:`jaeger_ai.contract.tool_bundles.TOOL_BUNDLES` so a typo fails at
    creation, not at turn admission.
    """

    def __init__(self, commitments: CommitmentStore) -> None:
        self.commitments = commitments

    def create(
        self,
        title: str,
        *,
        objective: str = "",
        project: str | None = None,
        tool_bundle: str | None = None,
        success_criteria: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("goal title is required")
        if tool_bundle is not None and not is_known_bundle(tool_bundle):
            raise ValueError(f"unknown tool_bundle: {tool_bundle!r}")
        payload: dict[str, Any] = dict(metadata or {})
        if objective:
            payload["objective"] = objective.strip()
        if tool_bundle:
            payload["tool_bundle"] = tool_bundle
        if success_criteria:
            payload["success_criteria"] = success_criteria.strip()
        parent_id: str | None = None
        if project:
            parent = self.commitments.create(
                str(project).strip(), kind="project", payload={}
            )
            parent_id = parent.id
        goal = self.commitments.create(
            clean_title, kind="goal", payload=payload, parent_id=parent_id
        )
        return self.describe(goal.id)

    def describe(self, goal_id: str) -> dict[str, Any]:
        goal = self.commitments.get(goal_id)
        if goal is None or goal.kind != "goal":
            raise KeyError(f"goal not found: {goal_id}")
        out: dict[str, Any] = {"goal": asdict(goal)}
        if goal.parent_id:
            parent = self.commitments.get(goal.parent_id)
            if parent is not None:
                out["project"] = asdict(parent)
        out["tasks"] = [
            asdict(child) for child in self.commitments.children(goal.id)
        ]
        return out

    def list(self, *, state: str | None = None) -> list[dict[str, Any]]:
        return [
            self.describe(item.id)
            for item in self.commitments.list(state=state)
            if item.kind == "goal"
        ]

    def update(
        self,
        goal_id: str,
        *,
        title: str | None = None,
        objective: str | None = None,
        tool_bundle: str | None | object = None,
        success_criteria: str | None = None,
    ) -> dict[str, Any]:
        """Edit a goal in place. ``tool_bundle=None`` leaves it; pass the
        sentinel ``_UNSET``-via-omission only — to clear, pass ``""``."""
        goal = self.commitments.get(goal_id)
        if goal is None or goal.kind != "goal":
            raise KeyError(f"goal not found: {goal_id}")
        payload = dict(goal.payload)
        if title is not None:
            clean = title.strip()
            if not clean:
                raise ValueError("goal title cannot be empty")
            # Commitment is a slotted dataclass; title is mutable in memory
            # but the SqliteCommitmentStore has no update-title path, so we
            # keep title edits in payload to stay store-agnostic.
            payload["display_title"] = clean
        if objective is not None:
            payload["objective"] = objective.strip()
        if success_criteria is not None:
            payload["success_criteria"] = success_criteria.strip()
        if tool_bundle is not None:
            if tool_bundle == "":
                payload.pop("tool_bundle", None)
            elif not is_known_bundle(str(tool_bundle)):
                raise ValueError(f"unknown tool_bundle: {tool_bundle!r}")
            else:
                payload["tool_bundle"] = str(tool_bundle)
        # Persist via transition-free payload rewrite: the commitment store
        # has no generic update, so re-create is wrong (loses id). We write
        # through the store's closest primitive — transition to the SAME
        # state is illegal — so goals keep edits in payload via a dedicated
        # store hook if present, else we mutate the in-memory record and
        # rely on the SQLite store's row being rewritten by ``_save``.
        self._persist_payload(goal, payload)
        return self.describe(goal.id)

    def _persist_payload(self, goal: Commitment, payload: dict[str, Any]) -> None:
        """Write an edited payload back through the store.

        The ``CommitmentStore`` protocol has no update method, so we write
        through the bound memory database directly (the same database the
        store reads from). The row keeps its id/state/parent; only the
        payload JSON and ``updated_at`` change. In-memory-only stores (the
        test double) just take the mutation.
        """
        goal.payload = payload
        update_row = getattr(self.commitments, "update_payload", None)
        if callable(update_row):
            update_row(goal.id, payload)
            return
        # Only the SQLite store needs a real write-through; in-memory stores
        # (tests) already reflect the mutation above.
        from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
        if not isinstance(self.commitments, SqliteCommitmentStore):
            return
        try:
            from jaeger_agent.memory import sqlite_store
            writer = sqlite_store.writer
        except Exception:  # noqa: BLE001 — no store bound; in-memory only
            return
        if writer is None:
            return
        from jaeger_agent.cognition.lifecycle import now as _now
        import json as _json
        with writer() as conn:
            conn.execute(
                "UPDATE commitments SET payload_json = ?, updated_at = ? "
                "WHERE id = ?",
                (_json.dumps(payload), _now(), goal.id),
            )

    def transition(self, goal_id: str, state: str) -> dict[str, Any]:
        return asdict(self.commitments.transition(goal_id, state))

    def project_status(self, project_id: str) -> dict[str, Any]:
        """Roll-up for one project: the project row, its goals, and each
        goal's open child tasks."""
        project = self.commitments.get(project_id)
        if project is None or project.kind != "project":
            raise KeyError(f"project not found: {project_id}")
        goals = [self.describe(g.id) for g in self.commitments.children(project_id)
                 if g.kind == "goal"]
        return {"project": asdict(project), "goals": goals}

    def seed_from_config(
        self,
        projects: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Seed durable goals from ``OperatorConfig.projects`` (the
        ``[[operator.projects]]`` tables in operator.toml).

        Each operator.toml project becomes a durable ``project`` commitment
        with one ``goal`` child per declared phase. Idempotent: a project is
        skipped when a project commitment with the same ``source_name``
        already exists in the store, so re-seeding on every boot does not
        duplicate work.

        ``phases`` on a project table is a list of
        ``{title, objective, tool_bundle, success_criteria}`` dicts — the
        phases of work for that project. When ``phases`` is absent the
        project seeds as a single goal titled "Kick off <project>".
        """
        created: list[dict[str, Any]] = []
        for project in projects:
            name = str(project.get("name", "")).strip()
            if not name:
                continue
            if self._find_project_by_source(name) is not None:
                continue  # already seeded
            bundle = project.get("tool_bundle") or None
            phases = project.get("phases") or []
            if isinstance(phases, list) and phases:
                # Project carries explicit phases — one goal per phase.
                parent = self.commitments.create(
                    name, kind="project",
                    payload={"source_name": name,
                             "root": project.get("root", ""),
                             "build_cmd": project.get("build_cmd", "")},
                )
                for phase in phases:
                    if isinstance(phase, str):
                        phase = {"title": phase}
                    phase = dict(phase)
                    phase_title = str(phase.pop("title", "")).strip()
                    if not phase_title:
                        continue
                    phase_bundle = phase.pop("tool_bundle", None) or bundle
                    goal = self.commitments.create(
                        phase_title, kind="goal",
                        payload={
                            **phase,
                            **({"tool_bundle": phase_bundle} if phase_bundle else {}),
                        },
                        parent_id=parent.id,
                    )
                    created.append(self.describe(goal.id))
            else:
                # No phases declared — single kickoff goal under the project.
                result = self.create(
                    f"Kick off {name}",
                    objective=str(project.get("objective", "")).strip(),
                    project=name,
                    tool_bundle=bundle,
                    success_criteria=str(project.get("success_criteria", "")).strip(),
                    metadata={"source_name": name,
                              "root": project.get("root", ""),
                              "build_cmd": project.get("build_cmd", "")},
                )
                created.append(result)
        return created

    def _find_project_by_source(self, source_name: str) -> Commitment | None:
        for item in self.commitments.list():
            if item.kind == "project" and item.payload.get("source_name") == source_name:
                return item
        return None
