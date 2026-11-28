import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MinecraftRadarPeek } from "./MinecraftRadarPeek";
import { OfficeEngine } from "./officeEngine";
import type { OfficeAgentActivity, OfficeAgentRecord, OfficeSnapshot } from "./types";

export interface OfficeWorkspaceProps {
  baseUrl: string;
  onOpenChat?: () => void;
  onOpenWorkflows?: () => void;
  onOpenDroid?: () => void;
}

const ACTIVITY_LABELS: Record<OfficeAgentActivity, string> = {
  typing: "Active · Coding / Executing",
  reading: "Active · Researching / Reading",
  thinking: "Thinking",
  waiting_approval: "Waiting for Approval",
  idle: "Standing By",
  coffee: "Coffee Break",
  offline: "Offline",
  estop: "E-Stop Latched",
};

const IS_TEST =
  typeof import.meta !== "undefined" &&
  Boolean((import.meta as { env?: { MODE?: string } }).env?.MODE === "test");

export function OfficeWorkspace({
  baseUrl,
  onOpenChat,
  onOpenWorkflows,
  onOpenDroid,
}: OfficeWorkspaceProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<OfficeEngine | null>(null);
  if (!engineRef.current) engineRef.current = new OfficeEngine();

  const [snapshot, setSnapshot] = useState<OfficeSnapshot>({
    agents: [],
    activityFeed: [],
    pendingApprovals: 0,
    activeSubagents: 0,
    estopActive: false,
    autonomyEnabled: true,
    minecraftConnected: false,
    droidAwake: false,
    updatedAt: 0,
  });
  const [selectedId, setSelectedId] = useState<string | null>("jaeger");
  const [zoom, setZoom] = useState(2.35);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [reducedMotion, setReducedMotion] = useState(() =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [actionNotice, setActionNotice] = useState("");
  const [sseLive, setSseLive] = useState(false);
  const [showMcPeek, setShowMcPeek] = useState(false);
  const dragRef = useRef<{ active: boolean; moved: boolean; startX: number; startY: number; panX: number; panY: number }>({
    active: false,
    moved: false,
    startX: 0,
    startY: 0,
    panX: 0,
    panY: 0,
  });

  const loadOfficeState = useCallback(async () => {
    try {
      const r = await fetch(`${baseUrl}/v1/office/state`);
      if (!r.ok) return;
      const data = (await r.json()) as Partial<OfficeSnapshot> & { ok?: boolean };
      if (!Array.isArray(data.agents)) return;
      const next: OfficeSnapshot = {
        agents: data.agents,
        activityFeed: Array.isArray(data.activityFeed) ? data.activityFeed : [],
        budgets: data.budgets,
        pendingApprovals: Number(data.pendingApprovals ?? 0),
        activeSubagents: Number(data.activeSubagents ?? 0),
        estopActive: Boolean(data.estopActive),
        autonomyEnabled: data.autonomyEnabled !== false,
        minecraftConnected: Boolean(data.minecraftConnected),
        minecraftSummary: data.minecraftSummary,
        droidAwake: Boolean(data.droidAwake),
        updatedAt: Number(data.updatedAt ?? Date.now() / 1000),
      };
      setSnapshot(next);
      engineRef.current?.syncSnapshot(next);
    } catch {
      // Keep last known snapshot during brief reconnects
    }
  }, [baseUrl]);

  useEffect(() => {
    void loadOfficeState();
    let debounceTimer: number | undefined;
    const scheduleRefresh = () => {
      if (debounceTimer !== undefined) return;
      debounceTimer = window.setTimeout(() => {
        debounceTimer = undefined;
        void loadOfficeState();
      }, 220);
    };

    let es: EventSource | null = null;
    if (!IS_TEST && typeof EventSource === "function") {
      try {
        es = new EventSource(`${baseUrl}/v1/events/global`);
        es.onopen = () => setSseLive(true);
        es.onerror = () => setSseLive(false);
        const eventTypes = [
          "global.connected",
          "office.tool_started",
          "office.tool_finished",
          "subagent.spawned",
          "droid.changed",
          "droid.auto_parked",
          "minecraft.changed",
          "minecraft.chat",
          "minecraft.reply",
          "minecraft.step",
          "cognition.state",
          "cognition.reflection",
          "chat.turn_completed",
        ];
        for (const evType of eventTypes) {
          es.addEventListener(evType, scheduleRefresh);
        }
      } catch {
        setSseLive(false);
      }
    }

    const fallbackMs = es ? 15000 : 3500;
    const timer = window.setInterval(() => void loadOfficeState(), fallbackMs);
    return () => {
      window.clearInterval(timer);
      if (debounceTimer !== undefined) window.clearTimeout(debounceTimer);
      if (es) es.close();
    };
  }, [baseUrl, loadOfficeState]);

  useEffect(() => {
    if (engineRef.current) {
      engineRef.current.selectedAgentId = selectedId;
    }
  }, [selectedId]);

  useEffect(() => {
    if (IS_TEST) return;
    const canvas = canvasRef.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;
    let last = performance.now();

    const frame = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      const targetW = Math.max(320, Math.floor(rect.width * dpr));
      const targetH = Math.max(240, Math.floor(rect.height * dpr));
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      ctx.save();
      ctx.scale(dpr, dpr);
      engine.step(dt, reducedMotion);
      engine.render(ctx, rect.width || 640, rect.height || 420, zoom, pan.x, pan.y);
      ctx.restore();
      rafId = window.requestAnimationFrame(frame);
    };

    rafId = window.requestAnimationFrame(frame);
    return () => window.cancelAnimationFrame(rafId);
  }, [zoom, pan, reducedMotion]);

  const selectedAgent: OfficeAgentRecord | null = useMemo(() => {
    if (selectedId) {
      const exact = snapshot.agents.find((a) => a.id === selectedId);
      if (exact) return exact;
    }
    return snapshot.agents[0] ?? null;
  }, [snapshot.agents, selectedId]);

  const activeWorkersCount = useMemo(
    () =>
      snapshot.agents.filter((a) =>
        a.activity === "typing" || a.activity === "reading" || a.activity === "thinking" || a.activity === "waiting_approval",
      ).length,
    [snapshot.agents],
  );

  const handleCanvasTap = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    const rect = canvas.getBoundingClientRect();
    const world = engine.screenToWorld(clientX, clientY, rect, zoom, pan.x, pan.y);
    if (engine.petCatIfHit(world.x, world.y)) {
      setActionNotice("Pixel the office cat purred.");
      return;
    }
    const hit = engine.hitTestAgent(world.x, world.y);
    if (hit) {
      setSelectedId(hit.id);
      setActionNotice("");
    }
  };

  const triggerAutonomousStep = async () => {
    setActionNotice("Running one safe autonomous step…");
    try {
      const r = await fetch(`${baseUrl}/v1/cognition/autonomy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_now: true }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        setActionNotice(d.triggered?.summary || "Autonomous step evaluated.");
        await loadOfficeState();
      } else {
        setActionNotice(d.error || "Could not trigger autonomous step.");
      }
    } catch {
      setActionNotice("Gateway unreachable.");
    }
  };

  return (
    <div
      className="jg-content jg-workspace-page"
      data-testid="jaeger-virtual-office"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      {/* Top Studio Office HUD */}
      <div
        className="jg-card"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 15 }}>Jaeger Virtual Office</strong>
          <span className="jg-pill">{snapshot.agents.length} roster</span>
          <span className="jg-pill">{activeWorkersCount} active</span>
          {sseLive && <span className="jg-pill">Realtime SSE</span>}
          {snapshot.activeSubagents > 0 && (
            <span className="jg-pill">{snapshot.activeSubagents} live subagent(s)</span>
          )}
          {snapshot.pendingApprovals > 0 && (
            <span className="jg-pill">{snapshot.pendingApprovals} waiting approval</span>
          )}
          {snapshot.budgets?.daily_cap_usd !== undefined && (
            <span className="jg-pill">
              Budget: ${(snapshot.budgets.daily_spent_usd ?? 0).toFixed(2)} / ${snapshot.budgets.daily_cap_usd.toFixed(2)}
            </span>
          )}
          {snapshot.estopActive && <span className="jg-pill">E-STOP ACTIVE</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            className="jg-btn-ghost"
            aria-label="Zoom out office"
            onClick={() => setZoom((z) => Math.max(1.2, Number((z - 0.3).toFixed(2))))}
          >
            −
          </button>
          <button
            type="button"
            className="jg-btn-ghost"
            aria-label="Reset office camera"
            onClick={() => {
              setZoom(2.35);
              setPan({ x: 0, y: 0 });
            }}
          >
            {Math.round((zoom / 2.35) * 100)}%
          </button>
          <button
            type="button"
            className="jg-btn-ghost"
            aria-label="Zoom in office"
            onClick={() => setZoom((z) => Math.min(4.2, Number((z + 0.3).toFixed(2))))}
          >
            +
          </button>
          <button
            type="button"
            className={showMcPeek ? "jg-btn jg-btn-primary" : "jg-btn-ghost"}
            aria-pressed={showMcPeek}
            onClick={() => setShowMcPeek((v) => !v)}
          >
            {showMcPeek ? "Hide MC Peek" : "Minecraft Peek"}
          </button>
          <button
            type="button"
            className="jg-btn-ghost"
            aria-pressed={reducedMotion}
            onClick={() => setReducedMotion((v) => !v)}
          >
            {reducedMotion ? "Resume Motion" : "Reduced Motion"}
          </button>
          <button type="button" className="jg-btn" onClick={() => void triggerAutonomousStep()}>
            Run Step
          </button>
        </div>
      </div>

      {/* Main Split: Interactive Pixel Canvas + Agent Inspector */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(260px, 320px)",
          gap: 12,
          alignItems: "stretch",
        }}
      >
        <div
          className="jg-card"
          style={{
            padding: 0,
            overflow: "hidden",
            position: "relative",
            minHeight: 420,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <canvas
            ref={canvasRef}
            aria-label="Interactive Jaeger Virtual Office floorplan"
            style={{
              width: "100%",
              height: 440,
              display: "block",
              cursor: "grab",
              touchAction: "none",
            }}
            onWheel={(e) => {
              e.preventDefault();
              const delta = e.deltaY < 0 ? 0.2 : -0.2;
              setZoom((z) => Math.min(4.2, Math.max(1.2, Number((z + delta).toFixed(2)))));
            }}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              dragRef.current = {
                active: true,
                moved: false,
                startX: e.clientX,
                startY: e.clientY,
                panX: pan.x,
                panY: pan.y,
              };
            }}
            onPointerMove={(e) => {
              const canvas = canvasRef.current;
              const engine = engineRef.current;
              if (dragRef.current.active) {
                const dx = e.clientX - dragRef.current.startX;
                const dy = e.clientY - dragRef.current.startY;
                if (Math.hypot(dx, dy) > 5) dragRef.current.moved = true;
                setPan({ x: dragRef.current.panX + dx, y: dragRef.current.panY + dy });
                return;
              }
              if (canvas && engine) {
                const rect = canvas.getBoundingClientRect();
                const world = engine.screenToWorld(e.clientX, e.clientY, rect, zoom, pan.x, pan.y);
                const hit = engine.hitTestAgent(world.x, world.y);
                engine.hoveredAgentId = hit?.id ?? null;
              }
            }}
            onPointerUp={(e) => {
              const wasDrag = dragRef.current.moved;
              dragRef.current.active = false;
              if (!wasDrag) {
                handleCanvasTap(e.clientX, e.clientY);
              }
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "6px 12px",
              borderTop: "1px solid var(--jg-border-subtle)",
              fontSize: 12,
            }}
          >
            <span className="jg-muted">
              Click any agent to inspect · Drag to pan · Scroll to zoom · Tap Pixel the cat
            </span>
            <span className="jg-muted">
              Droid: {snapshot.droidAwake ? "Awake" : "Parked"} · Minecraft: {snapshot.minecraftConnected ? "Connected" : "Offline"}
            </span>
          </div>
        </div>

        {/* Right Inspector Drawer */}
        <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong style={{ fontSize: 13.5 }}>Agent Inspector</strong>
            {selectedAgent && <span className="jg-pill">{selectedAgent.zone}</span>}
          </div>

          {/* Quick Agent Roster Switcher (accessible for keyboard & mobile/iPad) */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {snapshot.agents.map((a) => (
              <button
                key={a.id}
                type="button"
                className={selectedAgent?.id === a.id ? "jg-btn jg-btn-primary" : "jg-btn-ghost"}
                style={{ fontSize: 11.5, padding: "4px 8px" }}
                onClick={() => setSelectedId(a.id)}
              >
                {a.name}
              </button>
            ))}
          </div>

          {selectedAgent ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--jg-border-subtle)", paddingTop: 10 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{selectedAgent.name}</div>
                <div className="jg-muted" style={{ fontSize: 12 }}>{selectedAgent.role}</div>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <span className="jg-pill">{ACTIVITY_LABELS[selectedAgent.activity]}</span>
                {selectedAgent.model && <span className="jg-pill">{selectedAgent.model}</span>}
              </div>
              {selectedAgent.currentTool && (
                <div className="jg-muted" style={{ fontSize: 12 }}>
                  Tool: <code>{selectedAgent.currentTool}</code>
                </div>
              )}
              <div className="jg-muted" style={{ fontSize: 12.5 }}>
                {selectedAgent.currentTask || selectedAgent.statusLabel}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                {onOpenChat && (
                  <button type="button" className="jg-btn jg-btn-primary" onClick={onOpenChat}>
                    Open Chat
                  </button>
                )}
                {onOpenWorkflows && (
                  <button type="button" className="jg-btn" onClick={onOpenWorkflows}>
                    Workflows
                  </button>
                )}
                {onOpenDroid && selectedAgent.kind === "embodiment" && (
                  <button type="button" className="jg-btn" onClick={onOpenDroid}>
                    Droid / Body
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="jg-muted" style={{ fontSize: 12.5 }}>
              Waiting for live agents from Gateway…
            </div>
          )}

          {actionNotice && (
            <div className="jg-muted" role="status" style={{ fontSize: 12 }}>
              {actionNotice}
            </div>
          )}

          {/* Water Cooler / Studio Activity Feed */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid var(--jg-border-subtle)", paddingTop: 10, marginTop: "auto" }}>
            <strong style={{ fontSize: 12.5 }}>Live Studio Feed</strong>
            {snapshot.activityFeed.length === 0 ? (
              <div className="jg-muted" style={{ fontSize: 12 }}>All desks quiet.</div>
            ) : (
              snapshot.activityFeed.slice(0, 6).map((ev) => (
                <div key={ev.id} style={{ fontSize: 12, lineHeight: 1.35 }}>
                  <strong>{ev.agentName}</strong>{" "}
                  <span className="jg-muted">{ev.summary}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {showMcPeek && (
        <MinecraftRadarPeek baseUrl={baseUrl} onClose={() => setShowMcPeek(false)} />
      )}
    </div>
  );
}
