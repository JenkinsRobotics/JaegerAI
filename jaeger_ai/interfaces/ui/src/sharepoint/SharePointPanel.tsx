/**
 * SharePointPanel — reworked into "Artifacts" (Jenkins Robotics, 2026-10-30).
 *
 * The mock SharePoint document table (hardcoded PDFs, fake sync states) is
 * retired. This surface now shows ONLY files Jaeger actually made — verified
 * task artifacts through `source.taskArtifacts` — and a composer to prompt
 * Jaeger to make a new one, submitted as a real background task the same way
 * the Tasks page does (`taskActions.create`, proposal flow, approvals intact).
 *
 * The name stays one word away from the dock contract (`sharepoint` window id
 * and the dock label are repointed at build time below).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { TaskArtifact } from "../api/source";
import { Search, Zap, RefreshCw, X } from "../components/Icons";
import "./sharepoint.css";

export interface SharePointPanelProps {
  source?: JaegerSource;
}

function kindLabel(mime: string, name: string): string {
  const ext = (name.split(".").pop() ?? "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.includes("pdf")) return "pdf";
  if (ext === "md" || ext === "txt") return "text";
  if (ext === "csv" || mime.includes("sheet") || mime.includes("excel")) return "sheet";
  if (ext === "json" || ext === "py" || ext === "js" || ext === "ts" || ext === "rs" || ext === "sh")
    return "code";
  return ext || mime || "file";
}

function bytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function SharePointPanel({ source }: SharePointPanelProps) {
  const controls = source?.taskArtifacts;
  const taskActions = source?.taskActions;
  const [artifacts, setArtifacts] = useState<TaskArtifact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");

  // Prompt-to-create composer state
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitNote, setSubmitNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    if (!controls) {
      setError("This gateway does not expose an artifact catalog.");
      return;
    }
    setError(null);
    controls
      .list()
      .then((v) => {
        if (live) setArtifacts(v.artifacts);
      })
      .catch((e) => {
        if (live) setError(String((e as Error).message ?? e));
      });
    return () => {
      live = false;
    };
  }, [controls, attempt]);

  const filtered = useMemo(() => {
    if (!artifacts) return null;
    if (!query.trim()) return artifacts;
    const q = query.toLowerCase();
    return artifacts.filter(
      (a) => a.name.toLowerCase().includes(q) || a.task_title.toLowerCase().includes(q),
    );
  }, [artifacts, query]);

  /** Ask Jaeger to make a new artifact — a real background task submission. */
  const promptJaeger = useCallback(async () => {
    const goal = prompt.trim();
    if (!goal || !taskActions || submitting) return;
    setSubmitting(true);
    setSubmitNote(null);
    try {
      // The task owner requires a home session as the parent / return feed.
      let sessionId: string;
      if (source?.agentHome) {
        const home = await source.agentHome("native:jaeger");
        sessionId = home.session_id;
      } else {
        throw new Error("This gateway does not expose a home session for task submission.");
      }
      const receipt = await taskActions.create({
        session_id: sessionId,
        goal,
        request_id: crypto.randomUUID(),
        proposal: true,
      });
      setSubmitNote(
        `Submitted to Jaeger as a proposal (${receipt.task_id}). It will appear here once it produces a verified artifact.`,
      );
      setPrompt("");
    } catch (e) {
      setSubmitNote(String((e as Error).message ?? e));
    } finally {
      setSubmitting(false);
    }
  }, [prompt, taskActions, submitting, source]);

  return (
    <div className="bots-page artifacts-page">
      <header className="bots-header">
        <div className="bots-header__top">
          <div className="bots-title">
            <Zap size={32} />
            <div>
              <h1>Artifacts</h1>
              <p>
                Files Jaeger made — verified receipts, not a cloud sync. The SharePoint
                connector is disconnected for now.
              </p>
            </div>
          </div>
        </div>

        {/* Prompt Jaeger to create something */}
        <div className="artifacts-prompt">
          <textarea
            value={prompt}
            placeholder="Ask Jaeger to make something — e.g. “Write a Python script that converts the step files to STL”"
            maxLength={20000}
            rows={2}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void promptJaeger();
              }
            }}
            disabled={submitting || !taskActions}
            aria-label="Ask Jaeger to create an artifact"
          />
          <button
            type="button"
            className="bot-card__btn bot-card__btn--primary"
            disabled={submitting || !prompt.trim() || !taskActions}
            onClick={() => void promptJaeger()}
          >
            {submitting ? "Submitting…" : "Ask Jaeger"}
          </button>
        </div>
        {submitNote && <p className="artifacts-note" role="status">{submitNote}</p>}
        {!taskActions && (
          <p className="artifacts-note">Task submission isn’t available from this gateway, so prompting is off.</p>
        )}

        {/* Catalog search */}
        <div className="bots-search">
          <Search size={18} />
          <input
            type="text"
            placeholder="Search artifacts by name or task…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button className="bots-search__clear" onClick={() => setQuery("")} aria-label="Clear search">
              ×
            </button>
          )}
        </div>
      </header>

      <div className="bots-grid-container">
        {error ? (
          <div className="bots-empty">
            <Zap size={64} />
            <h3>Artifacts aren’t available</h3>
            <p>{error}</p>
          </div>
        ) : artifacts === null ? (
          <div className="bots-empty">
            <Zap size={64} />
            <h3>Reading artifact catalog…</h3>
          </div>
        ) : filtered !== null && filtered.length === 0 ? (
          <div className="bots-empty">
            <Zap size={64} />
            <h3>{query ? "No artifacts match" : "No artifacts yet"}</h3>
            <p>{query ? "Try a different search." : "Ask Jaeger above to make the first one."}</p>
          </div>
        ) : (
          <div className="bots-grid">
            {filtered?.map((a) => (
              <div className="bot-card artifact-card" key={a.attachment_id} title={a.name}>
                <div className="bot-card__info">
                  <p className="task-card__goal artifact-card__name" title={a.name}>
                    {a.name}
                  </p>
                  <div className="task-card__metrics">
                    <span className="task-card__metric">{kindLabel(a.mime, a.name)}</span>
                    <span className="task-card__metric">{bytes(a.size)}</span>
                    <span className="task-card__metric" title={a.task_title}>
                      from {a.task_title.slice(0, 24)}
                      {a.task_title.length > 24 ? "…" : ""}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {artifacts !== null && artifacts.length > 0 && (
          <button type="button" className="artifacts-refresh" onClick={() => setAttempt((n) => n + 1)}>
            <RefreshCw size={13} /> Refresh catalog
          </button>
        )}
      </div>
      {/* X marks the disabled connector explicitly, replacing the fake table */}
      <p className="artifacts-connector-note" title="SharePoint connector">
        <X size={12} /> SharePoint connector: disconnected
      </p>
    </div>
  );
}

export default SharePointPanel;