import { useEffect, useState } from "react";
import { activityList, changePolicy, clearActivity, historyPolicy, recordActivity, type Activity, type HistoryPolicy } from "./privateStore";
import { Row, Switch } from "./BrowserSettings";

type NativeHost={post:(type:string,payload:object)=>Promise<{name?:string;allowed?:boolean}>};
const nativeHost=()=>(window as Window & {jaegerNative?:NativeHost}).jaegerNative;
export function useActivityRecorder(view:string) {
  useEffect(()=>{
    let closed=false, timer:number|undefined, generation=0;
    async function configure(){
      const current=++generation;
      clearInterval(timer);
      const policy=await historyPolicy();
      if(closed || current!==generation || !policy.enabled || policy.paused)return;
      await recordActivity(view,"Jaeger");
      const host=nativeHost();
      if(!host || !policy.desktop || closed || current!==generation)return;
      let previous="", pending=false;
      const poll=async()=>{
        if(pending)return;
        pending=true;
        try{
          const {name}=await host.post("history.foreground",{});
          if(!closed && current===generation && name && name!==previous){
            await recordActivity(name,"Desktop");previous=name;
          }
        }catch{/* An older desktop shell can still record Jaeger navigation. */}
        finally{pending=false;}
      };
      void poll();timer=window.setInterval(poll,10000);
    }
    const refresh=()=>{void configure().catch(()=>{});};
    refresh();window.addEventListener("jaeger-history-policy",refresh);
    return ()=>{closed=true;clearInterval(timer);window.removeEventListener("jaeger-history-policy",refresh);};
  },[view]);
}
export function ActivityHistory(){
  const [rows,setRows]=useState<Activity[]>([]),[policy,setPolicy]=useState<HistoryPolicy>();
  const [query,setQuery]=useState(""),[search,setSearch]=useState(false),[access,setAccess]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    let active=true;
    const refresh=async()=>{try{const [p,r]=await Promise.all([historyPolicy(),activityList()]);if(active){setPolicy(p);setRows(r);}}catch{if(active)setError("Activity storage is unavailable.");}};
    const update=()=>void refresh();
    update();window.addEventListener("jaeger-history-updated",update);window.addEventListener("jaeger-history-policy",update);
    return ()=>{active=false;window.removeEventListener("jaeger-history-updated",update);window.removeEventListener("jaeger-history-policy",update);};
  },[]);
  const change=(p:Partial<HistoryPolicy>)=>{void changePolicy(p).catch(()=>setError("Could not save history preferences."));};
  const remove=(id?:number)=>{if(window.confirm(id?"Delete this activity?":"Clear all recorded activity?"))void clearActivity(id).catch(()=>setError("Could not remove activity."));};
  const filtered=rows.filter(r=>r.label.toLowerCase().includes(query.toLowerCase()));
  return <div className="jg-browser-settings"><header className="jg-browser-intro"><h1>Computer history</h1></header>
    <section className="jg-browser-card"><Row title="Computer history" description="Record Jaeger navigation on this device. The latest 1,000 entries are retained.">
    {policy && <div className="jg-personal-actions"><button disabled={!policy.enabled} onClick={()=>change({paused:!policy.paused})}>{policy.paused?"Resume":"Pause"}</button><Switch name="Computer history" value={policy.enabled} onChange={()=>change({enabled:!policy.enabled,paused:false})}/></div>}</Row>
    <Row title="Permissions" description="Choose which activity Jaeger records"><button onClick={()=>setAccess(!access)} aria-expanded={access}>Choose</button></Row>
    {access && <label><input type="checkbox" disabled={!nativeHost()} checked={!!policy?.desktop} onChange={async e=>{
      const enabled=e.target.checked;
      try {
        const result=await nativeHost()?.post("history.consent",{enabled});
        if(enabled && !result?.allowed){setError("Desktop recording permission was declined.");return;}
        setError("");change({desktop:enabled});
      } catch {setError("Desktop activity requires the updated Jaeger macOS app.");}
    }}/>Include foreground app names (Jaeger desktop app)</label>}</section>
    <section><div className="jg-browser-heading"><h2>History</h2><div className="jg-personal-actions"><button disabled={!rows.length} onClick={()=>remove()}>Clear history</button><button onClick={()=>{setSearch(!search);setQuery("");}}>Search your history</button></div></div>
    {search && <input autoFocus aria-label="Search activity" value={query} onChange={e=>setQuery(e.target.value)}/>}
    <div className="jg-browser-card">{!filtered.length && <p>{query?"No matching activity.":"No activity recorded."}</p>}
    {[...new Set(filtered.map(r=>new Date(r.at).toLocaleDateString()))].map(day=><details key={day} open><summary>{day}</summary>{filtered.filter(r=>new Date(r.at).toLocaleDateString()===day).map(r=><article className="jg-history-event" key={r.id}><time>{new Date(r.at).toLocaleTimeString([], {hour:"numeric",minute:"2-digit"})}</time><div><strong>{r.label}</strong><p>{r.source}</p><button aria-label={"Delete "+r.label} onClick={()=>remove(r.id)}>Delete</button></div></article>)}</details>)}</div></section>{error && <p role="alert">{error}</p>}</div>;
}
