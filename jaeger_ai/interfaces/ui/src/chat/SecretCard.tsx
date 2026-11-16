import { useState } from "react";
import { csrfHeader } from "../api/gateway";

/** Masked vault card (parity P24). The value posts straight to the owner-only
 *  vault route and is never added to the chat, the event log or the model. */
export function SecretCard({ name, prompt, status, sessionId }: { name: string; prompt: string; status?: string; sessionId?: string }) {
  const [value, setValue] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">(status === "saved" ? "saved" : "idle");
  const [error, setError] = useState<string>();
  const done = state === "saved" || status === "saved";
  const save = async () => {
    if (!value) return;
    setState("saving"); setError(undefined);
    try {
      const res = await fetch("/v1/vault/secrets", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", Accept: "application/json", ...csrfHeader("POST") },
        body: JSON.stringify({ name, value, session_id: sessionId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setValue(""); setState("saved");
    } catch (e) { setState("error"); setError(String((e as Error).message || e)); }
  };
  return (
    <div className="jg-card jg-secret-card" role="group" aria-label={`Vault: ${name}`}>
      <div className="jg-card__title">🔒 {name}</div>
      {prompt && <p className="jg-card__message">{prompt}</p>}
      {done ? <p className="jg-card__message">Saved to your vault. Jaeger never sees it in chat.</p>
        : status === "expired" ? <p className="jg-card__message">This request expired. Ask again, or add it under Settings.</p>
        : <form style={{ display: "flex", gap: 8 }} onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Paste value" aria-label={`${name} value`} style={{ flex: 1 }} />
            <button type="submit" disabled={!value || state === "saving"}>{state === "saving" ? "Saving…" : "Save to vault"}</button>
          </form>}
      {error && <p className="jg-card__message" role="alert">{error}</p>}
    </div>
  );
}
