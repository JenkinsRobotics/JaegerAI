import {useEffect,useRef,useState} from 'react';
import './companionMode.css';

export function CompanionMode({team,onChange}:{team:boolean;onChange:(team:boolean)=>void}) {
 const [open,setOpen]=useState(false);
 const root=useRef<HTMLDivElement>(null);
 const trigger=useRef<HTMLButtonElement>(null);
 useEffect(()=>{
  if(!open)return;
  const outside=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false);};
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.stopPropagation();setOpen(false);trigger.current?.focus();}};
  document.addEventListener('pointerdown',outside);
  document.addEventListener('keydown',escape,true);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape,true);};
 },[open]);
 return <div ref={root} className="jg-companion-mode">
  <button ref={trigger} type="button" className="jg-companion-mode__trigger" aria-label="Switch companion mode" aria-expanded={open} aria-controls="companion-mode-options" onClick={()=>setOpen(!open)}><strong>{team?'Team':'Jaeger'}</strong><span aria-hidden="true">⌄</span></button>
  {open&&<div id="companion-mode-options" className="jg-companion-mode__options" role="group" aria-label="Companion mode">
   {[{team:false,name:'Jaeger',description:'Your companion and main conversation'},{team:true,name:'Team',description:'Check in on agents and delegated work'}].map(option=><button key={option.name} type="button" aria-pressed={team===option.team} onClick={()=>{onChange(option.team);setOpen(false);trigger.current?.focus();}}><span><strong>{option.name}</strong><small>{option.description}</small></span><span aria-hidden="true">{team===option.team?'✓':''}</span></button>)}
  </div>}
 </div>;
}
