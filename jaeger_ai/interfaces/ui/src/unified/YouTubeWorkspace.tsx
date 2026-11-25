import { useEffect, useRef, useState } from "react";
import { YouTubePage } from "../research/YouTubePage";
import { PageHead, Segmented, useToast } from "./ui";
import "./youtubeWorkspace.css";

const KEY = "jaeger.youtube.production.v1";
const stages = ["Research", "Script", "Voice & visuals", "Edit & captions", "Review", "Export"];
const stageHelp = [
  "Collect sources, examples, and the question the video will answer.",
  "Write the hook and outline the steps viewers should be able to repeat.",
  "Plan narration, shots, and the visuals you’ll need.",
  "Track edit decisions, captions, and any missing clips.",
  "Check factual claims, source links, audio, and the reproducible steps.",
  "Record the final files and handoff notes. Exporting this brief won’t publish a video.",
];
type Brief = { version: 1; title: string; audience: string; format: string; goal: string; notes: string[]; reviewed: boolean[] };
const blank = (): Brief => ({ version: 1, title: "", audience: "", format: "Short · 30–60 seconds", goal: "", notes: stages.map(() => ""), reviewed: stages.map(() => false) });
export function parseBrief(value: unknown): Brief {
  const b = value as Brief;
  if (!b || b.version !== 1 || ![b.title,b.audience,b.format,b.goal].every(v => typeof v === "string" && v.length <= 20000)
    || !Array.isArray(b.notes) || b.notes.length !== stages.length || !b.notes.every(v => typeof v === "string" && v.length <= 100000)
    || !Array.isArray(b.reviewed) || b.reviewed.length !== stages.length || !b.reviewed.every(v => typeof v === "boolean")) throw new Error("Choose a Jaeger production brief exported from this workspace.");
  return { version: 1, title: b.title, audience: b.audience, format: b.format, goal: b.goal, notes: b.notes, reviewed: b.reviewed };
}
export function productionPrompt(b: Brief, stage: number) {
  return `Help me produce an original YouTube video.\nTitle: ${b.title}\nAudience: ${b.audience}\nFormat: ${b.format}\nGoal: ${b.goal}\n\nCurrent stage: ${stages[stage]}\n${b.notes.map((n,i) => `${stages[i]}:\n${n}`).join("\n\n")}\n\nUse source links for factual claims. Check available tools before promising generation. Save usable outputs and explain any blocked steps. Ask before paid generation or publishing. Include instructions viewers can reproduce with their own accounts; never include credentials or private memory.`;
}
export function YouTubeWorkspace({ params, onNavigate }: { params?: URLSearchParams; onNavigate: (to: string) => void }) {
  const toast = useToast();
  const [view, setView] = useState<"production" | "research">(params?.has("job") ? "research" : "production");
  const [brief,setBrief] = useState<Brief>(() => { try { return parseBrief(JSON.parse(localStorage.getItem(KEY) || "null")); } catch { return blank(); } });
  const [briefOpen, setBriefOpen] = useState(() => !brief.title.trim());
  const [stage,setStage] = useState(0);
  const [saved,setSaved] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { try { localStorage.setItem(KEY,JSON.stringify(brief)); setSaved(true); } catch { setSaved(false); } },[brief]);
  const update = (key: "title" | "audience" | "format" | "goal", value: string) => setBrief(b => ({...b,[key]:value}));
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(brief,null,2)],{type:"application/json"}));
    const a = document.createElement("a"); a.href=url; a.download="jaeger-youtube-brief.json"; a.click(); URL.revokeObjectURL(url);
  };
  return <div className="jg-u-page jg-production">
    <PageHead title="YouTube" subtitle="Take one video from idea to a repeatable tutorial." />
    <div className="jg-production__toolbar"><Segmented label="YouTube view" value={view} onChange={setView} options={[{value:"production",label:"Video plan"},{value:"research",label:"Channel research"}]} /></div>
    {view === "research" ? <YouTubePage params={params} onNavigate={onNavigate} /> : <>
      <div className="jg-production__toolbar">
        <span role="status">{saved ? "Brief saved in this browser" : "Browser storage unavailable — export to keep your brief"}</span>
        <button className="jg-u-btn" onClick={() => file.current?.click()}>Import brief</button>
        <button className="jg-u-btn" onClick={download}>Export brief</button>
        <input ref={file} type="file" accept="application/json,.json" hidden onChange={async e => { const f=e.target.files?.[0]; e.target.value=""; if(!f)return; try { if(f.size>1000000)throw new Error("Brief must be smaller than 1 MB."); const next=parseBrief(JSON.parse(await f.text())); if(window.confirm("Replace this browser’s current brief with the imported brief?"))setBrief(next); } catch(err){toast((err as Error).message,"error");} }} />
      </div>
      <details className="jg-production__brief-panel" open={briefOpen} onToggle={e => setBriefOpen(e.currentTarget.open)}><summary>Video brief{brief.title.trim() ? ` · ${brief.title}` : ""}</summary>
      <section className="jg-production__brief" aria-label="Video brief">
        <label>Video idea<input className="jg-ui-input" value={brief.title} onChange={e=>update("title",e.target.value)} placeholder="A useful AI tool anyone can run" /></label>
        <label>Who is it for?<input className="jg-ui-input" value={brief.audience} onChange={e=>update("audience",e.target.value)} placeholder="People trying AI for the first time" /></label>
        <label>Format<select className="jg-ui-input" value={brief.format} onChange={e=>update("format",e.target.value)}><option>Short · 30–60 seconds</option><option>Tutorial · 5–10 minutes</option><option>Demo · 2–5 minutes</option></select></label>
        <label>What should viewers learn?<input className="jg-ui-input" value={brief.goal} onChange={e=>update("goal",e.target.value)} placeholder="A concrete result they can reproduce" /></label>
      </section></details>
      <div className="jg-production__work">
        <nav aria-label="Production stages">{stages.map((name,i)=><button className="jg-u-btn" key={name} aria-current={stage===i?"step":undefined} onClick={()=>setStage(i)}><span>{i+1}. {name}</span><span>{brief.reviewed[i]?"Reviewed":brief.notes[i].trim()?"Draft":""}</span></button>)}</nav>
        <section className="jg-production__editor" aria-label={`${stages[stage]} notes`}>
          <h2>{stages[stage]}</h2>
          <p>{stageHelp[stage]}</p>
          <label htmlFor="production-notes">Stage notes and outputs</label>
          <textarea id="production-notes" className="jg-ui-input" rows={10} value={brief.notes[stage]} onChange={e=>setBrief(b=>({...b,notes:b.notes.map((n,i)=>i===stage?e.target.value:n),reviewed:b.reviewed.map((v,i)=>i===stage?false:v)}))} />
          <div className="jg-production__toolbar"><label><input type="checkbox" checked={brief.reviewed[stage]} onChange={e=>setBrief(b=>({...b,reviewed:b.reviewed.map((v,i)=>i===stage?e.target.checked:v)}))} /> I reviewed this stage</label>
            {stage < stages.length - 1 && <button type="button" className="jg-u-btn" onClick={() => setStage(s => s + 1)}>Next stage</button>}</div>
          <div className="jg-production__toolbar"><button className="jg-u-btn jg-u-btn--primary" disabled={!brief.title.trim()} onClick={async()=>{try{await navigator.clipboard.writeText(productionPrompt(brief,stage));toast("Stage prompt copied. Paste it into Jaeger Chat to begin.");}catch{toast("Clipboard unavailable. Export the brief instead.","error");}}}>Copy prompt for Jaeger</button><button className="jg-u-btn" onClick={()=>onNavigate("/")}>Open chat</button></div>
        </section>
      </div>
      <footer className="jg-production__toolbar" aria-label="Production resources"><button className="jg-u-btn" onClick={()=>onNavigate("/studio")}>Create visuals</button><button className="jg-u-btn" onClick={()=>onNavigate("/library?section=media")}>Find outputs</button><button className="jg-u-btn" onClick={()=>onNavigate("/work/tasks")}>Track tasks</button><button className="jg-u-btn" onClick={()=>onNavigate("/library?section=knowledge")}>Browse skills</button></footer>
      <p className="jg-u-note">Export shares this brief and your notes, not an executable tool. Check the contents for private information before sharing. Generation and publishing run through Jaeger Chat and its connected tools.</p>
    </>}
  </div>;
}
