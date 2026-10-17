/* Minimal stand-in chat renderer. Just enough for the mock screenshot; the
 * shared VS Code-derived widget replaces it through ChatPaneMount. Not polished
 * on purpose. */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { HandoffMarker } from "../agents/HandoffMarker";
import { ErrorState } from "../shell/ErrorState";
import { MicIcon, PlusIcon, SendIcon, StopIcon } from "../icons";
import { applyPart, type ChatHost, type ChatPart, type ChatSession, type ChatTurn, type TurnHandle } from "./host";
import { MiniMarkdown } from "./miniMarkdown";

const seconds = (ms?: number) => Math.max(1, Math.round((ms ?? 0) / 1000));

function Part({ part, onDecide }: { part: ChatPart; onDecide: (callId: string, decision: "approve" | "deny") => void }) {
  switch (part.kind) {
    case "markdownContent":
      return <div className="jg-md"><MiniMarkdown text={part.text} /></div>;
    case "thinking":
      return <details className="jg-thinking"><summary>Thought for {seconds(part.durationMs)} s</summary><p>{part.text}</p></details>;
    case "progress":
      return <div className="jg-progress"><span className="jg-spinner" aria-hidden="true" />{part.message}</div>;
    case "toolInvocation":
      return (
        <div className={`jg-tool jg-tool--${part.state}`}>
          <span className="jg-tool__verb">{part.state === "completed" ? "Ran" : part.state === "cancelled" ? "Stopped" : part.state === "waitingForConfirmation" ? "Run" : "Running"}</span>{" "}
          <code>{part.toolName}</code>
        </div>
      );
    case "confirmation":
      return (
        <div className="jg-confirm" role="group" aria-label={part.title}>
          <div className="jg-confirm__title">{part.title}</div>
          <div className="jg-confirm__message">{part.message}</div>
          <div className="jg-confirm__actions">
            <button type="button" className="aui-button aui-button--primary" onClick={() => onDecide(part.callId, "approve")}>Allow</button>
            <button type="button" className="aui-button" onClick={() => onDecide(part.callId, "deny")}>Deny</button>
          </div>
        </div>
      );
    case "warning":
      return <div className="jg-notice jg-notice--warn">{part.message}</div>;
    case "error":
      return <div className="jg-notice jg-notice--error">{part.message}</div>;
    case "handoff":
      return null;
  }
}

/** Split a response into bubble runs and centered handoff markers. */
function segments(parts: ChatPart[]) {
  const out: Array<{ marker: Extract<ChatPart, { kind: "handoff" }> } | { bubble: ChatPart[] }> = [];
  for (const part of parts) {
    if (part.kind === "handoff") out.push({ marker: part });
    else {
      const last = out[out.length - 1];
      if (last && "bubble" in last) last.bubble.push(part);
      else out.push({ bubble: [part] });
    }
  }
  return out;
}

export function MinimalChat({ host, sessionId }: { host: ChatHost; sessionId?: string }) {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [loadError, setLoadError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState<TurnHandle | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    setSession(null);
    setLoadError(undefined);
    if (sessionId) host.sessions.load(sessionId).then(
      (s) => { if (live) setSession(s); },
      (error: unknown) => { if (live) setLoadError(String((error as Error)?.message ?? error)); },
    );
    return () => { live = false; };
  }, [host, sessionId, attempt]);

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [session]);

  const updateTurn = useCallback((turnId: string, fn: (turn: ChatTurn) => ChatTurn) => {
    setSession((s) => (s ? { ...s, turns: s.turns.map((t) => (t.turnId === turnId ? fn(t) : t)) } : s));
  }, []);

  const send = () => {
    const message = draft.trim();
    if (!message || !session || active) return;
    const turnId = crypto.randomUUID();
    setDraft("");
    setSession({ ...session, turns: [...session.turns, { turnId, message, parts: [], state: "pending" }] });
    const handle = host.startTurn({ sessionId: session.id, turnId, message }, (part) => updateTurn(turnId, (t) => ({ ...t, parts: applyPart(t.parts, part) })));
    setActive(handle);
    void handle.done.then(({ state }) => { updateTurn(turnId, (t) => ({ ...t, state })); setActive(null); });
  };
  const stop = () => active?.cancel();

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); stop(); return; }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
  };

  const decide = (turnId: string) => (callId: string, decision: "approve" | "deny") => {
    void host.respondToConfirmation(turnId, callId, decision);
    updateTurn(turnId, (t) => ({
      ...t,
      parts: t.parts.filter((p) => !(p.kind === "confirmation" && p.callId === callId)).map((p) =>
        p.kind === "toolInvocation" && p.callId === callId ? { ...p, state: decision === "approve" ? "executing" : "cancelled" } : p),
    }));
  };

  return (
    <div className="jg-chat">
      <div className="jg-chat__band" data-aether-window-drag-region>
        <button type="button" className="jg-title-pill">{session?.title ?? "New chat"}</button>
      </div>
      <div className="jg-chat__scroll" ref={scroller}>
        <div className="jg-chat__column">
          {loadError && <ErrorState title="Couldn't load this chat" error={loadError} onRetry={() => setAttempt((n) => n + 1)} />}
          {session && !session.turns.length && <p className="jg-chat__empty">What should we work on?</p>}
          {session?.turns.map((turn) => (
            <section key={turn.turnId} className="jg-turn">
              <div className="jg-bubble jg-bubble--user">{turn.message}</div>
              {segments(turn.parts).map((seg, i) =>
                "marker" in seg
                  ? <HandoffMarker key={i} part={seg.marker} onOpen={host.openHandoff ? (id) => host.openHandoff?.(id) : undefined} />
                  : <div key={i} className="jg-bubble jg-bubble--assistant">{seg.bubble.map((p, j) => <Part key={j} part={p} onDecide={decide(turn.turnId)} />)}</div>)}
              {turn.state === "pending" && !turn.parts.length && <div className="jg-bubble jg-bubble--assistant"><div className="jg-progress"><span className="jg-spinner" aria-hidden="true" />Working…</div></div>}
            </section>
          ))}
        </div>
      </div>
      <form className="jg-composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <button type="button" className="jg-composer__icon" aria-label="Attach"><PlusIcon /></button>
        <textarea className="jg-composer__input" rows={1} placeholder="Message Jaeger" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} aria-label="Message" />
        {host.capabilities.voice && <button type="button" className="jg-composer__icon" aria-label="Voice input"><MicIcon /></button>}
        {active
          ? <button type="button" className="jg-send" aria-label="Stop (⌘Esc)" onClick={stop}><StopIcon /></button>
          : <button type="submit" className="jg-send" aria-label="Send" disabled={!draft.trim()}><SendIcon /></button>}
      </form>
    </div>
  );
}
