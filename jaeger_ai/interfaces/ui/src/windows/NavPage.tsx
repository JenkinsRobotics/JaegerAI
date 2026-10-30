/**
 * NavPage — the Settings hub (Jenkins Robotics, 2026-10-30, original).
 *
 * Panels (About / Features / Library / Skills / Workflows / Tools) and the
 * danger-zone reset. Agents live in the Agents tab, chats in Chat, tasks in
 * Tasks; this page no longer mirrors them.
 */
import React, { useCallback, useMemo, useState } from "react";
import type { WindowId } from "./WindowManager";
import "../widgets/host/host.css";
import {
  ChevronDown,
  ChevronRight,
  Plus,
} from "../components/Icons";

export interface NavPageProps {
  /** Kept so callers can pass it; Settings itself reads no live data. */
  source?: unknown;
  onOpenWindow?: (id: WindowId) => void;
  onStartChat?: () => void;
}

function Section({
  title,
  open,
  onToggle,
  children,
  note,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <div className="navp__section">
      <button
        type="button"
        className="navp__section-title"
        aria-expanded={open}
        onClick={onToggle}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span>{title}</span>
      </button>
      {open && (
        <div className="navp__section-body">
          {note ? <p className="navp__note">{note}</p> : children}
        </div>
      )}
    </div>
  );
}

/** Reset-to-default flow state */
type ResetStage = "idle" | "confirm" | "running" | "done" | "error";

/** Reset-to-default flow. Talks to POST /v1/app-reset (same-origin proxy adds
 * the caller token). The confirmation requires typing RESET; the request never
 * runs without it. */
function DangerReset() {
  const [stage, setStage] = useState<ResetStage>("idle");
  const [wipeMemory, setWipeMemory] = useState(false);
  const [typed, setTyped] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setStage("running");
    setError(null);
    try {
      const response = await fetch("/v1/app-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ wipe_memory: wipeMemory }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error((body && body.error) || `Reset failed (${response.status})`);
      }
      setResult(
        `Reset complete. ${body.deleted_sessions} conversation(s) deleted` +
          (body.archive ? ` · archive saved to ${body.archive}` : "") +
          (body.memory_cleared?.length ? ` · memory cleared: ${body.memory_cleared.length} item(s)` : "") +
          (body.memory_failed?.length ? ` · memory items that could not be removed: ${body.memory_failed.join(", ")}` : ""),
      );
      setStage("done");
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setStage("error");
    }
  }, [wipeMemory]);

  const busy = stage === "running";
  const canConfirm = typed.trim().toUpperCase() === "RESET";

  return (
    <div className="navp-reset">
      <p className="navp-reset__explain">
        Deletes every conversation, its messages, queued turns and attachments, and (optionally)
        Jaeger's memory of you and your work. An archive is saved to disk first, so history is
        recoverable manually. Caller tokens, credentials, identity and skills are never touched.
      </p>
      <label className="navp-reset__memory">
        <input
          type="checkbox"
          checked={wipeMemory}
          disabled={busy}
          onChange={(e) => setWipeMemory(e.target.checked)}
        />
        <span>Also wipe memory (facts, notes, reflections — Jaeger forgets you)</span>
      </label>

      {stage === "idle" && (
        <button type="button" className="navp-reset__btn" onClick={() => setStage("confirm")}>
          Reset app to default
        </button>
      )}

      {stage === "confirm" && (
        <div className="navp-reset__confirm">
          <p>
            Type <strong>RESET</strong> to confirm. {wipeMemory ? "Memory will be wiped." : "Chat history will be deleted."}
          </p>
          <div className="navp-reset__confirm-row">
            <input
              autoFocus
              type="text"
              placeholder="RESET"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canConfirm) void run();
                if (e.key === "Escape") setStage("idle");
              }}
              aria-label="Type RESET to confirm"
            />
            <button type="button" className="navp-reset__btn navp-reset__btn--danger" disabled={!canConfirm || busy} onClick={() => void run()}>
              Delete
            </button>
            <button type="button" className="navp-reset__btn" onClick={() => { setStage("idle"); setTyped(""); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {busy && <p className="navp-reset__status" role="status">Resetting — archiving, then deleting…</p>}
      {stage === "done" && result && <p className="navp-reset__status navp-reset__status--ok" role="status">{result}</p>}
      {stage === "error" && error && <p className="navp-reset__status navp-reset__status--err" role="alert">{error}</p>}
    </div>
  );
}

export function NavPage({ onOpenWindow, onStartChat }: NavPageProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    pages: true,
    danger: false,
  });

  const toggle = useCallback(
    (key: string) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] })),
    [],
  );

  // Settings-style panel list: the former tabs, grouped. Each row opens the
  // panel the same way it used to — a window, not a route change.
  const panels = useMemo(
    () => [
      { id: "about", label: "About JaegerAI", hint: "Version, identity, Jenkins Robotics" },
      { id: "features", label: "Features", hint: "What Jaeger can do" },
      { id: "library", label: "Library", hint: "Files, documents and artifacts" },
      { id: "skills", label: "Skills", hint: "Learned procedures" },
      { id: "workflows", label: "Workflows", hint: "Automation pipelines" },
      { id: "tools", label: "Tools & MCP", hint: "Tool inventory and servers" },
    ] as { id: string; label: string; hint: string }[],
    [],
  );

  return (
    <div className="navp">
      <div className="jg-band wg-band" data-aether-window-drag-region>
        <span className="jg-traffic-lights" aria-hidden="true"><i /><i /><i /></span>
        <h1 className="wg-page__title">Settings</h1>
        <div className="wg-page__tools">
          <button type="button" className="wg-btn wg-btn--primary" onClick={onStartChat}>
            <Plus size={13} /> New chat
          </button>
        </div>
      </div>

      <div className="navp__scroll">
        {/* Panels: everything that used to be its own tab */}
        <Section
          title="Panels"
          open={openSections.pages}
          onToggle={() => toggle("pages")}
        >
          <ul className="navp__list">
            {panels.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className="navp__row"
                  onClick={() => onOpenWindow?.(p.id as never)}
                  title={p.hint}
                >
                  <span className="navp__label">{p.label}</span>
                  <span className="navp__meta">{p.hint}</span>
                </button>
              </li>
            ))}
          </ul>
        </Section>

        {/* Danger zone — reset to default */}
        <Section
          title="Danger zone"
          open={openSections.danger}
          onToggle={() => toggle("danger")}
        >
          <DangerReset />
        </Section>
      </div>
    </div>
  );
}

export default NavPage;
