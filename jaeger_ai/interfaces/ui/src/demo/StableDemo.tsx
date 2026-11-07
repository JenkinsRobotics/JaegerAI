import { useEffect, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { ChatPane } from "../chat/ChatPane";
import { WebHost } from "../chat/webHost";
import { contractHome, httpGetJson } from "../chat/homeSession";
import { TasksWorkspace } from "../unified/TasksWorkspace";
import { ApprovalTray } from "../unified/ApprovalTray";
import { ToastProvider } from "../unified/ui";
import "../unified/unified.css";
import "../unified/design.css";
import "./stableDemo.css";

export const DEMO_SESSION_KEY = "jaeger.stable-demo.session.v1";
function storedSession() { try { return localStorage.getItem(DEMO_SESSION_KEY) || ""; } catch { return ""; } }
/** Recovery surface: existing chat renderer and Gateway-owned task runner, no parallel backend. */
export function StableDemo({ source }: { source: JaegerSource }) {
  const [page, setPage] = useState<"chat" | "tasks">("chat");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [session, setSession] = useState(storedSession);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const host = useMemo(() => {
    const h = new WebHost(source);
    h.home = contractHome(httpGetJson(), { agentName: id => id === "native:jaeger" ? "Jaeger" : id, onCursor: (sid, cursor) => h.noteCursor(sid, cursor) }, source.stream.bind(source));
    return h;
  }, [source]);
  useEffect(() => {
    let live = true;
    Promise.all([source.agents(), session ? source.session(session) : Promise.resolve(null)]).then(([rows]) => {
      if (live) { setAgents(rows); setReady(true); setError(""); }
    }).catch((e: unknown) => { if (live) { setError(String((e as Error).message)); setReady(false); } });
    return () => { live = false; };
  }, [source, session]);
  const start = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      // Independent lead conversation: never reuse or replay the stuck Builder request.
      const row = await source.createSession({ agent_id: "native:jaeger", title: "Jaeger stable chat" });
      localStorage.setItem(DEMO_SESSION_KEY, row.session_id); setSession(row.session_id);
    } catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(false); }
  };
  const agent = agents.find(a => a.id === "native:jaeger");
  return <ToastProvider><div className="jg-stable-demo" data-stable-demo="1">
    <header className="jg-stable-demo__header">
      <strong>Jaeger</strong><span role="status">{error ? "Connection error" : ready ? "Live Gateway" : "Connecting…"}</span>
      <nav aria-label="Demo navigation">
        <button type="button" aria-current={page === "chat" ? "page" : undefined} onClick={() => setPage("chat")}>Chat</button>
        <button type="button" aria-current={page === "tasks" ? "page" : undefined} onClick={() => setPage("tasks")}>Tasks</button>
      </nav>
      <ApprovalTray source={source} onOpenChat={() => setPage("chat")} />
      <a href="/?full=1">Full workspace (preview)</a>
    </header>
    {error && <p role="alert">{error} <button onClick={() => location.reload()}>Reconnect</button></p>}
    <section className="jg-stable-demo__body" hidden={page !== "chat"} aria-label="Chat">
      {session && ready ? <ChatPane host={host} sessionId={session} agents={agent ? [agent] : agents} /> :
        <div className="jg-stable-demo__empty"><h1>Chat with Jaeger</h1><p>A saved conversation with live replies. Tasks continue on the Gateway when you leave this page.</p>
        <button type="button" disabled={!ready || busy} onClick={() => void start()}>{busy ? "Opening…" : "Start conversation"}</button></div>}
    </section>
    <section className="jg-stable-demo__body" hidden={page !== "tasks"} aria-label="Tasks">
      {page === "tasks" && <TasksWorkspace source={source} agents={agents} params={new URLSearchParams()} onNavigate={(to) => { location.href = `${to}${to.includes("?") ? "&" : "?"}full=1`; }} />}
    </section>
    <footer className="jg-stable-demo__footer">Chat history and tasks are stored by Gateway. Automatic recovery after worker interruption is not verified.</footer>
  </div></ToastProvider>;
}
