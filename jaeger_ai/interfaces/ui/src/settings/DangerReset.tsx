/** Reset-to-default (moved from the old Settings hub NavPage into Settings → System → Reset). */
import { useCallback, useState } from "react";
import "../widgets/host/host.css";

type ResetStage = "idle" | "confirm" | "running" | "done" | "error";

/** Reset-to-default flow. Talks to POST /v1/app-reset (same-origin proxy adds
 * the caller token). The confirmation requires typing RESET; the request never
 * runs without it. */
export function DangerReset() {
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

