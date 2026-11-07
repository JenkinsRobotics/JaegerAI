import {useEffect,useRef,useState} from 'react';
import {useReducedMotion} from './AvatarStage';
import {getAvatar,JAEGER_BUNDLE,missingClip,STATUS_TEXT,type AvatarBundle,type ClipState} from './avatar';
import './clipAvatar.css';

export function ClipAvatar({state='idle',size=94,name='Jaeger',still=false,bundle=JAEGER_BUNDLE,showStatus=false,portraitOverride}: {state?:ClipState;size?:number;name?:string;still?:boolean;bundle?:AvatarBundle;showStatus?:boolean;portraitOverride?:string}) {
 const reduced=useReducedMotion();
 const media=getAvatar('jaeger',state,bundle);
 const [failed,setFailed]=useState<string[]>([]);
 const [playing,setPlaying]=useState('');
 const video=useRef<HTMLVideoElement>(null);
 const animate=!portraitOverride&&!still&&!reduced&&media.kind==='video'&&!failed.includes(media.src);
 useEffect(()=>{
  if(!animate)return;
  const timer=setTimeout(()=>{if(video.current?.readyState===0){missingClip(media.src);setFailed(old=>[...old,media.src]);}},8000);
  return()=>clearTimeout(timer);
 },[animate,media.src]);
 useEffect(()=>{
  if(portraitOverride||still||reduced)return;
  const preloads=['idle','working'].flatMap(state=>{const href=bundle.videos[state as ClipState];if(!href)return [];const link=document.createElement('link');link.rel='preload';link.as='video';link.href=href;document.head.append(link);return [link];});
  return()=>preloads.forEach(link=>link.remove());
 },[bundle,still,reduced,portraitOverride]);
 useEffect(()=>setPlaying(''),[media.src]);
 const fail=()=>{missingClip(media.src);setFailed(old=>[...old,media.src]);};
 return <span className="jg-clip-identity" data-avatar-state={state}>
  <span className="jg-clip-avatar" style={{width:size,height:size}}>
   <img src={portraitOverride||media.portrait} alt={`${name} avatar`} draggable={false}/>
   {animate&&<video key={media.src} ref={video} src={media.src} poster={media.portrait} autoPlay muted loop playsInline preload="auto" aria-hidden="true" onPlaying={()=>setPlaying(media.src)} onError={fail} onCanPlay={()=>{void video.current?.play().catch(fail);}} style={{opacity:playing===media.src?1:0}}/>}
  </span>
  {showStatus&&<span className="jg-clip-status" role="status">{STATUS_TEXT[state]}</span>}
 </span>;
}
