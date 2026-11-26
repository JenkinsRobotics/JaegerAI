import { useEffect, useRef, useState } from "react";
import type { ChatMessage, GatewayEventEnvelope, SessionSummary } from "@jaeger/ui-protocol";
import { HttpSseTransport, SessionStore } from "@jaeger/ui-sdk";
import { ApprovalCard, ScrollFollowMachine, ThinkingDisclosure, ToolCallCard } from "@jaeger/ui-kit";
import { JAEGER_DESTINATIONS, type DestinationId } from "./destinations";

interface GatewayRuntimeSnapshot {
  model?: string;
  tools_count?: number;
  uptime_s?: number;
  all_green?: boolean;
  workspace?: string;
  state_dir?: string;
}

interface ToolRow {
  name: string;
  description: string;
  tier: string;
  read_only: boolean;
  source: string;
}

interface WorkflowRow {
  run_id: string;
  name: string;
  status: string;
  total_steps: number;
  next_ready: string[];
  steps?: Array<{ id: string; name: string; record?: { status: string } }>;
}

interface FactRow {
  subject: string;
  key: string;
  value: string;
  category?: string | null;
}

function NavIcon({ id }: { id: DestinationId }) {
  const paths: Record<DestinationId, string> = {
    chat: "M2.5 4A1.5 1.5 0 0 1 4 2.5h8A1.5 1.5 0 0 1 13.5 4v6A1.5 1.5 0 0 1 12 11.5H6l-3 2.5v-2.5A1.5 1.5 0 0 1 2.5 10V4Z",
    tasks: "M3 4.5h10M3 8h10M3 11.5h6",
    tools: "M10.5 2.5a3 3 0 0 0-3.7 3.7L2.5 10.5a1.4 1.4 0 1 0 2 2l4.3-4.3a3 3 0 0 0 3.7-3.7L11 6l-1-1 1.5-1.5Z",
    memory: "M8 2.5c2.8 0 5 1 5 2.3v6.4c0 1.3-2.2 2.3-5 2.3s-5-1-5-2.3V4.8c0-1.3 2.2-2.3 5-2.3Z",
    settings: "M8 5.2A2.8 2.8 0 1 0 8 10.8 2.8 2.8 0 0 0 8 5.2ZM2.5 8h1.4m8.2 0h1.4M8 2.5v1.4m0 8.2v1.4",
  };
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d={paths[id]} stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export interface JaegerAppProps {
  baseUrl?: string;
}

export function JaegerApp({ baseUrl = "" }: JaegerAppProps) {
  const [dest, setDest] = useState<DestinationId>("chat");
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
  );
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [runStatus, setRunStatus] = useState<string>("idle");
  const [health, setHealth] = useState<GatewayRuntimeSnapshot>({});
  const [tools, setTools] = useState<ToolRow[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowRow[]>([]);
  const [facts, setFacts] = useState<FactRow[]>([]);
  const [models, setModels] = useState<Array<{ id: string }>>([]);
  const [activeModel, setActiveModel] = useState("");
  const [factKey, setFactKey] = useState("");
  const [factVal, setFactVal] = useState("");

  const transportRef = useRef<HttpSseTransport | null>(null);
  const storeRef = useRef<SessionStore | null>(null);
  const scrollMachineRef = useRef(new ScrollFollowMachine());
  const scrollEndRef = useRef<HTMLDivElement | null>(null);
  const [showJump, setShowJump] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  if (!transportRef.current) {
    transportRef.current = new HttpSseTransport({ baseUrl });
  }

  const refreshSessions = async () => {
    const res = await fetch(`${baseUrl}/v1/sessions`);
    if (!res.ok) return;
    const data = (await res.json()) as { sessions?: SessionSummary[] };
    const rows = data.sessions ?? [];
    setSessions(rows);
    if (!activeSessionId && rows.length > 0) {
      setActiveSessionId(rows[0].session_id);
    }
  };

  const createNewSession = async () => {
    const res = await fetch(`${baseUrl}/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "New Conversation" }),
    });
    if (!res.ok) return;
    const data = (await res.json()) as { session: SessionSummary };
    setSessions((prev) => [data.session, ...prev]);
    setActiveSessionId(data.session.session_id);
    setDest("chat");
  };

  useEffect(() => {
    void refreshSessions();
    void fetch(`${baseUrl}/health`)
      .then((r) => r.json())
      .then((d: GatewayRuntimeSnapshot) => setHealth(d))
      .catch(() => {});
  }, [baseUrl]);

  useEffect(() => {
    if (dest === "tools") {
      void fetch(`${baseUrl}/v1/tools`)
        .then((r) => r.json())
        .then((d: { tools?: ToolRow[] }) => setTools(d.tools ?? []))
        .catch(() => {});
    } else if (dest === "tasks") {
      void fetch(`${baseUrl}/v1/workflows`)
        .then((r) => r.json())
        .then((d: { workflows?: WorkflowRow[] }) => setWorkflows(d.workflows ?? []))
        .catch(() => {});
    } else if (dest === "memory") {
      void fetch(`${baseUrl}/v1/memory/facts`)
        .then((r) => r.json())
        .then((d: { facts?: FactRow[] }) => setFacts(d.facts ?? []))
        .catch(() => {});
    } else if (dest === "settings") {
      void fetch(`${baseUrl}/v1/models`)
        .then((r) => r.json())
        .then((d: { active?: string; models?: Array<{ id: string }> }) => {
          setActiveModel(d.active ?? "");
          setModels(d.models ?? []);
        })
        .catch(() => {});
      void fetch(`${baseUrl}/health`)
        .then((r) => r.json())
        .then((d: GatewayRuntimeSnapshot) => setHealth(d))
        .catch(() => {});
    }
  }, [dest, baseUrl]);

  useEffect(() => {
    if (!activeSessionId || !transportRef.current) return;
    const abort = new AbortController();
    const store = new SessionStore(activeSessionId, transportRef.current);
    storeRef.current = store;

    const unsub = store.subscribe((snap) => {
      setMessages(snap.messages);
      setRunStatus(snap.status);
      scrollMachineRef.current.transition({ type: "CONTENT_APPENDED" });
      setShowJump(scrollMachineRef.current.showJumpButton);
      if (scrollMachineRef.current.shouldAutoScroll) {
        scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
      }
    });

    void fetch(`${baseUrl}/v1/sessions/${encodeURIComponent(activeSessionId)}/messages`)
      .then((r) => r.json())
      .then((d: { messages?: Array<{ id: number; role: "user" | "assistant"; content: string; created_at: number }> }) => {
        const hydrated: ChatMessage[] = (d.messages ?? []).map((m) => ({
          id: String(m.id),
          session_id: activeSessionId,
          role: m.role,
          content: m.content,
          parts: [{ type: "text", text: m.content }],
          created_at: m.created_at,
        }));
        setMessages(hydrated);
      })
      .catch(() => {});

    void transportRef.current
      .subscribe(
        activeSessionId,
        0,
        (env: GatewayEventEnvelope) => {
          store.applyEvent(env);
        },
        abort.signal,
      )
      .catch(() => {});

    return () => {
      abort.abort();
      unsub();
      store.dispose();
    };
  }, [activeSessionId, baseUrl]);

  const handleSend = async () => {
    const text = prompt.trim();
    if (!text) return;
    let sid = activeSessionId;
    if (!sid) {
      const res = await fetch(`${baseUrl}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text.slice(0, 48) }),
      });
      if (!res.ok) return;
      const created = (await res.json()) as { session: SessionSummary };
      sid = created.session.session_id;
      setSessions((prev) => [created.session, ...prev]);
      setActiveSessionId(sid);
    }
    setPrompt("");
    if (storeRef.current && sid === activeSessionId) {
      await storeRef.current.sendPrompt(text);
    } else if (transportRef.current) {
      await transportRef.current.submitRun(sid, text, `req_${Date.now()}`);
    }
  };

  const handleSaveFact = async () => {
    if (!factKey.trim() || !factVal.trim()) return;
    const res = await fetch(`${baseUrl}/v1/memory/facts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: factKey.trim(), value: factVal.trim() }),
    });
    if (res.ok) {
      setFactKey("");
      setFactVal("");
      const list = (await (await fetch(`${baseUrl}/v1/memory/facts`)).json()) as { facts?: FactRow[] };
      setFacts(list.facts ?? []);
    }
  };

  const handleSelectModel = async (modelId: string) => {
    const res = await fetch(`${baseUrl}/v1/models/select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelId }),
    });
    if (res.ok) {
      const data = (await res.json()) as { active?: string };
      setActiveModel(data.active ?? modelId);
    }
  };

  return (
    <div className="jg-app" data-testid="jaeger-modular-app">
      <aside className="jg-sidebar">
        <div className="jg-brand">
          <span>Jaeger Modular</span>
          <button
            type="button"
            className="jg-btn"
            style={{ padding: "3px 7px", fontSize: "11px" }}
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </div>

        <nav className="jg-nav" aria-label="Primary navigation">
          {JAEGER_DESTINATIONS.map((d) => (
            <button
              key={d.id}
              type="button"
              className="jg-nav-btn"
              data-active={dest === d.id}
              onClick={() => setDest(d.id)}
            >
              <NavIcon id={d.id} />
              <span>{d.label}</span>
            </button>
          ))}
        </nav>

        <div style={{ borderTop: "1px solid var(--jg-border-subtle)", paddingTop: "10px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0 6px 6px" }}>
            <span style={{ fontSize: "11px", color: "var(--jg-text-muted)", fontWeight: 600 }}>SESSIONS</span>
            <button type="button" className="jg-btn" style={{ padding: "2px 7px", fontSize: "11px" }} onClick={() => void createNewSession()}>
              + New
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
            {sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                className="jg-nav-btn"
                data-active={dest === "chat" && activeSessionId === s.session_id}
                onClick={() => {
                  setActiveSessionId(s.session_id);
                  setDest("chat");
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="jg-main">
        <header className="jg-header">
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <strong>{JAEGER_DESTINATIONS.find((d) => d.id === dest)?.label}</strong>
            <span className="jg-pill">{health.model || "modular-runtime"}</span>
            {dest === "chat" && <span className="jg-pill">{runStatus}</span>}
          </div>
          <span className="jg-pill" style={{ color: health.all_green ? "var(--jg-status-success)" : "var(--jg-text-secondary)" }}>
            {health.all_green ? "Gateway Online" : "Connecting…"}
          </span>
        </header>

        {dest === "chat" && (
          <>
            <div
              className="jg-content"
              onScroll={(e) => {
                const el = e.currentTarget;
                const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
                scrollMachineRef.current.transition({ type: nearBottom ? "REACHED_BOTTOM" : "USER_SCROLL_UP" });
                setShowJump(scrollMachineRef.current.showJumpButton);
              }}
            >
              {messages.length === 0 && (
                <div className="jg-card" style={{ maxWidth: "680px", margin: "40px auto", textAlign: "center" }}>
                  <h2 style={{ margin: "0 0 8px", fontSize: "18px" }}>Jaeger Standalone Modular Framework</h2>
                  <p style={{ margin: 0, color: "var(--jg-text-secondary)", fontSize: "13.5px" }}>
                    100% modular backend (15 standalone packages) + modular frontend (@jaeger/ui-*).
                    Ask a question, edit workspace files, run sandboxed commands, or manage workflows.
                  </p>
                </div>
              )}
              {messages.map((m) => (
                <div key={m.id} className="jg-msg" data-role={m.role}>
                  <div style={{ fontSize: "11px", color: "var(--jg-text-muted)", marginBottom: "4px", fontWeight: 600 }}>
                    {m.role === "user" ? "You" : "Jaeger"}
                  </div>
                  {m.parts.map((part, idx) => {
                    if (part.type === "thinking") return <ThinkingDisclosure key={idx} part={part} />;
                    if (part.type === "tool") return <ToolCallCard key={part.callId} part={part} />;
                    if (part.type === "approval") {
                      return (
                        <ApprovalCard
                          key={part.approvalId}
                          approval={part}
                          onDecision={(aid, dec) => void transportRef.current?.resolveApproval(aid, dec)}
                        />
                      );
                    }
                    return (
                      <div key={idx} style={{ whiteSpace: "pre-wrap" }}>
                        {part.text}
                      </div>
                    );
                  })}
                </div>
              ))}
              <div ref={scrollEndRef} />
            </div>

            {showJump && (
              <div style={{ textAlign: "center", paddingBottom: "6px" }}>
                <button
                  type="button"
                  className="jg-btn"
                  onClick={() => {
                    scrollMachineRef.current.transition({ type: "JUMP_REQUESTED" });
                    scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
                    setShowJump(false);
                  }}
                >
                  Jump to latest
                </button>
              </div>
            )}

            <form
              className="jg-composer"
              onSubmit={(e) => {
                e.preventDefault();
                void handleSend();
              }}
            >
              <input
                className="jg-input"
                placeholder="Ask Jaeger to inspect code, run checks, organize mail, or create a workflow…"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
              <button type="submit" className="jg-btn jg-btn-primary" disabled={!prompt.trim()}>
                Send
              </button>
            </form>
          </>
        )}

        {dest === "tasks" && (
          <div className="jg-content" style={{ display: "grid", gap: "12px", maxWidth: "860px" }}>
            {workflows.length === 0 ? (
              <div className="jg-card">No active durable workflows yet. Ask Jaeger in Chat to create one.</div>
            ) : (
              workflows.map((wf) => (
                <div key={wf.run_id} className="jg-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>{wf.name}</strong>
                    <span className="jg-pill">{wf.status}</span>
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--jg-text-secondary)", marginTop: "6px" }}>
                    Run {wf.run_id} · {wf.total_steps} step(s)
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {dest === "tools" && (
          <div className="jg-content" style={{ display: "grid", gap: "10px", maxWidth: "920px" }}>
            {tools.map((t) => (
              <div key={t.name} className="jg-card" style={{ display: "flex", justifyContent: "space-between", gap: "12px" }}>
                <div>
                  <strong>{t.name}</strong>
                  <div style={{ fontSize: "12.5px", color: "var(--jg-text-secondary)", marginTop: "3px" }}>
                    {t.description}
                  </div>
                </div>
                <span className="jg-pill">{t.read_only ? "read-only" : t.tier}</span>
              </div>
            ))}
          </div>
        )}

        {dest === "memory" && (
          <div className="jg-content" style={{ display: "grid", gap: "14px", maxWidth: "820px" }}>
            <div className="jg-card" style={{ display: "flex", gap: "8px" }}>
              <input className="jg-input" placeholder="Fact key" value={factKey} onChange={(e) => setFactKey(e.target.value)} />
              <input className="jg-input" placeholder="Fact value" value={factVal} onChange={(e) => setFactVal(e.target.value)} />
              <button type="button" className="jg-btn jg-btn-primary" onClick={() => void handleSaveFact()}>
                Save
              </button>
            </div>
            {facts.map((f) => (
              <div key={`${f.subject}:${f.key}`} className="jg-card" style={{ display: "flex", justifyContent: "space-between" }}>
                <div>
                  <strong>{f.key}</strong>: {f.value}
                </div>
                <span className="jg-pill">{f.subject}</span>
              </div>
            ))}
          </div>
        )}

        {dest === "settings" && (
          <div className="jg-content" style={{ display: "grid", gap: "14px", maxWidth: "760px" }}>
            <div className="jg-card">
              <h3 style={{ margin: "0 0 10px", fontSize: "14px" }}>Active Model</h3>
              <select
                className="jg-input"
                value={activeModel}
                onChange={(e) => void handleSelectModel(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </select>
            </div>
            <div className="jg-card">
              <h3 style={{ margin: "0 0 8px", fontSize: "14px" }}>Runtime Diagnostics</h3>
              <pre style={{ margin: 0, fontSize: "12px", fontFamily: "var(--jg-font-mono)", whiteSpace: "pre-wrap" }}>
                {JSON.stringify(health, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
