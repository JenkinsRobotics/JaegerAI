import { useEffect, useRef, useState } from "react";
import { decryptVault, readVault, saveVault, unlockKey, type Contact, type Credential, type Vault } from "./privateStore";
const empty={id:"",site:"",username:"",password:""};
const emptyContact:Contact={id:"",kind:"contact",name:"",address:"",phone:"",email:""};
export function PasswordVault({contacts=false}:{contacts?:boolean}={}){
  const [exists,setExists]=useState<boolean>(),[pass,setPass]=useState(""),[confirm,setConfirm]=useState("");
  const [session,setSession]=useState<{key:CryptoKey;salt:Vault["salt"];revision:number;entries:(Credential|Contact)[]}|null>(null);
  const [draft,setDraft]=useState(empty),[busy,setBusy]=useState(false),[error,setError]=useState("");
  useEffect(()=>{readVault().then(v=>setExists(!!v)).catch(()=>setError("Device storage unavailable."));},[]);
  const [contact,setContact]=useState(emptyContact);
  const generation=useRef(0);
  function lock(){generation.current++;setSession(null);setContact(emptyContact);setDraft(empty);setPass("");setConfirm("");setError("");}
  useEffect(()=>{
    const hide=()=>{if(document.hidden)lock();};
    document.addEventListener("visibilitychange",hide);
    const timer=session ? window.setTimeout(lock,300000) : undefined;
    return ()=>{document.removeEventListener("visibilitychange",hide);clearTimeout(timer);};
  },[session]);
  async function unlock(){
    const attempt=generation.current;
    setBusy(true);setError("");
    try{
      const vault=await readVault();
      if(!vault && (pass.length<12 || pass!==confirm))throw new Error("Use a matching passphrase of at least 12 characters.");
      const salt=vault?.salt ?? crypto.getRandomValues(new Uint8Array(16));
      const key=await unlockKey(pass,salt);
      const entries=vault?await decryptVault(key,vault):[];
      if(attempt!==generation.current || document.hidden)return;
      if(!vault)await saveVault(key,salt,0,entries);
      if(attempt!==generation.current || document.hidden)return;
      setSession({key,salt,revision:vault?.revision ?? 1,entries});setExists(true);setPass("");setConfirm("");
    }catch(e){setError(e instanceof Error && e.name!=="OperationError"?e.message:"Could not unlock the vault.");}
    finally{setBusy(false);}
  }
  async function commit(entries:(Credential|Contact)[]){
    if(!session || busy)return;
    const attempt=generation.current;
    setBusy(true);setError("");
    try{await saveVault(session.key,session.salt,session.revision,entries);if(attempt!==generation.current || document.hidden)return;setSession({...session,revision:session.revision+1,entries});setDraft(empty);setContact(emptyContact);}
    catch{setError("Could not save. Lock and reopen to load the latest vault.");}finally{setBusy(false);}
  }
  return <section className="jg-vault"><p>Encrypted in this browser profile. Keep your passphrase to recover access.</p>
    {!session?<form onSubmit={e=>{e.preventDefault();void unlock();}}>
    <label>Vault passphrase<input type="password" autoComplete={exists?"current-password":"new-password"} required value={pass} onChange={e=>setPass(e.target.value)}/></label>
    {exists===false && <label>Confirm passphrase<input type="password" autoComplete="new-password" required value={confirm} onChange={e=>setConfirm(e.target.value)}/></label>}
    <button disabled={busy || exists===undefined}>{exists?"Unlock":"Create vault"}</button></form>:<>
    <button type="button" onClick={lock}>Lock vault</button>
    {session.entries.map(entry=>{
      if(entry.kind==="contact")return contacts && <div key={entry.id} className="jg-browser-row"><span>{entry.name}</span><button onClick={()=>setContact({...entry})}>Edit</button></div>;
      return !contacts && <div key={entry.id} className="jg-browser-row"><span>{entry.site} · {entry.username}</span><button onClick={()=>setDraft({...entry})}>Edit</button></div>;
    })}
    {contacts ? <form onSubmit={e=>{e.preventDefault();const updated={...contact,id:contact.id||crypto.randomUUID()};void commit([...session.entries.filter(item=>item.id!==updated.id),updated]);}}>
      {(["name","address","phone","email"] as const).map(field=><label key={field}>{field}<input type={field==="email"?"email":field==="phone"?"tel":"text"} required={field==="name"} value={contact[field]} onChange={e=>setContact({...contact,[field]:e.target.value})}/></label>)}
      <button disabled={busy}>Save contact</button>{contact.id && <button type="button" disabled={busy} onClick={()=>{if(window.confirm("Delete this contact?"))void commit(session.entries.filter(item=>item.id!==contact.id));}}>Delete contact</button>}
    </form> :
    <form onSubmit={e=>{e.preventDefault();if(!session)return;const entry={...draft,id:draft.id||crypto.randomUUID()};void commit([...session.entries.filter(item=>item.id!==entry.id),entry]);}}>
      <label>Site<input required value={draft.site} onChange={e=>setDraft({...draft,site:e.target.value})}/></label>
      <label>Username<input value={draft.username} onChange={e=>setDraft({...draft,username:e.target.value})}/></label>
      <label>Password<input type="password" autoComplete="new-password" required value={draft.password} onChange={e=>setDraft({...draft,password:e.target.value})}/></label>
      <button disabled={busy}>Save login</button> {draft.id && <button type="button" disabled={busy} onClick={()=>{if(window.confirm("Delete this saved login?"))void commit(session.entries.filter(e=>e.id!==draft.id));}}>Delete login</button>}
    </form>}</>}{error && <p role="alert">{error}</p>}</section>;
}
