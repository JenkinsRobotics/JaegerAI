import { PasswordVault } from "./PasswordVault";
import { useId, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, MousePointer2, PanelTop, Plus, ShieldAlert } from "lucide-react";

const choices = ["Always allow", "Always ask", "Block"] as const;
type Permission = typeof choices[number];
const columns = ["Browsing", "Downloads", "Site tools", "Camera", "Microphone"] as const;
type Column = typeof columns[number];
type Rule = { site: string; permissions: Record<Column, Permission> };
const defaults: Rule = {site:"Default", permissions:{Browsing:"Always allow",Downloads:"Always allow","Site tools":"Always allow",Camera:"Always ask",Microphone:"Always ask"}};

function Choice({name,value,onChange}:{name:string;value:Permission;onChange:(p:Permission)=>void}) {
  return <select aria-label={name} value={value} onChange={e=>onChange(e.target.value as Permission)}>{choices.map(p=><option key={p}>{p}</option>)}</select>;
}
export function Switch({name,value,onChange}:{name:string;value:boolean;onChange:()=>void}) {
  return <button type="button" className="jg-browser-switch" role="switch" aria-label={name} aria-checked={value} onClick={onChange}><span/></button>;
}
export function Row({title,description,children}:{title:string;description:ReactNode;children:ReactNode}) {
  return <div className="jg-browser-row"><div><strong>{title}</strong><p>{description}</p></div>{children}</div>;
}

