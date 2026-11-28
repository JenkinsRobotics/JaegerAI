import { EmailDelivery } from "./EmailDelivery";
import { useSetting } from "./userPreferences";
import { useState, type ReactNode } from "react";
import { CircleAlert, CodeXml, Mail, Navigation, Pencil } from "lucide-react";
import { Row, Switch } from "./BrowserSettings";

export function Card({title, description, children}: {title: string; description?: ReactNode; children: ReactNode}) {
  return <section><h2>{title}</h2>{description && <p>{description}</p>}<div className="jg-browser-card">{children}</div></section>;
}
export function Toggle({title, description, initial = false}: {title: string; description: ReactNode; initial?: boolean}) {
  const [on, setOn] = useState(initial);
  return <Row title={title} description={description}><Switch name={title} value={on} onChange={() => setOn(!on)}/></Row>;
}
export function Menu({title, description, options, initial}: {title: string; description: ReactNode; options: string[]; initial?: string}) {
  return <Row title={title} description={description}><select aria-label={title} defaultValue={initial ?? options[0]}>{options.map(option => <option key={option}>{option}</option>)}</select></Row>;
}
export function Editable({title, description, initial, hotkey = false}: {title: string; description: string; initial: string; hotkey?: boolean}) {
  const [value, setValue] = useState(initial);
  const [draft, setDraft] = useState<string | null>(null);
  return <Row title={title} description={description}>{draft === null
    ? <div className="jg-personal-actions"><span>{value || "Off"}</span><button aria-label={"Edit " + title} onClick={() => setDraft(value)}>{hotkey ? <Pencil size={15}/> : "Change"}</button></div>
    : <form className="jg-personal-actions" onSubmit={e => {e.preventDefault(); setValue(draft.trim()); setDraft(null);}}>
      <input autoFocus required={!hotkey} aria-label={title} value={draft} onChange={e => setDraft(e.target.value)}/>
      <button>Save</button><button type="button" onClick={() => setDraft(null)}>Cancel</button></form>}</Row>;
}

