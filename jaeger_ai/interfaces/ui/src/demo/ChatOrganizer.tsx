import {useEffect,useRef,useState} from "react";
import type {JaegerSource} from "../api/source";
import type {Organization,OrganizationAction,OrganizationProposal,ChatGroup} from "../api/organization";
import "./chatOrganizer.css";

export function ChatOrganizer({source,initialSelection=[],onClose,onChanged,onOpen,onDelete}:{source:JaegerSource;initialSelection?:string[];onClose():void;onChanged():Promise<void>;onOpen(id:string):void;onDelete(ids:string[]):void}) {
 const [data,setData]=useState<Organization|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 const [selection,setSelection]=useState(new Set(initialSelection)),[search,setSearch]=useState(""),[archive,setArchive]=useState(false);
 const [title,setTitle]=useState(""),[instruction,setInstruction]=useState("Suggest descriptive names and group related chats into projects. Preserve names I set manually.");
 const [groupName,setGroupName]=useState(""),[groupKind,setGroupKind]=useState<"project"|"section">("project"),[editingGroup,setEditingGroup]=useState("");
 const [notes,setNotes]=useState(""),[preview,setPreview]=useState<OrganizationProposal|null>(null),[undo,setUndo]=useState(""),[notice,setNotice]=useState("");
 const dialog=useRef<HTMLDialogElement>(null);
 const api=source.organization;
 const refresh=async()=>{if(api)setData(await api.get());};
 useEffect(()=>{dialog.current?.showModal?.(); void refresh().catch(e=>setError(e.message));},[source]);
 const run=async(fn:()=>Promise<void>)=>{setBusy(true);setError("");try{await fn();}catch(e){setError((e as Error).message);await refresh().catch(()=>{});}finally{setBusy(false);}};
 const apply=async(actions:OrganizationAction[],revision=data?.revision)=>{
  if(!api||revision===undefined)return;
  const result=await api.command({action:"apply",actions,revision,operation_id:crypto.randomUUID()});
  setUndo(result.operation_id||"");setNotice("Changes saved");await refresh();await onChanged();
 };
 const selected=Array.from(selection),single=data?.sessions.find(s=>s.session_id===selected[0]);
 const rows=(data?.sessions||[]).filter(s=>s.archived===archive && (s.title+" "+s.workspace+" "+s.session_id).toLowerCase().includes(search.toLowerCase())).sort((a,b)=>(a.position??Number.MAX_SAFE_INTEGER)-(b.position??Number.MAX_SAFE_INTEGER));
 const toggle=(id:string)=>setSelection(old=>{const n=new Set(old);n.has(id)?n.delete(id):n.add(id);return n;});
 const move=(field:string,group_id:string)=>void run(()=>apply([{type:"move",session_ids:selected,field,group_id:group_id||null}]));
 const suggest=(prompt:string,renameManual=false)=>void run(async()=>{
  if(!api)return;
  const p=await api.command({action:"suggest",session_ids:selected,instruction:prompt,rename_manual:renameManual});
  if(p.id&&p.actions&&p.revision!==undefined)setPreview(p as OrganizationProposal);
  await refresh();
 });
 const editGroup=(g:ChatGroup)=>{setEditingGroup(g.id);setGroupName(g.name);setGroupKind(g.kind);setNotes(g.notes||"");};
 const describe=(a:OrganizationAction)=>{
  const names=(a.session_ids as string[]|undefined)?.map(id=>data?.sessions.find(s=>s.session_id===id)?.title||id).join(", ");
  const group=[...(data?.groups||[]),...(preview?.actions.filter(x=>x.type==="create_group").map(x=>({id:x.id,name:x.name}))||[])].find(g=>g.id===a.group_id);
  if(a.type==="rename")return names+" → "+a.title;
  if(a.type==="rename_group")return "Rename "+(data?.groups.find(g=>g.id===a.id)?.name||a.id)+" → "+a.name;
  if(a.type==="create_group")return "Create "+a.kind+": "+a.name;
  if(a.type==="move")return names+" → "+(group?.name||"Ungrouped");
  return a.type;
 };
 const reorderChat=(direction:number)=>void run(async()=>{
  if(!data||selected.length!==1)return;
  const order=rows.map(s=>s.session_id),i=order.indexOf(selected[0]),j=i+direction;
  if(i<0||j<0||j>=order.length)return;
  [order[i],order[j]]=[order[j],order[i]];
  await apply([{type:"reorder_chats",order}]);
 });
 return <dialog ref={dialog} className="jg-organizer" aria-labelledby="chat-organizer-title" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
  <header><div><h2 id="chat-organizer-title">Manage conversations</h2><p>Organize your chats across the app and web.</p></div><button type="button" aria-label="Close chat manager" disabled={busy} onClick={onClose}>×</button></header>
  {!api?<p role="alert">This connection does not support chat organization.</p>:<>
  <div className="jg-organizer__status" aria-live="polite">{busy?"Working…":notice}{undo&&<button disabled={busy} onClick={()=>void run(async()=>{await api.command({action:"undo",operation_id:undo});setUndo("");setNotice("Changes undone");await refresh();await onChanged();})}>Undo last change</button>}</div>
  {error&&<p role="alert" className="jg-organizer__error">{error}</p>}
  <div className="jg-organizer__body">
   <section className="jg-organizer__chats" aria-label="Conversations">
    <div className="jg-organizer__filters"><input aria-label="Search conversations" placeholder="Search names or workspaces" value={search} onChange={e=>setSearch(e.target.value)}/>
     <button aria-pressed={!archive} onClick={()=>{setArchive(false);setSelection(new Set());}}>Active</button><button aria-pressed={archive} onClick={()=>{setArchive(true);setSelection(new Set());}}>Archived</button></div>
    <div className="jg-organizer__selection"><button disabled={busy||!rows.length} onClick={()=>setSelection(selection.size===rows.length?new Set():new Set(rows.map(s=>s.session_id)))}>{selection.size===rows.length&&rows.length?"Clear selection":"Select shown"}</button><span>{selected.length} selected</span><button disabled={busy||selected.length!==1} onClick={()=>reorderChat(-1)}>Move up</button><button disabled={busy||selected.length!==1} onClick={()=>reorderChat(1)}>Move down</button></div>
    <div className="jg-organizer__list">{!data?<p>Loading conversations…</p>:!rows.length?<p>No {archive?"archived ":""}conversations match.</p>:rows.map(s=><label className="jg-organizer__row" key={s.session_id} data-selected={selection.has(s.session_id)}><input type="checkbox" aria-label={"Select "+s.title} checked={selection.has(s.session_id)} disabled={busy} onChange={()=>{toggle(s.session_id);setTitle(s.title);}}/><span><strong>{s.title||"Untitled conversation"}</strong><small>{[s.pinned?"Pinned":"",data.groups.find(g=>g.id===s.project_id)?.name,data.groups.find(g=>g.id===s.section_id)?.name,s.workspace?.split("/").pop()].filter(Boolean).join(" · ")||"No project"}{" · "+s.session_id.slice(-8)}</small></span><button type="button" disabled={busy} aria-label={"Open "+s.title} onClick={e=>{e.preventDefault();onOpen(s.session_id);onClose();}}>Open</button></label>)}</div>
   </section>
   <aside className="jg-organizer__actions" aria-label="Organization actions">
    <fieldset disabled={busy||!selected.length}><legend>Selected conversations</legend>
     <div className="jg-organizer__inline"><button onClick={()=>void run(()=>apply([{type:"pin",session_ids:selected,value:true}]))}>Pin</button><button onClick={()=>void run(()=>apply([{type:"pin",session_ids:selected,value:false}]))}>Unpin</button><button onClick={()=>void run(async()=>{await apply([{type:"archive",session_ids:selected,value:!archive}]);setSelection(new Set());})}>{archive?"Restore":"Archive"}</button></div>
     <label>Project<select aria-label="Move to project" value="" onChange={e=>move("project_id",e.target.value==="__none"?"":e.target.value)}><option value="" disabled>Move to project…</option><option value="__none">No project</option>{data?.groups.filter(g=>g.kind==="project").map(g=><option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
     <label>Section<select aria-label="Move to section" value="" onChange={e=>move("section_id",e.target.value==="__none"?"":e.target.value)}><option value="" disabled>Move to section…</option><option value="__none">No section</option>{data?.groups.filter(g=>g.kind==="section").map(g=><option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
     <label>Conversation name<input aria-label="Conversation name" disabled={selected.length!==1} value={title} placeholder={single?.title||"Select one conversation"} onChange={e=>setTitle(e.target.value)}/></label>
     <div className="jg-organizer__inline"><button disabled={selected.length!==1||!title.trim()} onClick={()=>void run(()=>apply([{type:"rename",session_ids:selected,title}]))}>Save name</button><button disabled={selected.length>40} onClick={()=>suggest("Rename the selected chats with concise descriptive titles based on their actual content. Do not group them. This explicitly requests renaming even manually named chats.",true)}>AI name</button></div>
    </fieldset>
    <fieldset disabled={busy}><legend>Projects and sections</legend>
     <select aria-label="Edit group" value={editingGroup} onChange={e=>{const g=data?.groups.find(x=>x.id===e.target.value);if(g)editGroup(g);else{setEditingGroup("");setGroupName("");setNotes("");}}}><option value="">Create new…</option>{data?.groups.map(g=><option key={g.id} value={g.id}>{g.name} ({g.kind})</option>)}</select>
     {!editingGroup&&<select aria-label="Group type" value={groupKind} onChange={e=>setGroupKind(e.target.value as "project"|"section")}><option value="project">Project</option><option value="section">Section</option></select>}
     <input aria-label="Group name" placeholder="Name" value={groupName} onChange={e=>setGroupName(e.target.value)}/>
     {editingGroup&&groupKind==="project"&&<label>Project notes<textarea aria-label="Project notes" value={notes} onChange={e=>setNotes(e.target.value)} maxLength={12000}/><small>Shared as reference context in future chats in this project. No file access is granted.</small></label>}
     <button disabled={!groupName.trim()} onClick={()=>void run(async()=>{
      const actions:OrganizationAction[]=editingGroup?[{type:"rename_group",id:editingGroup,name:groupName},...(groupKind==="project"?[{type:"group_notes",id:editingGroup,notes}]:[])]:[{type:"create_group",id:crypto.randomUUID(),kind:groupKind,name:groupName}];
      await apply(actions);setEditingGroup("");setGroupName("");setNotes("");
     })}>{editingGroup?"Save group":"Create group"}</button>
     {editingGroup&&<div className="jg-organizer__inline"><button onClick={()=>void run(async()=>{if(!data)return;const order=data.groups.map(g=>g.id),i=order.indexOf(editingGroup);if(i>0){[order[i-1],order[i]]=[order[i],order[i-1]];await apply([{type:"reorder_groups",order}]);}})}>Move group up</button><button onClick={()=>void run(async()=>{await apply([{type:"remove_group",id:editingGroup}]);setEditingGroup("");setGroupName("");})}>Remove group</button></div>}
     {editingGroup&&<small>Removing a group keeps its conversations.</small>}
    </fieldset>
    <fieldset disabled={busy||!selected.length||selected.length>40}><legend>Organize with Jaeger</legend><textarea aria-label="Organization instructions" value={instruction} onChange={e=>setInstruction(e.target.value)} maxLength={2000}/><button onClick={()=>suggest(instruction)}>Preview AI suggestions</button><small>Review names and groups before applying. Up to 40 chats at a time.</small></fieldset>
    {!!data?.proposals.length&&<section aria-label="Saved suggestions"><h3>Suggestions to review</h3>{data.proposals.map(p=><div className="jg-organizer__inline" key={p.id}><button disabled={busy} onClick={()=>setPreview(p)}>{p.label}</button><button aria-label={"Dismiss "+p.label} disabled={busy} onClick={()=>void run(async()=>{await api.command({action:"dismiss",proposal_id:p.id});await refresh();})}>Dismiss</button></div>)}</section>}
    <details><summary>Delete conversations</summary><p>Permanent deletion removes the saved history. Archive keeps it available.</p><button className="jg-organizer__danger" disabled={busy||!selected.length} onClick={()=>{onDelete(selected);onClose();}}>Delete selected…</button></details>
   </aside>
  </div>
  {preview&&<section className="jg-organizer__preview" aria-label="Review organization suggestions"><h3>{preview.label}</h3><p>{preview.actions.length} changes. Conversations retain their history and workspace.</p><ol>{preview.actions.map((a,i)=><li key={i}>{describe(a)}</li>)}</ol><div><button disabled={busy} onClick={()=>setPreview(null)}>Back</button><button disabled={busy||!data||preview.revision!==data.revision} onClick={()=>void run(async()=>{await apply(preview.actions,preview.revision);await api.command({action:"dismiss",proposal_id:preview.id});setPreview(null);await refresh();})}>Apply suggestions</button></div>{data&&preview.revision!==data.revision&&<p role="alert">Organization changed since this preview. Generate a fresh suggestion.</p>}</section>}
  </>}
 </dialog>;
}
