import { useCallback, useEffect, useState } from "react";

export interface MindAutonomyPanelProps {
  baseUrl: string;
  liveCogMode: string;
  focusText: string;
  tickCount: number;
  idleLifeStatus: string;
  preemptionCount: number;
  estopActive: boolean;
  onOpenTasks: () => void;
  onOpenGoals: () => void;
}

interface InitiativeAction {
  action_id?: string;
  kind: string;
  status: string;
  summary: string;
  created_at?: number;
}

interface AutonomyStatus {
  config?: {
    enabled?: boolean;
    cooldown_s?: number;
    max_actions_per_hour?: number;
  };
  drives?: {
    curiosity?: number;
    goal_momentum?: number;
    social?: number;
    energy?: number;
  };
  actions_last_hour?: number;
  next_eligible_in_s?: number;
}

interface MinecraftStatus {
  state?: {
    connected?: boolean;
    paused?: boolean;
    active_goal?: string;
    biome?: string;
    position?: { x?: number; y?: number; z?: number };
    ticks?: number;
  };
  bridge?: {
    server_reachable?: boolean;
    npm_installed?: boolean;
  };
}

export function MindAutonomyPanel({
  baseUrl,
  liveCogMode,
  focusText,
  tickCount,
  idleLifeStatus,
  preemptionCount,
  estopActive,
  onOpenTasks,
  onOpenGoals,
}: MindAutonomyPanelProps) {
  const [briefingSummary, setBriefingSummary] = useState("");
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [autonomy, setAutonomy] = useState<AutonomyStatus>({});
  const [actions, setActions] = useState<InitiativeAction[]>([]);
  const [reflections, setReflections] = useState<Array<{ reason?: string; skill_captured?: string; tools_used?: string[] }>>([]);
  const [minecraft, setMinecraft] = useState<MinecraftStatus>({});
  const [mcGoalDraft, setMcGoalDraft] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [statusNote, setStatusNote] = useState("");

  const loadLiveMind = useCallback(async () => {
    const safeGet = async (path: string): Promise<Record<string, any>> => {
      try {
        const r = await fetch(`${baseUrl}${path}`);
        if (!r.ok) return {};
        return (await r.json()) as Record<string, any>;
      } catch {
        return {};
      }
    };
    const [br, act, emb, aw] = await Promise.all([
      safeGet("/v1/cognition/briefing"),
      safeGet("/v1/cognition/actions?limit=8"),
      safeGet("/v1/embodiment/status"),
      safeGet("/v1/cognition/awareness"),
    ]);
    if (typeof br.summary === "string") setBriefingSummary(br.summary);
    if (typeof br.pending_approvals_count === "number") setPendingApprovals(br.pending_approvals_count);
    if (act.status) setAutonomy(act.status as AutonomyStatus);
    if (Array.isArray(act.actions)) setActions(act.actions as InitiativeAction[]);
    if (emb.minecraft) setMinecraft(emb.minecraft as MinecraftStatus);
    if (Array.isArray(aw.recent_reflections)) setReflections(aw.recent_reflections);
  }, [baseUrl]);

  useEffect(() => {
    void loadLiveMind();
    let es: EventSource | null = null;
    if (typeof EventSource === "function") {
      try {
        es = new EventSource(`${baseUrl}/v1/events/global`);
        const onChange = () => void loadLiveMind();
        for (const ev of ["cognition.reflection", "cognition.state", "minecraft.changed", "minecraft.step", "droid.changed", "droid.auto_parked"]) {
          es.addEventListener(ev, onChange);
        }
      } catch {
        es = null;
      }
    }
    const timer = window.setInterval(() => void loadLiveMind(), es ? 20000 : 10000);
    return () => {
      window.clearInterval(timer);
      if (es) es.close();
    };
  }, [baseUrl, loadLiveMind]);

  const toggleAutonomy = async () => {
    const nextEnabled = !(autonomy.config?.enabled ?? true);
    setBusyAction("toggle");
    setStatusNote("");
    try {
      const r = await fetch(`${baseUrl}/v1/cognition/autonomy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      if (r.ok) {
        const d = await r.json();
        if (d.status) setAutonomy(d.status);
        setStatusNote(nextEnabled ? "Autonomous self-actions enabled." : "Autonomous self-actions paused.");
      }
    } finally {
      setBusyAction("");
    }
  };

  const triggerStepNow = async () => {
    setBusyAction("step");
    setStatusNote("Running one safe self-action step…");
    try {
      const r = await fetch(`${baseUrl}/v1/cognition/autonomy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_now: true }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        if (d.status) setAutonomy(d.status);
        const trig = d.triggered;
        setStatusNote(trig?.acted ? `Completed: ${trig.summary || trig.kind}` : `Idle: ${trig?.reason || "nothing due"}`);
        await loadLiveMind();
      } else {
        setStatusNote(d.error || "Could not run autonomous step.");
      }
    } finally {
      setBusyAction("");
    }
  };

  const minecraftAct = async (action: string, params: Record<string, unknown> = {}) => {
    setBusyAction(`mc:${action}`);
    setStatusNote("");
    try {
      const r = await fetch(`${baseUrl}/v1/embodiment/minecraft/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, params }),
      });
      const d = await r.json().catch(() => ({}));
      setStatusNote(d.ok ? (d.summary || `Minecraft ${action} ok`) : (d.error || `Minecraft ${action} failed`));
      await loadLiveMind();
    } finally {
      setBusyAction("");
    }
  };

  const autonomyOn = autonomy.config?.enabled ?? true;
  const drives = autonomy.drives ?? {};
  const mcState = minecraft.state ?? {};
  const mcPos = mcState.position;

  return (
    <>
      <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <strong style={{ fontSize: 13 }}>While You Were Out</strong>
          {pendingApprovals > 0 && <span className="jg-pill">{pendingApprovals} waiting</span>}
        </div>
        <div className="jg-muted" style={{ whiteSpace: "pre-line", fontSize: 12.5 }}>
          {briefingSummary || "Standing by. Autonomous activity and daily updates appear here."}
        </div>
      </div>

      <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <strong style={{ fontSize: 13 }}>24/7 Cognitive Life Loop</strong>
          <span className="jg-pill">{autonomyOn ? "Autonomy ON" : "Autonomy PAUSED"}</span>
        </div>
        <div className="jg-muted" style={{ fontSize: 12 }}>
          Mode: <strong>{liveCogMode}</strong> · Ticks: {tickCount} · Rate: {autonomy.actions_last_hour ?? 0}/{autonomy.config?.max_actions_per_hour ?? 4}/hr
        </div>
        <div className="jg-muted" style={{ fontSize: 12 }}>Focus: {focusText} · Preemptions: {preemptionCount}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 11.5 }}>
          <span className="jg-pill">Curiosity: {Math.round((drives.curiosity ?? 0.5) * 100)}%</span>
          <span className="jg-pill">Momentum: {Math.round((drives.goal_momentum ?? 0.5) * 100)}%</span>
          <span className="jg-pill">Social: {Math.round((drives.social ?? 0.5) * 100)}%</span>
          <span className="jg-pill">Energy: {Math.round((drives.energy ?? 0.8) * 100)}%</span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button type="button" className="jg-btn" disabled={busyAction !== ""} onClick={() => void toggleAutonomy()}>
            {autonomyOn ? "Pause Autonomy" : "Enable Autonomy"}
          </button>
          <button
            type="button"
            className="jg-btn jg-btn-primary"
            disabled={busyAction !== "" || estopActive}
            onClick={() => void triggerStepNow()}
          >
            Run Step Now
          </button>
        </div>
        {statusNote && <div className="jg-muted" role="status" style={{ fontSize: 12 }}>{statusNote}</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 2 }}>
          <strong style={{ fontSize: 12 }}>Initiative Journal</strong>
          {actions.length === 0 ? (
            <div className="jg-muted" style={{ fontSize: 12 }}>No autonomous actions logged yet.</div>
          ) : (
            actions.slice(0, 5).map((act, idx) => (
              <div
                key={act.action_id || `${act.kind}-${idx}`}
                style={{ fontSize: 12, paddingTop: 4, borderTop: "1px solid var(--jg-border-subtle)" }}
              >
                <span className="jg-pill">{act.kind}</span>{" "}
                <span className="jg-muted">{act.summary}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <strong style={{ fontSize: 13 }}>Minecraft World Body</strong>
          <span className="jg-pill">{mcState.connected ? "Connected" : idleLifeStatus}</span>
        </div>
        <div className="jg-muted" style={{ fontSize: 12 }}>
          {mcPos && mcPos.x !== undefined
            ? `Pos: (${Math.round(mcPos.x)}, ${Math.round(mcPos.y ?? 0)}, ${Math.round(mcPos.z ?? 0)})${mcState.biome ? ` · ${mcState.biome}` : ""}`
            : "Not spawned in a Minecraft world yet."}
        </div>
        {mcState.active_goal && (
          <div className="jg-muted" style={{ fontSize: 12 }}>Goal: {mcState.active_goal}</div>
        )}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {mcState.connected ? (
            <button
              type="button"
              className="jg-btn"
              disabled={busyAction !== ""}
              onClick={() => void minecraftAct("disconnect")}
            >
              Disconnect
            </button>
          ) : (
            <button
              type="button"
              className="jg-btn"
              disabled={busyAction !== "" || estopActive}
              onClick={() => void minecraftAct("connect")}
            >
              Connect Minecraft
            </button>
          )}
        </div>
        <form
          style={{ display: "flex", gap: 6 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (!mcGoalDraft.trim()) return;
            const goal = mcGoalDraft.trim();
            setMcGoalDraft("");
            void minecraftAct("set_goal", { goal });
          }}
        >
          <input
            className="jg-input"
            aria-label="Minecraft goal"
            placeholder="Set Minecraft goal…"
            value={mcGoalDraft}
            onChange={(e) => setMcGoalDraft(e.target.value)}
          />
          <button type="submit" className="jg-btn" disabled={!mcGoalDraft.trim() || busyAction !== ""}>
            Set
          </button>
        </form>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button type="button" className="jg-btn-ghost" onClick={onOpenTasks}>Workflows</button>
          <button type="button" className="jg-btn-ghost" onClick={onOpenGoals}>Goals</button>
        </div>
      </div>

      {reflections.length > 0 && (
        <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <strong style={{ fontSize: 13 }}>Self-Improvement Reflections</strong>
          {reflections.slice(0, 4).map((ref, idx) => (
            <div key={idx} style={{ fontSize: 12, paddingTop: 4, borderTop: "1px solid var(--jg-border-subtle)" }}>
              <span className="jg-pill">{ref.skill_captured ? `skill:${ref.skill_captured}` : (ref.reason || "learned")}</span>{" "}
              <span className="jg-muted">
                {(ref.tools_used ?? []).slice(0, 4).join(", ") || "workflow"}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