export function GeneralSettings({children}: {children: ReactNode}) {
  const [context,setContext]=useSetting("contextUsage"), [shortcut,setShortcut]=useSetting("sendShortcut"), [awake,setAwake]=useSetting("keepAwake");
  const [completion,setCompletion]=useSetting("completionAlerts"), [approval,setApproval]=useSetting("approvalAlerts"), [sound,setSound]=useSetting("sound");
  const [permission,setPermission]=useState(() => typeof Notification === "undefined" ? "unavailable" : Notification.permission);
  const levels = ["Low","Medium","High","Extra high","Maximum"];
  const [efforts,setEfforts] = useState(levels);
  const [effortsOpen,setEffortsOpen] = useState(false);
  const [risk, setRisk] = useState(false);
  const [follow, setFollow] = useState("Steer");
  return <div className="jg-browser-settings">
    <header className="jg-browser-intro"><h1>General</h1></header>
    <Card title="Permissions">
      <Toggle title="Default permissions" initial description="By default, Jaeger can read and edit files in its workspace. It can ask for additional access when needed."/>
      <Toggle title="Full access" initial description={<>When Jaeger runs with full access, it can edit files on your computer and run commands with network access without asking for approval. This increases the risk of data loss, leaks, or unexpected behavior. <button className="jg-browser-inline-link" aria-expanded={risk} onClick={() => setRisk(!risk)}>Learn more</button> about elevated risks.{risk && <><br/>These preview switches do not change Gateway permissions.</>}</>}/>
    </Card>
    <Card title="General">
      <Editable title="Projectless chat folder" description="The location where chats started outside of projects store their data by default." initial="~/Documents/Jaeger"/>
      <Menu title="Default file open destination" description="Where files and folders open by default" options={["VS Code","System default"]}/>
      <Menu title="Language" description="Language for the app UI" options={["Auto detect","English","Español","Français"]}/>
      <Toggle title="Show in menu bar" initial description="Keep Jaeger in the macOS menu bar when the main window is closed"/>
      <Menu title="Confirm before closing a window" description="Warn when a tab-close shortcut would close the window" options={["Close shortcut only","Always","Never"]}/>
      <Toggle title="Full view by default" description="Open content tabs in full view in new chats"/>
      <Row title="Prevent sleep while running" description="Keep this screen awake during a run while Jaeger is visible, on supported devices"><Switch name="Prevent sleep while running" value={awake==="on"} onChange={()=>setAwake(awake==="on"?"off":"on")}/></Row>
      <Menu title="Automatically archive inactive chats" description="Archive local chats after a period of inactivity" options={["Never","After 30 days","After 90 days"]}/>
      <Toggle title="Compress local chat history" initial description="Save disk space by compressing older local chat history. Restart Jaeger to apply changes."/>
      <Menu title="Speed" description="Choose how quickly Jaeger runs across chats, subagents, and compaction" options={["Fast","Standard"]}/>
      <Row title="Available reasoning efforts" description="Choose which reasoning effort levels appear in model controls. Availability varies by model."><button aria-expanded={effortsOpen} onClick={()=>setEffortsOpen(!effortsOpen)}>{efforts.length} selected ⌄</button></Row>
      {effortsOpen && <fieldset><legend>Available reasoning efforts</legend>{levels.map(level=><label key={level}><input type="checkbox" checked={efforts.includes(level)} onChange={e=>setEfforts(e.target.checked ? [...efforts,level] : efforts.filter(l=>l!==level))}/>{level} </label>)}</fieldset>}
      <Row title="Open source licenses" description="Third-party notices for bundled dependencies"><a href="https://github.com/JenkinsRobotics/JaegerAI/blob/master/THIRD_PARTY_NOTICES.md" target="_blank" rel="noreferrer">View</a></Row>
      <Toggle title="Plugins" initial description="Allow Jaeger to use installed plugins"/>
    </Card>
    <Card title="Composer">
      <Toggle title="Show predictions" initial description="Predict your next message based on the conversation"/>
      <Toggle title="Plain text composer" description="Keep code, Markdown, and links as literal text while writing messages"/>
      <Row title="Show context window usage" description="Display estimated usage above the chat composer"><Switch name="Show context window usage" value={context==="on"} onChange={()=>setContext(context==="on"?"off":"on")}/></Row>
      <Row title="Send shortcut" description="Shift+Enter always inserts a new line"><select aria-label="Send shortcut" value={shortcut} onChange={e=>setShortcut(e.target.value)}><option>Enter</option><option>⌘ / Ctrl + Enter</option></select></Row>
      <Row title="Follow-up behavior" description="Queue follow-ups while Jaeger runs or steer the current run. Press ⌘↩ to do the opposite for one message.">
        <div className="jg-personal-actions">{["Queue","Steer"].map(mode => <button key={mode} aria-pressed={follow === mode} onClick={() => setFollow(mode)}>{mode}</button>)}</div>
      </Row>
    </Card>
    <Card title="Popout Window">
      <Editable title="Popout Window hotkey" description="Set a global shortcut for Popout Window. Leave unset to keep it off." initial="" hotkey/>
      <Toggle title="Default to standalone chat" description="Start new chats outside of any project"/>
    </Card>
    <Card title="Notifications">
      <Row title="Desktop alerts" description="Deliver notifications from this WebUI while it is open."><button disabled={permission !== "default"} onClick={async()=>{try{setPermission(await Notification.requestPermission());}catch{setPermission("unavailable");}}}>{permission==="default"?"Enable desktop alerts":permission}</button></Row>
      <Row title="Turn completion notifications" description="When to alert you that Jaeger has finished"><select aria-label="Turn completion notifications" value={completion} onChange={e=>setCompletion(e.target.value)}>{["Only when unfocused","Always","Never"].map(v=><option key={v}>{v}</option>)}</select></Row>
      <Row title="Enable permission notifications" description="Show alerts when Jaeger requests approval"><Switch name="Enable permission notifications" value={approval==="on"} onChange={()=>setApproval(approval==="on"?"off":"on")}/></Row>
      <Toggle title="Enable question notifications" initial description="Show alerts when a thread asks a question"/>
      <Toggle title="Enable dot notifications" initial description="Show alerts when a dot messages you or needs your input"/>
      <Row title="Notification sound" description="Sound for desktop alerts"><select aria-label="Notification sound" value={sound} onChange={e=>setSound(e.target.value)}><option>Default</option><option>Silent</option></select></Row>
    </Card>
    <Card title="Toys">
      <Toggle title="Confetti cannon" description="Show confetti in the app when you ask!"/>
      <Toggle title="Audio visualizer" description="Animate conversation rails with system audio processed on your device."/>
    </Card>
    <small>Desktop alert, composer shortcut, context usage, and screen wake preferences are saved on this device. Other controls above are previews.</small>
    {children && <section><h2>Jaeger runtime</h2>{children}</section>}
  </div>;
}

