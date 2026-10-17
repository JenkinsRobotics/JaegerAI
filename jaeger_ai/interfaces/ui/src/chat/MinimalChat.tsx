/* Minimal stand-in chat renderer, styled to the Grok Bot Mac target. The
 * shared VS Code-derived widget replaces it through ChatPaneMount. */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AgentAvatar } from "../agents/AgentAvatar";
import { HandoffMarker } from "../agents/HandoffMarker";
import { MicIcon, PlusIcon, SendIcon, StopIcon, WaveIcon } from "../icons";
import { ErrorState } from "../shell/ErrorState";
import { applyPart, type ChatHost, type ChatPart, type ChatSession, type ChatTurn, type TurnHandle } from "./host";
import { MiniMarkdown } from "./miniMarkdown";

const seconds = (ms?: number) => Math.max(1, Math.round((ms ?? 0) / 1000));
type Decide = (callId: string, decision: "approve" | "deny") => void;
type CardPart = Extract<ChatPart, { kind: "confirmation" | "question" }>;
type MarkerPart = Extract<ChatPart, { kind: "handoff" }>;

function BubblePart({ part }: { part: ChatPart }) {
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
    case "warning":
      return <div className="jg-notice jg-notice--warn">{part.message}</div>;
    case "error":
      return <div className="jg-notice jg-notice--error">{part.message}</div>;
    default:
      return null;
  }
}

function Card({ part, onDecide }: { part: CardPart; onDecide: Decide }) {
  if (part.kind === "question") {
    return (
      <div className="jg-card-widget" role="group" aria-label={part.title}>
        <div className="jg-card-widget__title">{part.title}</div>
        <ul className="jg-options">
          {part.options.map((o, i) => (
            <li key={o.id} className={`jg-option${o.id === part.chosenId ? " is-chosen" : ""}`} aria-current={o.id === part.chosenId ? "true" : undefined}>
              <span className="jg-option__key">{String.fromCharCode(65 + i)}</span>
              <span>{o.label}</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="jg-card-widget" role="group" aria-label={part.title}>
      <div className="jg-card-widget__title">{part.title}</div>
      <div className="jg-card-widget__message">{part.message}</div>
      <div className="jg-confirm__actions">
        <button type="button" className="jg-action jg-action--primary" onClick={() => onDecide(part.callId, "approve")}>Allow</button>
        <button type="button" className="jg-action" onClick={() => onDecide(part.callId, "deny")}>Deny</button>
      </div>
    </div>
  );
}

/** Split a response into bubbles, cards and centered markers. */
function segments(parts: ChatPart[]) {
  const out: Array<{ marker: MarkerPart } | { card: CardPart } | { bubble: ChatPart[] }> = [];
  for (const part of parts) {
    if (part.kind === "handoff") out.push({ marker: part });
    else if (part.kind === "confirmation" || part.kind === "question") out.push({ card: part });
    else {
      const last = out[out.length - 1];
      // Each new markdown block after text starts its own bubble, like the target.
      const startsNew = part.kind === "markdownContent" && last && "bubble" in last && last.bubble.some((p) => p.kind === "markdownContent");
      if (last && "bubble" in last && !startsNew) last.bubble.push(part);
      else out.push({ bubble: [part] });
    }
  }
  return out;
}

export function Typing() {
  return (
    <div className="jg-typing" role="status" aria-live="polite">
      <span className="jg-typing__dots" aria-hidden="true"><i /><i /><i /></span>
      Putting it together
    </div>
  );
}

export function MinimalChat({ host, sessionId }: { host: ChatHost; sessionId?: string }) {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [loadError, setLoadError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [agent, setAgent] = useState<{ id: string; name: string }>({ id: "native:jaeger", name: "Jaeger" });
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

  // The agent this chat talks to: pill + placeholder.
  useEffect(() => {
    const agentId = session?.agentId ?? "native:jaeger";
    let live = true;
    void host.listAgents?.().then((agents) => {
      const found = agents.find((a) => a.id === agentId);
      if (live) setAgent({ id: agentId, name: found?.name ?? (agentId === "native:jaeger" ? "Jaeger" : agentId) });
    }, () => {});
    return () => { live = false; };
  }, [host, session?.agentId]);

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

  const decide = (turnId: string): Decide => (callId, decision) => {
    void host.respondToConfirmation(turnId, callId, decision);
    updateTurn(turnId, (t) => ({
      ...t,
      parts: t.parts.filter((p) => !(p.kind === "confirmation" && p.callId === callId)).map((p) =>
        p.kind === "toolInvocation" && p.callId === callId ? { ...p, state: decision === "approve" ? "executing" : "cancelled" } : p),
    }));
  };

  const voice = host.capabilities.voice;
  const hasText = Boolean(draft.trim());
  return (
    <div className="jg-chat">
      <div className="jg-chat__band" data-aether-window-drag-region>
        <button type="button" className="jg-agent-pill" title={session?.title}>
          <AgentAvatar id={agent.id} name={agent.name} size={20} />
          <span>{agent.name}</span>
        </button>
      </div>
      <div className="jg-chat__scroll" ref={scroller}>
        <div className="jg-chat__column">
          {loadError && <ErrorState title="Couldn't load this chat" error={loadError} onRetry={() => setAttempt((n) => n + 1)} />}
          {session && !session.turns.length && <p className="jg-chat__empty">What should we work on?</p>}
          {session?.turns.map((turn) => (
            <section key={turn.turnId} className="jg-turn">
              {turn.message && <div className="jg-bubble jg-bubble--user">{turn.message}</div>}
              {segments(turn.parts).map((seg, i) =>
                "marker" in seg ? <HandoffMarker key={i} part={seg.marker} onOpen={host.openHandoff ? (id) => host.openHandoff?.(id) : undefined} />
                : "card" in seg ? <Card key={i} part={seg.card} onDecide={decide(turn.turnId)} />
                : <div key={i} className="jg-bubble jg-bubble--assistant">{seg.bubble.map((p, j) => <BubblePart key={j} part={p} />)}</div>)}
              {turn.state === "pending" && !turn.parts.some((p) => p.kind === "markdownContent" && p.text) && <Typing />}
            </section>
          ))}
        </div>
      </div>
      <form className="jg-composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <button type="button" className="jg-composer__icon jg-composer__icon--filled" aria-label="Attach"><PlusIcon /></button>
        <textarea className="jg-composer__input" rows={1} placeholder={`Message ${agent.name}`} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} aria-label="Message" />
        {voice && <button type="button" className="jg-composer__icon jg-composer__icon--filled" aria-label="Dictate"><MicIcon /></button>}
        {active
          ? <button type="button" className="jg-send" aria-label="Stop (⌘Esc)" onClick={stop}><StopIcon /></button>
          : hasText || !voice
            ? <button type="submit" className="jg-send" aria-label="Send" disabled={!hasText}><SendIcon /></button>
            : <button type="button" className="jg-send" aria-label="Voice mode"><WaveIcon /></button>}
      </form>
    </div>
  );
}
