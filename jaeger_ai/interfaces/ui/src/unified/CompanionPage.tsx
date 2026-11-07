import { useEffect, useState } from "react";
import type { JaegerSource, Notifications } from "../api/source";
import type { Agent } from "../api/types";
import { AutomationsPanel } from "../automations/AutomationsPanel";
import { LibraryPanel } from "../library/LibraryPanel";
import { TaskArtifacts } from "../library/TaskArtifacts";
import { StudioPage } from "./StudioPage";
import { PageHead, Segmented } from "./ui";
import "./companion.css";

type Props = { page: "library" | "automations" | "feed"; source: JaegerSource; agents: Agent[]; onNavigate(to: string): void };
export function CompanionPage({ page, source, agents, onNavigate }: Props) {
  const [section, setSection] = useState<"media" | "documents" | "outputs">("media");
  return <div className="jg-companion-page">
    <PageHead title={page === "library" ? "Library" : page === "automations" ? "Automations" : "Feed"}
      subtitle={page === "library" ? "Your creations, saved documents and work from your team." : page === "automations" ? "The routines Jaeger runs for you. Review schedules and see what happened." : "Updates from your agent."} />
    {page === "library" && <>
      <Segmented label="Library section" value={section} onChange={setSection} options={[{value:"media",label:"Media"},{value:"documents",label:"Documents"},{value:"outputs",label:"Outputs"}]} />
      {section === "media" && <StudioPage source={source} agents={agents} onNavigate={onNavigate} initialSection="library" />}
      {section === "documents" && (source.library ? <LibraryPanel controls={source.library} artifacts={source.taskArtifacts} /> : <Unavailable name="Document library" />)}
      {section === "outputs" && (source.taskArtifacts ? <TaskArtifacts controls={source.taskArtifacts} /> : <Unavailable name="Task outputs" />)}
    </>}
    {page === "automations" && (source.schedules ? <AutomationsPanel controls={source.schedules} /> : <Unavailable name="Automations" />)}
    {page === "feed" && (source.notifications ? <Feed controls={source.notifications} /> : <Unavailable name="Agent updates" />)}
  </div>;
}
function Unavailable({name}: {name:string}) { return <p role="status">{name} is not available on this connection.</p>; }
function Feed({ controls }: { controls: Notifications }) {
  const [data, setData] = useState<Awaited<ReturnType<Notifications["read"]>>>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setData(undefined); setError("");
    controls.read().then(value => { if (live) setData(value); }, e => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [controls, attempt]);
  return <section className="jg-companion-feed" aria-label="Agent updates">
    <button type="button" onClick={() => setAttempt(n => n+1)}>Refresh</button>
    {error && <p role="alert">Could not load updates: {error}</p>}
    {!data && !error && <p role="status">Loading updates...</p>}
    {data && !data.notifications.length && <div className="jg-companion-empty"><h2>You are caught up</h2><p>Jaeger's updates appear here when there is something to share.</p></div>}
    {data?.notifications.map(item => <article key={item.event_id} className="jg-companion-feed__item"><small>{item.agent_id || "Jaeger"} · {new Date(item.timestamp * 1000).toLocaleString()}</small><h2>{item.title}</h2>{item.status && <p>{item.status}</p>}<small>{item.unread ? "Unread" : "Read"}</small></article>)}
    <p className="jg-companion-note">This feed shows agent activity. Curated articles and proactive ideas are not connected here yet.</p>
  </section>;
}