const channels = [
  ["Codex","Get notified about Codex tasks.","Push"],
  ["dots","Get notified about updates from your dots.","Push"],
  ["Group chats","Receive notifications for new messages from group chats.","Push"],
  ["Health","Get notified when your health data is ready.","Push"],
  ["Library","Get notified about shared files, folders, and access requests in your Library.","Email"],
  ["Marketing","Stay in the loop on new tools and features from Jaeger.","Push, Email"],
  ["Personalized tips","Get recommendations based on your conversations with Jaeger.","Push, Email"],
  ["Projects","Get notified when you receive an email invitation to a shared project.","Email"],
  
  
  ["Usage","Get notified when limits reset for features like image creation.","Push, Email"],
];
export function NotificationSettings({baseUrl}:{baseUrl:string}) {
  return <div className="jg-browser-settings"><header className="jg-browser-intro"><h1>Notifications</h1></header>
    <EmailDelivery baseUrl={baseUrl}/>
    <Card title="Jaeger">{channels.map(([title, description, initial]) => <Menu key={title} title={title} initial={initial}
      description={<>{description}{title === "Tasks" && <><br/><a href="/tasks">Manage tasks</a></>}</>} options={["Push","Email","Push, Email","Off"]}/>)}</Card>
    <small>Email delivery uses the Gateway. Category menus above are previews.</small>
  </div>;
}

const categories = ["Settings","Projects","Chats","Plugins","Skills","Instructions"];
export function ImportSettings() {
  const [customize, setCustomize] = useState(false);
  const [selected, setSelected] = useState(categories);
  const [action, setAction] = useState("");
  return <div className="jg-browser-settings"><header className="jg-browser-intro"><h1>Import</h1><p>Bring setup, projects, and chats from other AI apps into Jaeger</p></header>
    <Card title="Automatic sync">
      <Toggle title="Keep imports in sync" description="Automatically sync new and updated content from connected sources" initial/>
      <Row title="Content to sync" description={selected.length + " categories selected"}><button aria-expanded={customize} onClick={() => setCustomize(!customize)}>Customize</button></Row>
      {customize && <fieldset><legend>Content to sync</legend>{categories.map(c => <label key={c}><input type="checkbox" checked={selected.includes(c)} onChange={e => setSelected(e.target.checked ? [...selected,c] : selected.filter(item => item !== c))}/>{c} </label>)}</fieldset>}
    </Card>
    <Card title="Import from another AI app" description="Example setup that can be added to Jaeger">
      {["Claude Code","Cursor"].map((source,i) => <div className="jg-browser-row" key={source}><strong className="jg-personal-actions">{i ? <Navigation/> : <CodeXml/>}{source}</strong><button aria-label={"Import from " + source} onClick={() => setAction(source)}>Import</button></div>)}
      <div className="jg-browser-row"><div className="jg-personal-actions"><CircleAlert size={16}/><div><strong>2 projects can’t be imported</strong><p>Sample Project A and Sample Project B use an unsupported project configuration</p></div></div></div>
    </Card>
    <Card title="Needs attention" description="Finish setting up items from a previous import">
      <h3>Plugins (1)</h3><div className="jg-browser-row"><div className="jg-personal-actions"><Mail/><div><strong>Gmail</strong><p>Find and reference emails from your inbox</p></div></div><button aria-label="Install Gmail" onClick={() => setAction("Gmail")}>Install</button></div>
    </Card>
    <Card title="Import history"><details open><summary><CodeXml size={18}/> Imported from Claude Code</summary><p>Nov 26, 2026, 10:59 AM · 0 imported</p><p>No results recorded</p></details></Card>
    <small>Import preview · Sources, projects, plugins, and history are examples.</small>
    {action && <dialog open className="jg-browser-dialog" aria-label={action}><h3>{action}</h3><p>{action === "Gmail" ? "Plugin installation" : "Import from " + action} will be available when the integration is connected.</p><button className="jg-btn" onClick={() => setAction("")}>Close</button></dialog>}
  </div>;
}
