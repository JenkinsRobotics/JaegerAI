import {useEffect,useState,type RefObject} from 'react';
import './conversationMinimap.css';

export function ConversationMinimap({scroller,revision,onNavigate}:{scroller:RefObject<HTMLDivElement|null>;revision:unknown;onNavigate:()=>void}) {
 const [marks,setMarks]=useState<Array<{id:string;label:string;visible:boolean}>>([]);
 useEffect(()=>{
  const root=scroller.current;if(!root)return;
  let frame=0;
  const update=()=>{
   cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{
    const bounds=root.getBoundingClientRect();
    setMarks([...root.querySelectorAll<HTMLElement>('[data-turn-id]')].map((el,i)=>{
     const rect=el.getBoundingClientRect();
     return {id:el.dataset.turnId!,label:`Turn ${i+1}: ${(el.querySelector('.jg-bubble--user')?.textContent || 'Agent update').slice(0,100)}`,visible:rect.bottom>bounds.top && rect.top<bounds.bottom};
    }));
   });
  };
  const resize=new ResizeObserver(update);resize.observe(root);
  if(root.firstElementChild)resize.observe(root.firstElementChild);
  root.addEventListener('scroll',update,{passive:true});update();
  return()=>{cancelAnimationFrame(frame);resize.disconnect();root.removeEventListener('scroll',update);};
 },[scroller,revision]);
 if(marks.length<2)return null;
 return <nav className="jg-conversation-minimap" aria-label="Conversation minimap">{marks.map(mark=><button type="button" key={mark.id} title={mark.label} aria-label={mark.label} aria-current={mark.visible?'location':undefined} onClick={()=>{
  const root=scroller.current;const target=[...root?.querySelectorAll<HTMLElement>('[data-turn-id]')||[]].find(el=>el.dataset.turnId===mark.id);
  if(root&&target){onNavigate();root.scrollTo({top:root.scrollTop+target.getBoundingClientRect().top-root.getBoundingClientRect().top,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
 }}><span /></button>)}</nav>;
}
