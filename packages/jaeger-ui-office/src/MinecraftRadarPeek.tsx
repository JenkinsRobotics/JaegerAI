import { useCallback, useEffect, useRef, useState } from "react";

interface RadarBot {
  username?: string;
  x?: number;
  y?: number;
  z?: number;
  yaw?: number;
  health?: number;
  food?: number;
  biome?: string;
}

interface RadarEntity {
  name: string;
  type: string;
  dx: number;
  dz: number;
  distance: number;
}

interface RadarChatItem {
  id: number;
  username: string;
  message: string;
  timestamp: number;
}

interface RadarResponse {
  ok?: boolean;
  connected?: boolean;
  radius?: number;
  bot?: RadarBot;
  grid?: Array<Array<[string, number]>>;
  entities?: RadarEntity[];
  nearby_players?: Array<{ username: string; visible?: boolean; distance?: number | null }>;
  inventory?: Record<string, number>;
  modes?: Record<string, { enabled?: boolean; target?: string | null }>;
  chat_inbox?: RadarChatItem[];
  error?: string;
}

const TERRAIN_COLORS: Record<string, string> = {
  water: "#2563eb",
  lava: "#ea580c",
  grass: "#4d7c0f",
  dirt: "#78533a",
  stone: "#64748b",
  wood: "#92400e",
  leaves: "#15803d",
  sand: "#d6b877",
  snow: "#e2e8f0",
  ore: "#38bdf8",
  bed: "#e11d48",
  chest: "#b45309",
  craft: "#a16207",
  air: "#0f172a",
  other: "#475569",
};

const MODE_KEYS = ["self_preservation", "auto_eat", "self_defense", "unstuck"] as const;

export interface MinecraftRadarPeekProps {
  baseUrl: string;
  onClose: () => void;
}

