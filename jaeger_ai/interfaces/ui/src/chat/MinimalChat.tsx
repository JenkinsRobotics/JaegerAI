/* Minimal stand-in chat renderer, styled to the Grok Bot Mac target. The
 * shared VS Code-derived widget replaces it through ChatPaneMount. */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { AgentAvatar } from "../agents/AgentAvatar";
import { avatarColor } from "../agents/avatarColor";
import { HandoffMarker } from "../agents/HandoffMarker";
import { ArrowDownIcon, MicIcon, PlusIcon, SendIcon, StopIcon, WaveIcon } from "../icons";
import { ErrorState } from "../shell/ErrorState";
import { applyPart, type ChatHost, type ChatPart, type ChatSession, type ChatTurn, type TurnHandle } from "./host";
import { MiniMarkdown } from "./miniMarkdown";
import type { VoiceHost } from "./nativeHost";

const seconds = (ms?: number) => Math.max(1, Math.round((ms ?? 0) / 1000));
type Decide = (callId: string, decision: "approve" | "deny") => void;
type CardPart = Extract<ChatPart, { kind: "confirmation" | "question" }>;
type MarkerPart = Extract<ChatPart, { kind: "handoff" }>;
type Links = { onCopy: (text: string) => void; onOpen: (url: string) => void };

/** A new separator when the day changes or after a 30-minute gap. */
const SEPARATOR_GAP_MS = 30 * 60 * 1000;
/** Auto-scroll only while the reader is this close to the bottom. */
const STICK_PX = 80;

export function separatorLabel(at: number, now = Date.now()): string {
  const d = new Date(at);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(new Date(now)) - day(d)) / 86_400_000);
  if (diff === 0) return `Today ${time}`;
  if (diff === 1) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}

export function needsSeparator(prev: number | undefined, at: number | undefined): boolean {
  if (at === undefined) return false;
  if (prev === undefined) return true;
  return new Date(prev).toDateString() !== new Date(at).toDateString() || at - prev > SEPARATOR_GAP_MS;
}

