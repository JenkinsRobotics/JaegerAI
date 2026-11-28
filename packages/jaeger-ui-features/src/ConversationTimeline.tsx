import { useEffect, useState } from "react";

export interface ConversationTopic {
  id: number;
  created_at: number;
  excerpt: string;
  reply?: string;
}

const checkpointKey = "jaeger.chat.timeline.checkpoints.v1";
const checkpointEvent = "jaeger:checkpoints-changed";

function readCheckpoints(): ConversationTopic[] {
  try {
    const stored = JSON.parse(localStorage.getItem(checkpointKey) ?? "[]");
    return Array.isArray(stored) ? stored.filter((item: ConversationTopic | null) =>
      item && Number.isSafeInteger(item.id) && typeof item.excerpt === "string" && Number.isFinite(item.created_at)) : [];
  } catch {
    return [];
  }
}

function topicLabel(topic: ConversationTopic) {
  const text = topic.excerpt.trim().replace(/\s+/g, " ");
  return text.length > 100 ? `${text.slice(0, 97)}…` : text || "Message";
}

const topicTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function ConversationTimeline({
  baseUrl,
  open,
  onToggle,
  visibleTopicId,
  loadedTopics,
  busy,
  onJump,
  onResume,
  onLatest,
  mode = "full",
}: {
  baseUrl: string;
  open: boolean;
  onToggle?: () => void;
  visibleTopicId?: number;
  loadedTopics: ConversationTopic[];
  busy: boolean;
  onJump: (id: number) => void;
  onResume: (topic: ConversationTopic) => void;
  onLatest: () => void;
  mode?: "full" | "rail" | "panel";
}) {
  const [query, setQuery] = useState("");
  const [remote, setRemote] = useState<ConversationTopic[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<ConversationTopic>();
  const [checkpoints, setCheckpoints] = useState(readCheckpoints);
  const term = query.trim();
  const latestLoaded = loadedTopics.at(-1)?.id;

  useEffect(() => {
    const sync = () => setCheckpoints(readCheckpoints());
    window.addEventListener(checkpointEvent, sync);
    return () => window.removeEventListener(checkpointEvent, sync);
  }, []);

  useEffect(() => {
    if (!open || mode === "rail") return;
    const controller = new AbortController();
    setPending(true);
    setError("");
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`${baseUrl}/v1/chat/topics?q=${encodeURIComponent(term)}`, { signal: controller.signal });
        if (!response.ok) throw new Error("Could not load topics.");
        const body: { topics: ConversationTopic[] } = await response.json();
        if (!controller.signal.aborted) setRemote(body.topics);
      } catch {
        if (!controller.signal.aborted) setError("Could not load the topic index. Try searching again.");
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    }, term ? 180 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [baseUrl, open, mode, term, latestLoaded]);

  const topics = term ? remote : [...new Map([...remote, ...loadedTopics].map((topic) => [topic.id, topic])).values()]
    .sort((a, b) => a.id - b.id);
  const activeIndex = loadedTopics.findIndex(topic => topic.id === visibleTopicId);
  const railStart = Math.max(0, Math.min(loadedTopics.length - 44,
    (activeIndex < 0 ? loadedTopics.length : activeIndex) - 22));
  const railTopics = loadedTopics.slice(railStart, railStart + 44);
  const current = selected ?? loadedTopics.find((topic) => topic.id === visibleTopicId) ?? loadedTopics.at(-1);
  const currentSaved = !!current && checkpoints.some((topic) => topic.id === current.id);

  function toggleCheckpoint(topic: ConversationTopic) {
    const saved = checkpoints.some((item) => item.id === topic.id);
    const next = saved ? checkpoints.filter((item) => item.id !== topic.id)
      : [...checkpoints, topic].sort((a, b) => a.id - b.id);
    try {
      localStorage.setItem(checkpointKey, JSON.stringify(next));
      setCheckpoints(next);
      window.dispatchEvent(new Event(checkpointEvent));
    } catch {
      setError("The browser could not save the checkpoint.");
    }
  }

  if (mode === "rail") {
    if (!railTopics.length) return null;
    return (
      <aside className="jg-timeline jg-timeline--rail-only" aria-label="Conversation timeline">
        <div className="jg-timeline-rail">
          <div className="jg-timeline-marks" aria-label="Visible timeline positions">
            {railTopics.map((topic, index) => {
              const saved = checkpoints.some(item => item.id === topic.id);
              return (
                <div className="jg-rail-stop" key={topic.id} data-upper={index < railTopics.length / 2 || undefined}
                  onKeyDown={event => {
                    if (event.key === "Escape") {
                      event.currentTarget.dataset.dismissed = "true";
                      event.currentTarget.querySelector<HTMLButtonElement>(".jg-timeline-mark")?.focus();
                    }
                  }}
                  onPointerEnter={event => { delete event.currentTarget.dataset.dismissed; }}
                  onFocus={event => { if (!event.currentTarget.contains(event.relatedTarget)) delete event.currentTarget.dataset.dismissed; }}>
                  <button className="jg-timeline-mark" type="button" aria-label={`Jump to ${topicLabel(topic)}`}
                    aria-current={visibleTopicId === topic.id ? "location" : undefined}
                    data-checkpoint={saved || undefined} disabled={busy} onClick={() => onJump(topic.id)}>
                    <span />
                  </button>
                  <div className="jg-rail-preview">
                    <div className="jg-rail-preview-head">
                      <strong>{topicLabel(topic)}</strong>
                      <button type="button" aria-label={saved ? "Remove checkpoint" : "Save checkpoint"}
                        aria-pressed={saved} onClick={() => toggleCheckpoint(topic)}>
                        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
                          <path d="M4 2h8v12l-4-3-4 3z" stroke="currentColor" fill={saved ? "currentColor" : "none"} />
                        </svg>
                      </button>
                    </div>
                    {topic.reply && <p>{topic.reply}</p>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </aside>
    );
  }

  const trackerSection = (
    <section
      id="conversation-tracker"
      className={mode === "panel" ? "jg-timeline-panel jg-timeline-panel--embedded" : "jg-timeline-panel"}
      hidden={!open}
    >
      <header className="jg-timeline-heading">
        <h2>Conversation tracker</h2>
        {onToggle && mode !== "panel" && (
          <button type="button" className="jg-ushell__icon-btn" aria-label="Close conversation tracker"
            onClick={onToggle}>×</button>
        )}
      </header>
      <input className="jg-input" type="search" aria-label="Search past topics" placeholder="Search past topics"
        value={query} maxLength={200} onChange={(event) => setQuery(event.target.value)} />
      {error && <p role="alert">{error}</p>}
      {current && (
        <div className="jg-timeline-current">
          <strong>{topicLabel(current)}</strong>
          <div className="jg-timeline-actions">
            <button type="button" className="jg-btn" disabled={busy} onClick={() => onJump(current.id)}>Jump to message</button>
            <button type="button" className="jg-btn" onClick={() => onResume(current)}>Resume topic</button>
            <button type="button" className="jg-btn" aria-pressed={currentSaved} onClick={() => toggleCheckpoint(current)}>
              {currentSaved ? "Remove checkpoint" : "Save checkpoint"}
            </button>
          </div>
        </div>
      )}
      <div className="jg-timeline-scroll">
        <section aria-labelledby="chat-checkpoints-label">
          <h3 id="chat-checkpoints-label">Checkpoints</h3>
          {checkpoints.length ? (
            <ul className="jg-timeline-list">
              {checkpoints.map((topic) => (
                <li key={topic.id}><button type="button" aria-pressed={current?.id === topic.id}
                  onClick={() => { setSelected(topic); onJump(topic.id); }}>{topicLabel(topic)}</button></li>
              ))}
            </ul>
          ) : <p className="jg-muted">Save a topic to find it here later.</p>}
        </section>
        <section aria-labelledby="chat-topics-label">
          <h3 id="chat-topics-label">Topic highlights</h3>
          {pending && term ? <p role="status">Searching…</p> : (
            <ul className="jg-timeline-list">
              {topics.map((topic) => (
                <li key={topic.id}><button type="button" aria-pressed={current?.id === topic.id}
                  onClick={() => { setSelected(topic); onJump(topic.id); }}>
                  <span>{topicLabel(topic)}</span>
                  <time dateTime={new Date(topic.created_at * 1000).toISOString()}>{topicTime.format(topic.created_at * 1000)}</time>
                </button></li>
              ))}
            </ul>
          )}
          {!pending && !topics.length && <p className="jg-muted">No matching topics.</p>}
        </section>
      </div>
      <button type="button" className="jg-btn" onClick={() => { setSelected(undefined); onLatest(); }}>Jump to latest</button>
    </section>
  );

  if (mode === "panel") {
    return trackerSection;
  }

  return (
    <aside className="jg-timeline" aria-label="Conversation timeline">
      <div className="jg-timeline-rail">
        {onToggle && (
          <button type="button" className="jg-timeline-toggle" aria-label="Conversation tracker"
            title="Conversation tracker" aria-expanded={open} aria-controls="conversation-tracker"
            onClick={onToggle}>
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true">
              <path d="M5 3v14M8 5h7m-7 5h5m-5 5h7" strokeLinecap="round" strokeWidth="1.5" />
            </svg>
          </button>
        )}
        <div className="jg-timeline-marks" aria-label="Visible timeline positions">
          {railTopics.map((topic) => (
            <button className="jg-timeline-mark" key={topic.id} type="button"
              title={topicLabel(topic)} aria-label={`Jump to ${topicLabel(topic)}`}
              aria-current={visibleTopicId === topic.id ? "location" : undefined}
              data-checkpoint={checkpoints.some((item) => item.id === topic.id) || undefined}
              disabled={busy} onClick={() => { setSelected(topic); onJump(topic.id); }}>
              <span />
            </button>
          ))}
        </div>
      </div>
      {trackerSection}
    </aside>
  );
}