export function MinecraftRadarPeek({ baseUrl, onClose }: MinecraftRadarPeekProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [radar, setRadar] = useState<RadarResponse | null>(null);
  const [playerTarget, setPlayerTarget] = useState("");
  const [chatDraft, setChatDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const fetchRadar = useCallback(async () => {
    try {
      const r = await fetch(`${baseUrl}/v1/embodiment/minecraft/radar?radius=8`);
      if (!r.ok) return;
      const data = (await r.json()) as RadarResponse;
      setRadar(data);
    } catch {
      // Ignore transient reconnect errors
    }
  }, [baseUrl]);

  useEffect(() => {
    void fetchRadar();
    const timer = window.setInterval(() => void fetchRadar(), 2200);
    return () => window.clearInterval(timer);
  }, [fetchRadar]);

  useEffect(() => {
    const isTest =
      typeof import.meta !== "undefined" &&
      Boolean((import.meta as { env?: { MODE?: string } }).env?.MODE === "test");
    if (isTest) return;
    const canvas = canvasRef.current;
    if (!canvas || !radar) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const size = 238;
    canvas.width = size;
    canvas.height = size;
    ctx.fillStyle = "#0b1120";
    ctx.fillRect(0, 0, size, size);

    const grid = radar.grid ?? [];
    const dim = grid.length || 17;
    const cell = Math.floor(size / dim);
    const offset = Math.floor((size - cell * dim) / 2);

    if (grid.length > 0) {
      for (let r = 0; r < grid.length; r++) {
        for (let c = 0; c < grid[r].length; c++) {
          const [kind, dy] = grid[r][c];
          ctx.fillStyle = TERRAIN_COLORS[kind] || TERRAIN_COLORS.other;
          ctx.fillRect(offset + c * cell, offset + r * cell, cell - 1, cell - 1);
          if (dy > 0) {
            ctx.fillStyle = "rgba(255,255,255,0.12)";
            ctx.fillRect(offset + c * cell, offset + r * cell, cell - 1, 2);
          } else if (dy < 0) {
            ctx.fillStyle = "rgba(0,0,0,0.22)";
            ctx.fillRect(offset + c * cell, offset + r * cell + cell - 3, cell - 1, 2);
          }
        }
      }
    } else {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "12px monospace";
      ctx.textAlign = "center";
      ctx.fillText("Minecraft standby", size / 2, size / 2);
    }

    const center = offset + Math.floor(dim / 2) * cell + Math.floor(cell / 2);
    // Draw nearby entities & teammates
    for (const ent of radar.entities ?? []) {
      const ex = center + ent.dx * cell;
      const ez = center + ent.dz * cell;
      if (ex < 4 || ex > size - 4 || ez < 4 || ez > size - 4) continue;
      ctx.fillStyle = ent.type === "player" ? "#facc15" : ent.type === "hostile" ? "#ef4444" : "#cbd5e1";
      ctx.beginPath();
      ctx.arc(ex, ez, ent.type === "player" ? 4.5 : 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Draw Jaeger center beacon
    ctx.fillStyle = "#22d3ee";
    ctx.beginPath();
    ctx.arc(center, center, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }, [radar]);

  const sendAction = async (action: string, params: Record<string, unknown> = {}) => {
    setBusy(true);
    setNotice("");
    try {
      const r = await fetch(`${baseUrl}/v1/embodiment/minecraft/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, params }),
      });
      const d = (await r.json()) as { ok?: boolean; summary?: string; error?: string };
      setNotice(d.summary || (d.ok ? `Sent ${action}` : d.error || "Action failed"));
      await fetchRadar();
    } catch {
      setNotice("Could not reach Minecraft control endpoint.");
    } finally {
      setBusy(false);
    }
  };

  const bot = radar?.bot ?? {};
  const modes = radar?.modes ?? {};
  const players = radar?.nearby_players ?? [];
  const defaultPlayer = playerTarget.trim() || players[0]?.username || "";

  return (
    <div
      className="jg-card"
      role="region"
      aria-label="Live Minecraft World Peek"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 13.5 }}>Live Minecraft World Peek</strong>
          <span className="jg-pill">
            {radar?.connected ? `Live @ (${bot.x ?? 0}, ${bot.y ?? 64}, ${bot.z ?? 0})` : "Standby"}
          </span>
          {radar?.connected && (
            <span className="jg-pill">
              HP {bot.health ?? 20}/20 · Food {bot.food ?? 20}/20
            </span>
          )}
        </div>
        <button type="button" className="jg-btn-ghost" onClick={onClose}>
          Close Peek
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 12, alignItems: "start" }}>
        <canvas
          ref={canvasRef}
          width={238}
          height={238}
          aria-label="Top-down Minecraft terrain and entity radar"
          style={{ width: 204, height: 204, borderRadius: 8, border: "1px solid var(--jg-border-subtle)", imageRendering: "pixelated" }}
        />

        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 200 }}>
          {/* Reflex mode toggles */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {MODE_KEYS.map((key) => {
              const on = Boolean(modes[key]?.enabled);
              return (
                <button
                  key={key}
                  type="button"
                  disabled={busy}
                  className={on ? "jg-btn jg-btn-primary" : "jg-btn-ghost"}
                  style={{ fontSize: 11.5, padding: "4px 8px" }}
                  onClick={() => void sendAction("set_mode", { mode: key, enabled: !on })}
                >
                  {key.replace("_", " ")}: {on ? "ON" : "OFF"}
                </button>
              );
            })}
          </div>

          {/* Co-op teammate controls */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <input
              className="jg-input"
              placeholder={players[0]?.username ? `Player (${players[0].username})` : "Player username"}
              value={playerTarget}
              onChange={(e) => setPlayerTarget(e.target.value)}
              style={{ flex: "1 1 130px", minWidth: 120 }}
            />
            <button
              type="button"
              className="jg-btn"
              disabled={busy || !defaultPlayer}
              onClick={() => void sendAction("follow_player", { player: defaultPlayer, distance: 3 })}
            >
              Follow
            </button>
            <button
              type="button"
              className="jg-btn"
              disabled={busy || !defaultPlayer}
              onClick={() => void sendAction("go_to_player", { player: defaultPlayer, distance: 3 })}
            >
              Come Here
            </button>
            <button
              type="button"
              className="jg-btn"
              disabled={busy}
              onClick={() => void sendAction("stop_actions")}
            >
              Stop
            </button>
          </div>

          {/* In-game chat bar */}
          <form
            style={{ display: "flex", gap: 6 }}
            onSubmit={(e) => {
              e.preventDefault();
              const msg = chatDraft.trim();
              if (!msg) return;
              setChatDraft("");
              void sendAction("chat", { message: msg });
            }}
          >
            <input
              className="jg-input"
              placeholder="Send in-game Minecraft chat…"
              value={chatDraft}
              onChange={(e) => setChatDraft(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="submit" className="jg-btn jg-btn-primary" disabled={busy || !chatDraft.trim()}>
              Say
            </button>
          </form>

          {notice && (
            <div className="jg-muted" role="status" style={{ fontSize: 12 }}>
              {notice}
            </div>
          )}

          {/* Recent inbound MC chat */}
          <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <strong style={{ fontSize: 11.5 }}>Recent In-Game Chat</strong>
            {(radar?.chat_inbox ?? []).length === 0 ? (
              <span className="jg-muted">No player chat messages yet.</span>
            ) : (
              (radar?.chat_inbox ?? []).slice(-4).map((m) => (
                <div key={m.id}>
                  <strong>{m.username}:</strong> <span className="jg-muted">{m.message}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