function BubblePart({ part, links }: { part: ChatPart; links: Links }) {
  switch (part.kind) {
    case "markdownContent":
      return <div className="jg-md"><MiniMarkdown text={part.text} onCopy={links.onCopy} onOpen={links.onOpen} /></div>;
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

/** Split a response into bubbles, cards and centered markers. Back-to-back
 * "Messaged" markers fold into one "Messaged X and Y", like the target. */
export function segments(parts: ChatPart[]) {
  const out: Array<{ marker: MarkerPart } | { card: CardPart } | { bubble: ChatPart[] }> = [];
  for (const part of parts) {
    const last = out[out.length - 1];
    if (part.kind === "handoff") {
      const prev = last && "marker" in last ? last.marker : undefined;
      if (prev && prev.direction === "to" && part.direction === "to") {
        const agents = [...(prev.agents ?? [{ id: prev.agentId, name: prev.agentName }])];
        if (!agents.some((a) => a.id === part.agentId)) agents.push({ id: part.agentId, name: part.agentName });
        out[out.length - 1] = { marker: { ...prev, agents } };
      } else out.push({ marker: part });
    } else if (part.kind === "confirmation" || part.kind === "question") out.push({ card: part });
    else {
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

const replyText = (turn: ChatTurn) => turn.parts.filter((p) => p.kind === "markdownContent").map((p) => (p as { text: string }).text).join("\n\n");

export function MinimalChat({ host, sessionId }: { host: ChatHost; sessionId?: string }) {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [loadError, setLoadError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [agent, setAgent] = useState<{ id: string; name: string }>({ id: "native:jaeger", name: "Jaeger" });
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState<TurnHandle | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [listening, setListening] = useState<"dictation" | "voice" | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const voiceHost = "micStart" in host ? (host as ChatHost & VoiceHost) : undefined;
  const [voiceReady, setVoiceReady] = useState(host.capabilities.voice);

  // Ask the shell for mic + tts once per host; re-render when it answers.
  useEffect(() => {
    let live = true;
    if (voiceHost) void voiceHost.probeCapabilities().then((c) => { if (live) setVoiceReady(c.voice); });
    return () => { live = false; };
  }, [voiceHost]);

  useEffect(() => {
    let live = true;
    setSession(null);
    setLoadError(undefined);
    stick.current = true;
    if (sessionId) host.sessions.load(sessionId).then(
      (s) => { if (live) setSession(s); },
      (error: unknown) => { if (live) setLoadError(String((error as Error)?.message ?? error)); },
    );
    return () => { live = false; };
  }, [host, sessionId, attempt]);

  // The agent this chat talks to: pill, placeholder and tint.
  useEffect(() => {
    const agentId = session?.agentId ?? "native:jaeger";
    let live = true;
    void host.listAgents?.().then((agents) => {
      const found = agents.find((a) => a.id === agentId);
      if (live) setAgent({ id: agentId, name: found?.name ?? (agentId === "native:jaeger" ? "Jaeger" : agentId) });
    }, () => {});
    return () => { live = false; };
  }, [host, session?.agentId]);

  // Follow new content only while the reader is at the bottom.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [session]);
  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX;
    stick.current = near;
    setAtBottom(near);
  };
  const jumpToLatest = () => {
    const el = scroller.current;
    if (!el) return;
    stick.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const updateTurn = useCallback((turnId: string, fn: (turn: ChatTurn) => ChatTurn) => {
    setSession((s) => (s ? { ...s, turns: s.turns.map((t) => (t.turnId === turnId ? fn(t) : t)) } : s));
  }, []);

  const send = (text = draft, speakReply = false) => {
    const message = text.trim();
    if (!message || !session || active) return;
    const turnId = crypto.randomUUID();
    setDraft("");
    stick.current = true;
    setSession({ ...session, turns: [...session.turns, { turnId, message, parts: [], state: "pending", createdAt: Date.now() }] });
    let finished: ChatTurn | undefined;
    const handle = host.startTurn({ sessionId: session.id, turnId, message }, (part) => updateTurn(turnId, (t) => (finished = { ...t, parts: applyPart(t.parts, part) })));
    setActive(handle);
    void handle.done.then(({ state }) => {
      updateTurn(turnId, (t) => ({ ...t, state }));
      setActive(null);
      if (speakReply && state === "complete" && finished) voiceHost?.speak(replyText(finished));
    });
  };
  const stop = () => active?.cancel();

  const toggleListening = async (mode: "dictation" | "voice") => {
    if (!voiceHost) return;
    if (listening) {
      const was = listening;
      setListening(null);
      const transcript = (await voiceHost.micStop()).trim();
      if (!transcript) return;
      if (was === "voice") send(transcript, true);
      else setDraft((d) => (d ? `${d} ${transcript}` : transcript));
      return;
    }
    voiceHost.stopSpeaking();
    setListening(mode);
    await voiceHost.micStart();
  };

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

  const links: Links = { onCopy: (text) => void host.copy(text), onOpen: (url) => host.openExternal(url) };
  const voice = voiceReady && Boolean(voiceHost);
  const hasText = Boolean(draft.trim());
  const tint = { "--jg-agent-color": avatarColor(agent.id) } as CSSProperties;
  return (
    <div className="jg-chat" style={tint}>
      <div className="jg-chat__band" data-aether-window-drag-region>
        <button type="button" className="jg-agent-pill" title={`${agent.name} details`} onClick={() => host.openDetails?.(agent.id)}>
          <AgentAvatar id={agent.id} name={agent.name} size={20} />
          <span>{agent.name}</span>
        </button>
      </div>
      <div className="jg-chat__scroll" ref={scroller} onScroll={onScroll}>
        <div className="jg-chat__column">
          {loadError && <ErrorState title="Couldn't load this chat" error={loadError} onRetry={() => setAttempt((n) => n + 1)} />}
          {session && !session.turns.length && <p className="jg-chat__empty">What should we work on?</p>}
          {session?.turns.map((turn, index) => (
            <section key={turn.turnId} className="jg-turn">
              {needsSeparator(session.turns[index - 1]?.createdAt, turn.createdAt) && (
                <div className="jg-separator" role="separator">{separatorLabel(turn.createdAt!)}</div>
              )}
              {turn.message && <div className="jg-bubble jg-bubble--user">{turn.message}</div>}
              {segments(turn.parts).map((seg, i) =>
                "marker" in seg ? <HandoffMarker key={i} part={seg.marker} onOpen={host.openHandoff ? (id) => host.openHandoff?.(id) : undefined} />
                : "card" in seg ? <Card key={i} part={seg.card} onDecide={decide(turn.turnId)} />
                : <div key={i} className="jg-bubble jg-bubble--assistant">{seg.bubble.map((p, j) => <BubblePart key={j} part={p} links={links} />)}</div>)}
              {turn.state === "pending" && !turn.parts.some((p) => p.kind === "markdownContent" && p.text) && <Typing />}
            </section>
          ))}
        </div>
      </div>
      {!atBottom && (
        <button type="button" className="jg-jump" aria-label="Scroll to bottom" onClick={jumpToLatest}><ArrowDownIcon /></button>
      )}
      <form className="jg-composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <button type="button" className="jg-composer__icon jg-composer__icon--filled" aria-label="Attach"><PlusIcon /></button>
        <textarea className="jg-composer__input" rows={1} placeholder={listening ? "Listening… tap again to stop" : `Message ${agent.name}`} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} aria-label="Message" />
        {voice && (
          <button type="button" className={`jg-composer__icon jg-composer__icon--filled${listening === "dictation" ? " is-listening" : ""}`}
            aria-label={listening === "dictation" ? "Stop dictation" : "Start voice input"} aria-pressed={listening === "dictation"}
            disabled={listening === "voice"} onClick={() => void toggleListening("dictation")}><MicIcon /></button>
        )}
        {active
          ? <button type="button" className="jg-send" aria-label="Stop (⌘Esc)" onClick={stop}><StopIcon /></button>
          : hasText || !voice
            ? <button type="submit" className="jg-send" aria-label="Send" disabled={!hasText}><SendIcon /></button>
            : <button type="button" className={`jg-send${listening === "voice" ? " is-listening" : ""}`}
                aria-label={listening === "voice" ? "Stop and send" : "Start voice chat"} aria-pressed={listening === "voice"}
                disabled={listening === "dictation"} onClick={() => void toggleListening("voice")}><WaveIcon /></button>}
      </form>
    </div>
  );
}
