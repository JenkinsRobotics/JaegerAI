import { useEffect, useState } from "react";
type Outgoing={message_id:string;channel:string;status:string;recipient:string;body:string};
export function EmailDelivery({baseUrl}:{baseUrl:string}){
  const [ready,setReady]=useState(false),[recipient,setRecipient]=useState(""),[items,setItems]=useState<Outgoing[]>([]);
  const [responses,setResponses]=useState(false),[tasks,setTasks]=useState(false);
  const [status,setStatus]=useState("Checking mail transport…"),[busy,setBusy]=useState(false);
  async function refresh(){
    const response=await fetch(baseUrl+"/v1/channels/status",{cache:"no-store"});
    if(!response.ok)throw new Error("Mail settings unavailable ("+response.status+")");
    const data=await response.json(), configured=!!data.channels?.configured_adapters?.includes("email");
    if(data.email_preferences){setRecipient(data.email_preferences.recipient);setResponses(data.email_preferences.responses);setTasks(data.email_preferences.tasks);}
    setReady(configured);setItems((data.outbox ?? []).filter((m:Outgoing)=>m.channel==="email"));
    setStatus(configured?"SMTP transport configured":"Set JAEGER_SMTP_HOST and JAEGER_SMTP_FROM on the Gateway. Optional authentication uses JAEGER_SMTP_USER and JAEGER_SMTP_PASSWORD. The default is TLS on port 465.");
  }
  useEffect(()=>{void refresh().catch(e=>setStatus(String(e)));},[baseUrl]);
  async function perform(path:string,body:object,method="POST"){
    setBusy(true);
    try{const response=await fetch(baseUrl+path,{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(!response.ok)throw new Error("Mail request failed ("+response.status+")");
      await refresh();
    }catch(e){setStatus(String(e));}finally{setBusy(false);}
  }
  return <section><h2>Email delivery</h2><div className="jg-browser-card"><p role="status">{status}</p>
    <form onSubmit={e=>{e.preventDefault();void perform("/v1/channels/email/preferences",{recipient,responses,tasks},"PUT");}}>
      <label>Notification recipient <input required={responses||tasks} type="email" value={recipient} onChange={e=>setRecipient(e.target.value)}/></label>
      <label><input type="checkbox" checked={responses} onChange={e=>setResponses(e.target.checked)}/>Responses · email when a response finishes</label>
      <label><input type="checkbox" checked={tasks} onChange={e=>setTasks(e.target.checked)}/>Tasks · email when a scheduled task finishes</label>
      <button disabled={busy}>Save email preferences</button>
      <button type="button" disabled={!ready||busy||!recipient} onClick={()=>void perform("/v1/channels/send",{channel:"email",recipient,body:"Test notification from Jaeger."})}>Queue test email</button>
    </form><p>Emails wait in the Gateway outbox for approval. <a href="/tasks">Manage tasks</a></p><button disabled={busy} onClick={()=>void refresh().catch(e=>setStatus(String(e)))}>Refresh outbox</button>
    {items.map(m=><div key={m.message_id} className="jg-browser-row"><span>{m.recipient} · {m.status}<br/>{m.body}</span>{m.status==="queued_for_approval" && <button disabled={!ready||busy} onClick={()=>void perform("/v1/channels/messages/"+encodeURIComponent(m.message_id)+"/approve",{})}>Approve and send</button>}</div>)}</div></section>;
}