type SessionBrowserProps = { baseUrl: string; sessionId: string };
function BrowserGeneral({show,baseUrl,sessionId}: SessionBrowserProps & {show: (name: string) => void}) {
  const [action,setAction] = useState<"grant"|"stop"|null>(null);
  const [url,setUrl] = useState("");
  const [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState("");
  async function applyBrowserAction() {
    if (!sessionId || !action || busy) return;
    setBusy(true);
    try {
      const response = await fetch(baseUrl+"/v1/sessions/"+encodeURIComponent(sessionId)+"/browser/"+action, {
        method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(action==="grant"?{url}:{})
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Browser request failed");
      setNotice(action==="grant" ? "Gateway granted access to "+url : "Browser access stopped for this conversation.");
      setAction(null);
    } catch(error) {setNotice(error instanceof Error ? error.message : "Browser request failed");}
    finally {setBusy(false);}
  }
  const [fullUrl, setFullUrl] = useState(false);
  const [solveCaptchas, setSolveCaptchas] = useState(false);
  const destinations = ["Jaeger", "System browser"];
  return <>
    <header className="jg-browser-intro">
      <h1>Browser</h1><p>Manage your Browser Use preferences and site access.</p>
    </header>
    <section className="jg-browser-card jg-browser-master">
      <span className="jg-browser-symbol" aria-hidden="true"><PanelTop/><MousePointer2/></span>
      <Row title="Browser" description="Grant this conversation access to a specific URL.">
        <div className="jg-personal-actions"><button disabled={!sessionId || busy} onClick={()=>{setAction("grant");setNotice("");}}>Grant access</button><button disabled={!sessionId || busy} onClick={()=>{setAction("stop");setNotice("");}}>Stop access</button></div>
      </Row>
    </section>
    {action && <form className="jg-browser-card" onSubmit={e=>{e.preventDefault();void applyBrowserAction();}}>
      <p>{action==="grant" ? "Choose the exact URL Jaeger may open in a supervised tab." : "Stop browser access for this conversation and close its supervised tabs. Further grants require a new conversation."}</p>
      {action==="grant" && <input type="url" aria-label="Approved URL" required autoFocus value={url} onChange={e=>setUrl(e.target.value)}/>}
      <button disabled={busy} className="jg-btn">{action==="grant"?"Grant this URL":"Stop for this conversation"}</button>
      <button disabled={busy} type="button" className="jg-btn" onClick={()=>setAction(null)}>Cancel</button>
    </form>}
    {notice && <p role="status">{notice}</p>}

    <section>
      <div className="jg-browser-heading jg-browser-general-heading"><h2>General</h2>
        <button type="button" onClick={()=>show("Import browser data")}>Import…</button>
      </div>
      <div className="jg-browser-card">
        <Row title="Web URL and link open destination" description={<>Manage pull request links in <button type="button" className="jg-browser-inline-link" onClick={()=>show("Code Review settings")}>Code Review settings</button></>}>
          <select aria-label="Web URL and link open destination">{destinations.map(d=><option key={d}>{d}</option>)}</select>
        </Row>
        <Row title="Local URL open destination" description="Where local development sites open by default">
          <select aria-label="Local URL open destination">{destinations.map(d=><option key={d}>{d}</option>)}</select>
        </Row>
        <Row title="Show full URL" description="Include the path, query, and fragment in the address bar">
          <Switch name="Show full URL" value={fullUrl} onChange={()=>setFullUrl(!fullUrl)}/>
        </Row>
        <Row title="Browsing data" description="Clear browsing history, site data, cache, and download history from the in-app browser">
          <button type="button" onClick={()=>show("Clear browsing data")}>Clear browsing data</button>
        </Row>
        <Row title="Browsing history" description="View and manage pages visited in the built-in browser">
          <button type="button" aria-label="Manage browsing history" onClick={()=>show("Browsing history")}>Manage</button>
        </Row>
        <Row title="Annotation screenshots" description="Screenshots help Jaeger better understand and address comments, but increase plan usage">
          <select aria-label="Annotation screenshots"><option>Always include</option><option>Always ask</option><option>Never include</option></select>
        </Row>
        <Row title="Solve CAPTCHAs" description="Allow Jaeger to solve future CAPTCHAs across websites for your tasks without asking each time">
          <Switch name="Solve CAPTCHAs" value={solveCaptchas} onChange={()=>setSolveCaptchas(!solveCaptchas)}/>
        </Row>
      </div>
    </section>
  </>;
}

export function BrowserSettings({baseUrl,sessionId}: SessionBrowserProps) {
  const [ask,setAsk]=useState(false), [tools,setTools]=useState(true), [cdp,setCdp]=useState(false);
  const [history,setHistory]=useState<Permission>("Always ask");
  const [location,setLocation]=useState("System Downloads folder");
  const [panel,setPanel]=useState(""), [draft,setDraft]=useState(""), [error,setError]=useState("");
  const [rules,setRules]=useState<Rule[]>([defaults]), [offset,setOffset]=useState(0);
  const id=useId();
  function show(name:string,initial="") {setPanel(name);setDraft(initial);setError("");}
  function update(site:string,col:Column,value:Permission) {
    setRules(rows=>rows.map(r=>r.site===site?{...r,permissions:{...r.permissions,[col]:value}}:r));
  }
  const dialog=panel && <dialog open className="jg-browser-dialog" aria-labelledby={id} onKeyDown={e=>{if(e.key==="Escape")setPanel("");}}>
    <h3 id={id}>{panel}</h3>
    {panel==="Import browser data" && <p>Browser import will be available when Jaeger connects to a browser profile.</p>}
    {panel==="Code Review settings" && <p>Pull request link preferences will appear here when Code Review is connected.</p>}
    {panel==="Browsing history" && <p>Visited pages will appear here when the browser is connected.</p>}
    {panel==="Clear browsing data" && <p>Clearing browser data will be available when the browser is connected.</p>}
    {panel==="Password manager" && <PasswordVault/>}
    {panel==="Contact info" && <PasswordVault contacts/>}
    {panel==="Extension manager" && <p>Installed browser extensions will appear here when the extension manager is connected.</p>}
    {panel==="Download history" && <p>Download history will appear here when the browser is connected.</p>}
    {panel==="Site settings" && (["Camera","Microphone"] as const).map(col=><label key={col}>{col}<Choice name={col} value={rules[0].permissions[col]} onChange={p=>update("Default",col,p)}/></label>)}
    {(panel==="Download location" || panel==="Add website") && <form onSubmit={e=>{
      e.preventDefault(); const value=draft.trim(); if(!value)return;
      if(panel==="Download location")setLocation(value);
      else if(rules.some(r=>r.site.toLowerCase()===value.toLowerCase())){setError("This site already has a rule.");return;}
      else setRules(rs=>[...rs,{site:value,permissions:{...rs[0].permissions}}]);
      setPanel("");
    }}><label>{panel==="Download location"?"Folder":"Site or pattern"}<input autoFocus required value={draft} placeholder={panel==="Add website"?"example.com":"System Downloads folder"} onChange={e=>setDraft(e.target.value)}/></label>
    {error && <p role="alert">{error}</p>}<button className="jg-btn">Save</button></form>}
    <button type="button" onClick={()=>setPanel("")} className="jg-btn">Close</button>
  </dialog>;
  return <div className="jg-browser-settings">
    <BrowserGeneral key={sessionId} baseUrl={baseUrl} sessionId={sessionId} show={show}/>
    <section><h2>Autofill and passwords</h2><div className="jg-browser-card">
      <Row title="Password manager" description="Add, delete, and edit saved passwords">
        <button type="button" aria-label="Manage saved passwords" onClick={()=>show("Password manager")}>Manage</button>
      </Row>
      <Row title="Contact info" description="Add, delete, and edit saved addresses, phone numbers, and email addresses">
        <button type="button" aria-label="Manage contact info" onClick={()=>show("Contact info")}>Manage</button>
      </Row>
    </div></section>
    <section><h2>Extensions</h2><div className="jg-browser-card">
      <Row title="Extension manager" description="Install, remove, and configure browser extensions">
        <button type="button" aria-label="Manage browser extensions" onClick={()=>show("Extension manager")}>Manage</button>
      </Row>
    </div></section>
    <section><h2>Downloads</h2><div className="jg-browser-card">
      <Row title="Location" description={location}><button onClick={()=>show("Download location",location)}>Change</button></Row>
      <Row title="Ask where to save downloads" description="Show a save dialog for downloads you start in the built-in browser"><Switch name="Ask where to save downloads" value={ask} onChange={()=>setAsk(!ask)}/></Row>
      <Row title="Download history" description="View and manage files downloaded from the built-in browser"><button aria-label="Manage download history" onClick={()=>show("Download history")}>Manage</button></Row>
    </div></section>
    <section><h2>Browser permissions</h2><div className="jg-browser-card">
      <Row title="Site settings" description="Control camera and microphone permissions in the built-in browser"><button aria-label="Manage site settings" onClick={()=>show("Site settings")}>Manage</button></Row>
      <Row title="History" description="Choose whether Jaeger can access your built-in browser history"><Choice name="Browser history access" value={history} onChange={setHistory}/></Row>
      <Row title="Use site tools by default" description="Allow Jaeger to discover and call tools provided by websites, including WebMCP, unless you set a different permission for a site"><Switch name="Use site tools by default" value={tools} onChange={()=>setTools(!tools)}/></Row>
    </div></section>
    <section><div className="jg-browser-heading"><h2>Website permissions</h2><button onClick={()=>show("Add website")}><Plus size={15}/> Add</button></div>
    <p>Choose default permissions and add exceptions for specific websites</p>
    <div className="jg-browser-card jg-permission-table"><table><thead><tr><th>Site or pattern</th>{columns.slice(offset,offset+2).map(c=><th key={c}>{c}</th>)}<th><button aria-label="Previous permissions" disabled={!offset} onClick={()=>setOffset(offset-1)}><ChevronLeft size={14}/></button><button aria-label="Next permissions" disabled={offset>=columns.length-2} onClick={()=>setOffset(offset+1)}><ChevronRight size={14}/></button></th></tr></thead>
    <tbody>{rules.map(r=><tr key={r.site}><th>{r.site}</th>{columns.slice(offset,offset+2).map(c=><td key={c}><Choice name={r.site+" "+c} value={r.permissions[c]} onChange={p=>update(r.site,c,p)}/></td>)}<td>{r.site!=="Default" && <button aria-label={"Remove "+r.site} onClick={()=>setRules(rs=>rs.filter(x=>x.site!==r.site))}>×</button>}</td></tr>)}</tbody></table></div>
    <small>Only sites with custom permissions appear here</small></section>
    <section><h2>Developer mode</h2><div className="jg-browser-card"><div className="jg-risk"><ShieldAlert size={15}/> Elevated risk</div>
      <Row title="Enable full CDP access" description="Allow Jaeger to use the full Chrome DevTools Protocol in connected browser sessions. Full CDP access lets Jaeger inspect and control sensitive browser internals that may put your data at risk."><Switch name="Enable full CDP access" value={cdp} onChange={()=>setCdp(!cdp)}/></Row>
    </div></section>
    <small>Browser grants and stops apply to the current Gateway conversation. Passwords and contact information are encrypted in this browser profile. Other controls are previews.</small>
    {dialog}
  </div>;
}
