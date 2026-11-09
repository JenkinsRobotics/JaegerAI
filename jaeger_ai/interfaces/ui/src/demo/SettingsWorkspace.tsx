import { useEffect, useRef, useState } from "react";
import { Settings, FolderInput, User, Sun, Mic, Terminal, Sparkles, Bot, Command, TrendingUp, BarChart, Shield, Compass, Clock, Image, Puzzle, Globe, Workflow, Link, Github, Code, FolderOpen, MessageSquare, ChevronLeft, Search } from "../components/Icons";
import { AudioSettingsPanel } from "../settings/AudioSettingsPanel";
import "./settingsWorkspace.css";

const groups = [
  { title: "Personal", items: [["General", Settings], ["Import", FolderInput], ["Profile", User], ["Appearance", Sun], ["Voice", Mic], ["Configuration", Terminal], ["Personalization", Sparkles], ["Pets", Bot], ["Keyboard shortcuts", Command], ["Usage & billing", TrendingUp], ["Analytics", BarChart], ["Account", Shield]] },
  { title: "Integrations", items: [["Computer use", Compass], ["Computer history", Clock], ["Appshots", Image], ["Plugins", Puzzle], ["Browser", Globe]] },
  { title: "Coding", items: [["Hooks", Workflow], ["Connections", Link], ["Git", Github], ["Environments", Terminal], ["Worktrees", Code]] },
  { title: "Archived", items: [["Archived chats", MessageSquare]] },
] as const;

/** Settings navigation. Implemented sections mount their canonical controls. */
export function SettingsWorkspace({ onClose }: { onClose: () => void }) {
  const [selected, setSelected] = useState<string>("General");
  const [query, setQuery] = useState("");
  const back = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    back.current?.focus();
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("keydown", escape); previous?.focus(); };
  }, [onClose]);
  return <div className="jg-settings-workspace">
    <aside aria-label="Settings navigation">
      <button ref={back} className="jg-settings-workspace__back" onClick={onClose}><ChevronLeft size={20} />Back to app</button>
      <label className="jg-settings-workspace__search"><Search size={18} /><input aria-label="Search settings" placeholder="Search settings…" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <nav aria-label="Settings categories">
        {groups.map(group => {
          const items = group.items.filter(([name]) => name.toLowerCase().includes(query.trim().toLowerCase()));
          return items.length > 0 && <section key={group.title}><h2>{group.title}</h2>{items.map(([name, Icon]) => <button key={name} aria-current={selected === name ? "page" : undefined} onClick={() => setSelected(name)}><Icon size={20} /><span>{name}</span></button>)}</section>;
        })}
        {!groups.some(group => group.items.some(([name]) => name.toLowerCase().includes(query.trim().toLowerCase()))) && <p role="status">No matching settings.</p>}
      </nav>
      <a href="/settings/appearance"><FolderOpen size={18} />Existing Jaeger settings</a>
    </aside>
    <main aria-labelledby="jaeger-settings-title"><header><h1 id="jaeger-settings-title">{selected}</h1>{selected!=="Voice"&&<span>Draft</span>}</header>{selected==="Voice"?<AudioSettingsPanel/>:<p>Settings for this section will be added here.</p>}</main>
  </div>;
}
