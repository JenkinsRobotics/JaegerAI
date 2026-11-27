import { ActivityHistory } from "./ActivityHistory";
import { PasswordVault } from "./PasswordVault";
import { useState, type ReactNode } from "react";
import { Settings, Bell, Download, CircleUserRound, Sun, Archive, Shield, Contact, Mic, Folder,
  Terminal, SlidersHorizontal, PawPrint, Keyboard, CreditCard, Gauge, Puzzle, KeyRound,
  MousePointer2, History, Scan, PanelTop, Monitor, Box, Cpu, Cable, Search, ListFilter,
  Anchor, Cloud, CloudRain, GitBranch, GitPullRequest, Split, ArrowUpRight, ChevronDown } from "lucide-react";
import { BrowserSettings } from "./BrowserSettings";
import { GeneralSettings, NotificationSettings, ImportSettings } from "./PersonalSettings";
import { AppearanceSettings, VoiceSettings, ConfigurationSettings, PersonalizationSettings } from "./PreferencePages";
import "./settings.css";

const personal = [
  ["General", Settings, "permissions access folder language menu bar close sleep archive compress shortcut follow-up queue steer popout notifications sound toys confetti audio governor resources emergency stop idle life Minecraft"],
  ["Notifications", Bell, "push email tasks dots groups health library marketing tips projects responses usage"], ["Import", Download, "sync Claude Cursor Gmail plugins history"], ["Profile", CircleUserRound, "identity owner name counterpart"],
  ["Appearance", Sun, "theme light dark"], ["Account", CircleUserRound, ""], ["Archived chats", Archive, ""],
  ["Parental controls", Shield, ""], ["Trusted contact", Contact, ""], ["Voice", Mic, ""], ["Storage", Folder, ""],
  ["Configuration", Terminal, ""], ["Personalization", SlidersHorizontal, ""], ["Mini & Pets", PawPrint, ""],
  ["Keyboard shortcuts", Keyboard, ""], ["Billing", CreditCard, ""], ["Usage", Gauge, ""], ["Data controls", Shield, ""],
] as const;
const integrations = [
  ["Plugins", Puzzle, ""], ["Passwords", KeyRound, ""], ["Computer use", MousePointer2, ""],
  ["Computer history", History, ""], ["Appshots", Scan, ""], ["Browser", PanelTop, "general import web local URL link destination code review browsing data cache annotation screenshots solve CAPTCHAs autofill passwords contact info addresses phone email extensions downloads history permissions website developer CDP camera microphone WebMCP"],
  ["Cloud computer", Monitor, ""],
] as const;
const coding = [
  ["Hooks", Anchor, ""], ["Connections", Cable, "MCP tools servers plugins"],
  ["Codex Cloud", Cloud, ""], ["Legacy Codex Cloud", CloudRain, ""],
  ["Code Review", GitPullRequest, ""], ["Git", GitBranch, ""], ["Worktrees", Split, ""],
] as const;
const jaeger = [
  ["Avatar", Box, "VRM GLB portrait voice viseme"], ["Models", Cpu, "provider local cloud inference"],
] as const;
const groups = [{name:"Personal", items:personal}, {name:"Integrations", items:integrations}, {name:"Coding", items:coding}, {name:"Jaeger", items:jaeger}];

export function SettingsWorkspace({ panels, baseUrl, sessionId }: { baseUrl:string; sessionId:string; panels: Record<string, ReactNode> }) {
  const [selected, setSelected] = useState("Browser");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("All");
  const [filterOpen, setFilterOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const matches = groups.filter(g => filter === "All" || filter === g.name).map(g => ({
    name:g.name, items:g.items.filter(([name,,terms]) => (name+" "+terms).toLowerCase().includes(query.trim().toLowerCase())),
  })).filter(g => g.items.length);
  const active = matches.some(g => g.items.some(([name]) => name === selected)) ? selected : matches[0]?.items[0]?.[0];
  const pages: Record<string,ReactNode> = {
    Passwords: <div className="jg-browser-settings"><header className="jg-browser-intro"><h1>Passwords</h1></header><PasswordVault/></div>,
    Browser: <BrowserSettings baseUrl={baseUrl} sessionId={sessionId}/>, General: <GeneralSettings>{panels.General}</GeneralSettings>,
    Notifications: <NotificationSettings baseUrl={baseUrl}/>, Import: <ImportSettings/>,
    Appearance: <AppearanceSettings>{panels.Appearance}</AppearanceSettings>, Voice: <VoiceSettings/>,
    Configuration: <ConfigurationSettings baseUrl={baseUrl}/>, Personalization: <PersonalizationSettings baseUrl={baseUrl}/>,
    "Computer history": <ActivityHistory/>,
  };
  return <div className="jg-settings">
    <nav className="jg-settings-nav" aria-label="Settings categories" data-expanded={navOpen}>
      <div className="jg-settings-nav-title"><h1>Settings</h1>
        <button className="jg-category-toggle" onClick={() => setNavOpen(!navOpen)} aria-expanded={navOpen}>{active || "Categories"} <ChevronDown size={14}/></button>
        <button className="jg-filter-button" aria-label="Filter settings categories" aria-expanded={filterOpen} onClick={() => setFilterOpen(!filterOpen)}><ListFilter size={17}/></button>
      </div>
      {filterOpen && <select aria-label="Category group" value={filter} onChange={e=>setFilter(e.target.value)}>{["All",...groups.map(g=>g.name)].map(g=><option key={g}>{g}</option>)}</select>}
      <label className="jg-settings-search"><Search size={16}/><input type="search" aria-label="Search settings" placeholder="Search" value={query} onChange={e=>{setQuery(e.target.value);setNavOpen(true);}}/></label>
      <div className="jg-settings-groups">{matches.map(g=><div key={g.name}><h2>{g.name}</h2>{g.items.map(([name,Icon])=>
        <button type="button" key={name} aria-current={active===name?"page":undefined} onClick={()=>{setSelected(name);setNavOpen(false);}}>
          <Icon size={16} strokeWidth={1.65}/>{name}{(name==="Billing" || name==="Profile") && <ArrowUpRight size={13} className="jg-category-arrow"/>}
        </button>)}</div>)}</div>
    </nav>
    <section className="jg-settings-detail" aria-label={active ?? "Search results"} key={active}>
      {active ? pages[active] ?? <><h2>{active}</h2>{panels[active] ?? <p className="jg-muted">Jaeger integration pending.</p>}</> : <p role="status">No settings match “{query}”.</p>}
    </section>
  </div>;
}
