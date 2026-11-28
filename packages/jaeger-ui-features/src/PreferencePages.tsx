import { useSetting } from "./userPreferences";
import { GatewayDetails, VoiceDeviceSettings } from "./ConnectedSettings";
import { useState, type ReactNode } from "react";
import { Copy, Download } from "lucide-react";
import { Card, Menu, Toggle, Editable } from "./PersonalSettings";
import { Row, Switch } from "./BrowserSettings";

function Page({name, subtitle, children}: {name:string; subtitle?:string; children:ReactNode}) {
  return <div className="jg-browser-settings"><header className="jg-browser-intro"><h1>{name}</h1>{subtitle && <p>{subtitle}</p>}</header>{children}<small>{name==="Appearance" ? "Appearance is saved on this device." : name==="Voice" ? "Microphone, spoken reply language, and voice apply to Droid. Other controls are previews." : "Preview controls do not change runtime policy."}</small></div>;
}
function Action({title, description, label, content}: {title:string; description?:ReactNode; label:string; content?:ReactNode}) {
  const [open,setOpen] = useState(false);
  return <><Row title={title} description={description}><button aria-label={title + " · " + label} onClick={()=>setOpen(true)}>{label}</button></Row>
    {open && <dialog open aria-label={title} className="jg-browser-dialog" onKeyDown={e=>{if(e.key==="Escape")setOpen(false);}}><h3>{title}</h3>{content ?? <p>This preview is ready for the Jaeger integration.</p>}<button autoFocus className="jg-btn" onClick={()=>setOpen(false)}>Close</button></dialog>}</>;
}
function Learn({text}: {text:string}) {
  const [open,setOpen]=useState(false);
  return <> <button className="jg-browser-inline-link" aria-expanded={open} onClick={()=>setOpen(!open)}>Learn more</button>{open && <span> {text}</span>}</>;
}
export function AppearanceSettings({children}: {children:ReactNode}) {
  const [mode,setMode]=useSetting("mode");
  const [bg,setBg]=useSetting("background"), [fg,setFg]=useSetting("foreground");
  const colors=[bg || (getComputedStyle(document.documentElement).getPropertyValue("--jg-bg").trim() || "#181818"),fg || (getComputedStyle(document.documentElement).getPropertyValue("--jg-text-primary").trim() || "#ffffff")];
  const [accent,setAccent]=useSetting("accent"), [font,setFont]=useSetting("font");
  const [status,setStatus]=useState("");
  const json=JSON.stringify({mode,theme:"Jaeger",accent,background:colors[0],foreground:colors[1],font},null,2);
  return <Page name="Appearance"><Card title="Visual style"><Row title="Mode" description=""><div className="jg-mode-options">{["System","Light","Dark"].map(m=><button key={m} title={m} aria-label={m+" mode"} aria-pressed={mode===m} data-mode={m} onClick={()=>setMode(m)}><span/><i/><i/><i/></button>)}</div></Row></Card>
    <section className="jg-browser-card"><Row title="Theme" description=""><div className="jg-personal-actions">
      <a aria-label="Download theme" download="jaeger-theme.json" href={"data:application/json;charset=utf-8,"+encodeURIComponent(json)}><Download size={16}/></a>
      <button aria-label="Copy theme" onClick={async()=>{try{await navigator.clipboard.writeText(json);setStatus("Theme copied");}catch{setStatus("Clipboard unavailable");}}}><Copy size={16}/></button>
      <select aria-label="Theme"><option>Jaeger</option></select></div></Row>
      <Row title="Accent" description=""><select aria-label="Accent" value={accent} onChange={e=>setAccent(e.target.value)}>{["Theme default","White","Blue","Green"].map(c=><option key={c}>{c}</option>)}</select></Row>
      {["Background","Foreground"].map((label,i)=><Row key={label} title={label} description=""><label className="jg-color-chip"><input type="color" aria-label={label} value={colors[i]} onChange={e=>(i===0 ? setBg : setFg)(e.target.value)}/>{colors[i].toUpperCase()}</label></Row>)}
      <Row title="Font" description=""><select aria-label="Font" value={font} onChange={e=>setFont(e.target.value)}>{["System","Serif","Monospace"].map(f=><option key={f}>{f}</option>)}</select></Row></section>
    {status && <p role="status">{status}</p>}<section><details><summary>Advanced</summary>{children}<button className="jg-btn" onClick={()=>{setMode("System");setBg("");setFg("");setAccent("Theme default");setFont("System");}}>Restore theme defaults</button></details></section></Page>;
}
export function VoiceSettings() {
  const [language,setLanguage]=useSetting("speechLanguage");
  return <Page name="Voice"><Card title="General"><VoiceDeviceSettings kind="microphone"/><Row title="Language" description="Language for spoken replies"><select aria-label="Voice language" value={language} onChange={e=>setLanguage(e.target.value)}><option value="">System default</option><option value="en-US">English</option><option value="es-ES">Español</option><option value="fr-FR">Français</option></select></Row></Card>
    <Card title="Voice chat"><VoiceDeviceSettings kind="voice"/>
      <Editable title="Voice chat hotkey" description="Start voice chat from anywhere on desktop" initial="" hotkey/>
      <Toggle title="Screen context" initial description="Let Jaeger inspect the foreground app when you refer to what’s on screen. macOS asks for access the first time it’s needed."/></Card>
    <Card title="Dictation"><Toggle title="Always show live transcription" description=""/></Card>
    <div className="jg-browser-card"><Editable title="Dictation shortcut" description="Hold to dictate, or double-tap for hands-free" initial="" hotkey/><details><summary>Advanced</summary><p>Hold the shortcut for one message or double-tap for continuous dictation.</p></details></div>
    <div className="jg-browser-card"><Row title="Recent recordings" description="Your last 20 recordings appear here when device storage is connected.">{null}</Row></div>
    <section className="jg-browser-card"><Action title="Voice dictionary" description="Words or phrases dictation should recognize" label="Manage" content={<textarea aria-label="Voice dictionary phrases" placeholder="One phrase per line"/>}/></section></Page>;
}
export function ConfigurationSettings({baseUrl}: {baseUrl:string}) {
  const [config,setConfig]=useState(false);
  return <Page name="Configuration" subtitle="Choose how Jaeger works on your tasks"><section><div className="jg-browser-heading jg-browser-general-heading"><select aria-label="Configuration profile"><option>Codex</option></select><button onClick={()=>setConfig(!config)}>Open config.toml ↗</button></div>
    {config && <p>Local configuration file access is pending integration.</p>}
    <div className="jg-browser-card"><Menu title="Approval policy" description="Choose when Jaeger asks for approval" options={["On request","Always ask"]}/>
    <Menu title="Sandbox settings" description="Choose how much Jaeger can do when running commands" options={["Workspace write","Read only"]}/>
    <Toggle title="Allow network access" description="Allow network access when the sandbox is set to workspace write"/>
    <Menu title="Web search" description="Choose how Jaeger accesses the web" options={["Cached","Live","Off"]}/>
    <Menu title="Output detail" description="Choose how much detail Jaeger includes in responses" options={["Model default","Low","Medium","High"]}/>
    <Menu title="Reasoning summary" description="Choose how Jaeger summarizes its reasoning" options={["Auto","Concise","Detailed"]}/></div></section>
    <Card title="Workspace Dependencies"><Toggle title="Codex dependencies" initial description="Allow Jaeger to install and expose bundled Node.js and Python tools"/>
    <Action title="Diagnose issues in Codex Workspace" description="Read current Gateway status and session diagnostics" label="Diagnose" content={<GatewayDetails kind="diagnostics" baseUrl={baseUrl}/>}/>
    <Action title="Reset and install Workspace" description="Downloads a fresh bundle, installs it, and reloads tools" label="↓ Reinstall"/></Card>
    <small>Current version · Awaiting workspace connection</small></Page>;
}
export function PersonalizationSettings({baseUrl}: {baseUrl:string}) {
  const [voice,setVoice]=useSetting("voiceEnabled");
  return <Page name="Personalization"><Card title="Jaeger memory" description={<>Configure how Jaeger manages memory.<Learn text="Memory makes selected context available across chats."/></>}>
    <Toggle title="Enable memory" initial description={<>Personalize your experience based on your chats, files, and connected apps.<Learn text="Memory preferences apply when the Gateway integration is connected."/></>}/>
    <Action title="Memory summary" description={<>View what Jaeger has learned about you. Use <a href="#jg-instructions">custom instructions</a> for details to keep in mind, or manage your saved memories.</>} label="Manage" content={<GatewayDetails kind="memory" baseUrl={baseUrl}/>}/>
    <p>Memory may personalize queries to search providers.<Learn text="A search query can include relevant context from your chats."/></p></Card>
    <section><div className="jg-browser-heading"><h2>Codex memory</h2><select aria-label="Memory location"><option>Local</option></select></div><p>Configure how Codex manages memory for Local.<Learn text="These options apply to the selected machine."/></p><div className="jg-browser-card">
    <Toggle title="Enable Codex memories" initial description="Create memories from local chats and use them to personalize future local chats"/>
    <Toggle title="Allow memories from tool-assisted chats" initial description="Generate memories from chats that used MCP tools or web search"/>
    <Action title="Delete Codex memories" description="Delete all Codex memories for Local" label="Delete"/></div></section>
    <Card title="Permissions"><Action title="Custom rules" description="Choose which actions Jaeger can take without asking and which require approval" label="1 ›"/></Card>
    <Card title="Writing"><Toggle title="Reference my writing style" description="Use your chats, Library files, and connected apps to write in your style"/></Card>
    <Card title="Reference photos">{[["Reference photo","Use this photo when creating an image of yourself"],["Full-body reference photo","Show how clothing and accessories look on you"]].map(([title,desc])=><Action key={title} title={title} description={desc} label="Add ›" content={<input type="file" accept="image/*" aria-label={title}/>}/>)}</Card>
    <section className="jg-browser-card"><Menu title="Base style and tone" description="" options={["Efficient","Default","Friendly"]}/>{["Warmth","Enthusiasm","Emoji","Visual answers","Headers and lists"].map(t=><Menu key={t} title={t} description="" options={["Default","More","Less"]}/>)}</section>
    <section id="jg-instructions"><h2>Custom instructions</h2><div className="jg-browser-card">{[["Jaeger","Give Jaeger extra instructions and context for all chats."],["Codex","Applies to Codex Cloud chats on desktop and web."],["AGENTS.md","Edit instructions on the selected machine. Repository instructions may also apply."]].map(([t,d])=><Action key={t} title={t} description={<>{d}{t!=="Codex" && <Learn text="Use instructions for preferences that should apply across tasks."/>}</>} label="›" content={<textarea aria-label={t+" instructions"}/>}/>)}</div></section>
    <Card title="Additional Jaeger settings">{[["Fast answers","Use general knowledge for quick answers without personalized memory."],["Suggested prompts","Suggest prompts using accessible chats, Pages, files, and connected apps."],["Reference record history","Reference previous recording transcripts and notes when responding."],["Web search","Automatically search the web for answers"],["Jaeger Voice","Enable Voice in Jaeger"],["Space search","Automatically search Space files for answers"],["Connector search","Automatically search connected sources for answers"]].map(([t,d])=>t==="Jaeger Voice" ? <Row key={t} title={t} description="Enable voice sessions in Droid"><Switch name={t} value={voice==="on"} onChange={()=>setVoice(voice==="on"?"off":"on")}/></Row> : <Toggle key={t} title={t} initial description={<>{d}{t==="Reference record history" && <Learn text="Recording history provides context from earlier sessions."/>}</>}/>)}</Card></Page>;
}
