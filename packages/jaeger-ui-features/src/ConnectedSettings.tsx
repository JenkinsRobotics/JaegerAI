import { useEffect, useState } from "react";
import { Row } from "./BrowserSettings";
import { useSetting } from "./userPreferences";

export function VoiceDeviceSettings({kind}: {kind:"microphone"|"voice"}) {
  const [value,setValue]=useSetting(kind==="microphone"?"microphone":"speechVoice");
  const [options,setOptions]=useState<Array<[string,string]>>([]);
  useEffect(()=>{
    let active=true;
    const refresh=async()=>{
      const list:Array<[string,string]>=kind==="voice"
        ? (window.speechSynthesis?.getVoices() ?? []).map(v=>[v.voiceURI,v.name+" · "+v.lang])
        : (await navigator.mediaDevices?.enumerateDevices().catch(()=>[]) ?? [])
          .filter(d=>d.kind==="audioinput" && d.deviceId && d.deviceId!=="default")
          .map((d,i)=>[d.deviceId,d.label || "Microphone "+(i+1)]);
      if(active)setOptions(list);
    };
    void refresh();
    const source=kind==="voice"?window.speechSynthesis:navigator.mediaDevices;
    const event=kind==="voice"?"voiceschanged":"devicechange";
    source?.addEventListener(event,refresh);
    return ()=>{active=false;source?.removeEventListener(event,refresh);};
  },[kind]);
  const title=kind==="voice"?"Voice":"Microphone";
  return <Row title={title} description={kind==="voice"?"Voice used for spoken Droid replies":"Input used for Droid voice sessions"}>
    <select aria-label={title} value={value} onChange={e=>setValue(e.target.value)}><option value="">System default</option>
    {value && !options.some(([id])=>id===value) && <option value={value}>Saved device unavailable</option>}
    {options.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></Row>;
}

export function GatewayDetails({kind,baseUrl}: {kind:"memory"|"diagnostics";baseUrl:string}) {
  const [text,setText]=useState("Loading…");
  useEffect(()=>{
    const controller=new AbortController();
    async function load() {
      try {
        const path=kind==="memory"?"/v1/memory/facts":"/v1/diagnostics";
        const response=await fetch(baseUrl+path,{signal:controller.signal});
        if(!response.ok)throw new Error("Gateway returned "+response.status);
        const data=await response.json();
        if(data.ok!==true)throw new Error("Gateway request failed");
        setText(kind==="memory"
          ? data.facts.map((f:{subject:string;key:string;value:string})=>f.subject+" · "+f.key+" — "+f.value).join("\n") || "No saved facts."
          : ["Gateway online","Sessions: "+data.sessions_count,"Pending approvals: "+data.pending_approvals,"Uptime: "+Math.floor(data.uptime_s)+" s"].join("\n"));
      } catch(error) { if(!controller.signal.aborted)setText(String(error)); }
    }
    void load();
    return ()=>controller.abort();
  },[kind,baseUrl]);
  return <pre className="jg-setting-output" role="status">{text}</pre>;
}
