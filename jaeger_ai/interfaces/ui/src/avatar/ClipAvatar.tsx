import {useCallback,useEffect,useRef,useState} from 'react';
import {useReducedMotion} from './AvatarStage';
import {getAvatar,JAEGER_BUNDLE,missingClip,STATUS_TEXT,type AvatarBundle,type ClipState} from './avatar';
import './clipAvatar.css';

export function ClipAvatar({state='idle',size=94,name='Jaeger',still=false,bundle=JAEGER_BUNDLE,showStatus=false,portraitOverride}: {state?:ClipState;size?:number;name?:string;still?:boolean;bundle?:AvatarBundle;showStatus?:boolean;portraitOverride?:string}) {
 const reduced=useReducedMotion();
 const media=getAvatar('jaeger',state,bundle);
 const [failed,setFailed]=useState<string[]>([]);
 const [playing,setPlaying]=useState('');
 const [playback,setPlayback]=useState<'poster'|'loading'|'playing'>('poster');
 const video=useRef<HTMLVideoElement>(null);
 const animate=!portraitOverride&&!still&&!reduced&&media.kind==='video'&&!failed.includes(media.src);
 const resume=useCallback(()=>{
  const element=video.current;
  if(!element||document.hidden)return;
  setPlayback('loading');
  void element.play().then(()=>{setPlaying(media.src);setPlayback('playing');}).catch(()=>setPlayback('poster'));
 },[media.src]);
 useEffect(()=>{
  if(!animate)return;
  const timer=setTimeout(()=>{if(video.current?.readyState===0){missingClip(media.src);setFailed(old=>[...old,media.src]);}},8000);
  const visible=()=>{if(!document.hidden)resume();};
  window.addEventListener('pageshow',resume);
  document.addEventListener('visibilitychange',visible);
  return()=>{clearTimeout(timer);window.removeEventListener('pageshow',resume);document.removeEventListener('visibilitychange',visible);};
 },[animate,media.src,resume]);
 useEffect(()=>{setPlaying('');setPlayback(animate?'loading':'poster');},[animate,media.src]);
 const fail=()=>{missingClip(media.src);setFailed(old=>[...old,media.src]);};
 return <span className="jg-clip-identity" data-avatar-state={state}>
  <span className="jg-clip-avatar" data-motion={animate?(playback==='playing'?'video':'poster'):undefined} style={{width:size,height:size}}>
   <img src={portraitOverride||media.portrait} alt={`${name} avatar`} draggable={false}/>
   {animate&&<video key={media.src} ref={video} src={media.src} poster={media.portrait} autoPlay muted loop playsInline preload="auto" aria-hidden="true" onPlaying={()=>{setPlaying(media.src);setPlayback('playing');}} onPause={()=>setPlayback('poster')} onError={fail} onCanPlay={resume} style={{opacity:playing===media.src?1:0}}/>}
  </span>
  {showStatus&&<span className="jg-clip-status" role="status">{STATUS_TEXT[state]}</span>}
 </span>;
}
