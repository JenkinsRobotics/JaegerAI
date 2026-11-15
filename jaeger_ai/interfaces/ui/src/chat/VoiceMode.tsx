import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { speakablePrefix, speechSentences } from './webSpeech';
import { RealtimeVoice, realtimeStatus, type ServiceMessage, type VoiceEngine } from './realtimeVoice';
import { useAudioPreferences } from '../settings/audioPreferences';
import { CameraIcon, CollapseIcon, ExpandIcon, GearIcon, HangUpIcon, MicIcon, ScreenIcon, WaveIcon } from '../icons';
import { AgentAvatar } from '../agents/AgentAvatar';
import { ClipAvatar } from '../avatar/ClipAvatar';
import { sendJson } from '../unified/webui';
import './voiceMode.css';

/** The reply being spoken. ``final`` is false while it is still streaming. */
export interface SpokenReply { id:string; text:string; final?:boolean }
type Phase='connecting'|'listening'|'hearing'|'thinking'|'speaking'|'paused';
const ENGINE_KEY='jaeger.voice.engine';
const readEngine=():VoiceEngine=>{try{return localStorage.getItem(ENGINE_KEY)==='gemini'?'gemini':'local';}catch{return 'local';}};
/** What full screen shows: the animated orb or Jaeger's avatar. */
type Look='orb'|'avatar';
const LOOK_KEY='jaeger.voice.look',BAR_KEY='jaeger.voice.bar';
const readLook=():Look=>{try{return localStorage.getItem(LOOK_KEY)==='avatar'?'avatar':'orb';}catch{return 'orb';}};
const readBar=():{x:number;y:number}|undefined=>{try{const v=JSON.parse(localStorage.getItem(BAR_KEY)||'null');return v&&Number.isFinite(v.x)&&Number.isFinite(v.y)?v:undefined;}catch{return undefined;}};
/** The call bar is draggable on desktop; on phones it stays pinned near the top. */
const canDrag=()=>typeof window!=='undefined'&&window.matchMedia?.('(min-width: 700px) and (pointer: fine)').matches;

type Sight='camera'|'screen';
/** One JPEG frame from a live video element, longest edge capped. */
const grabFrame=(video:HTMLVideoElement,edge=768):string|undefined=>{
 const w=video.videoWidth,h=video.videoHeight;if(!w||!h)return undefined;
 const k=Math.min(1,edge/Math.max(w,h)),c=document.createElement('canvas');c.width=Math.round(w*k);c.height=Math.round(h*k);
 c.getContext('2d')?.drawImage(video,0,0,c.width,c.height);return c.toDataURL('image/jpeg',0.82);
};
/** Ask the local VISION model about a frame (never a cloud service). */
async function describeFrame(image:string,question:string):Promise<string|undefined>{
 const ask=sendJson<{ok?:boolean;answer?:string}>('POST','/api/jaeger/vision/describe',{image_base64:image,question:`The user is talking to you while showing this. They said: "${question}". Describe what is relevant to that in at most three sentences; read any visible text that matters.`});
 const timeout=new Promise<undefined>(r=>window.setTimeout(()=>r(undefined),15000));
 try{const res=await Promise.race([ask,timeout]);return res?.ok&&res.answer?res.answer:undefined;}catch{return undefined;}
}

/**
 * Live voice over a WebRTC call to Jaeger's realtime voice service. It opens as a
 * compact floating call bar over the chat (avatar, live level, mute, settings,
 * hang up) so the conversation stays visible and voice turns land in the chat as
 * normal messages; expanding (or tapping the avatar) goes full screen with the
 * animated orb or Jaeger's avatar, captions, and the camera / screen buttons. Talk naturally; Smart Turn decides
 * when you're done, and speaking (or tapping the orb) interrupts Jaeger.
 *
 * Local engine: every utterance is a normal turn in this chat (same session,
 * history, tools and autonomy); the reply streams back and is spoken sentence by
 * sentence. Gemini Live engine: Gemini talks directly, hands real work to
 * Jaeger through ``ask_jaeger`` (a normal turn here), and both sides of the
 * conversation are saved to this chat.
 *
 * Camera / screen (local engine): frames stay on this Mac. At the end of each
 * utterance one frame goes to Jaeger's VISION-certified local model and its
 * description rides along with the words. With Gemini Live the camera is off,
 * because that would stream video to Google and cloud vision is off by default.
 */
export function VoiceMode({onTranscript,reply,outcome,busy,disabled,primary=false,onOpenChange,history,onSaveTranscript,onClosed}:{
 onTranscript(text:string,opts?:{full?:boolean}):Promise<boolean>; reply?:SpokenReply; outcome?:{id:string;state:string}; busy:boolean; disabled?:boolean; primary?:boolean;
 onOpenChange?:(open:boolean)=>void; history?:()=>{role:string;content:string}[];
 onSaveTranscript?:(role:'user'|'assistant',text:string,engine:VoiceEngine,interrupted?:boolean)=>Promise<unknown>|void; onClosed?:(changed:boolean)=>void;
}){
 const [open,setOpen]=useState(false),[phase,setPhase]=useState<Phase>('connecting'),[engine,setEngine]=useState<VoiceEngine>(readEngine);
 const [you,setYou]=useState(''),[bot,setBot]=useState(''),[error,setError]=useState(''),[muted,setMuted]=useState(false),[latency,setLatency]=useState<number>();
 const [geminiReady,setGeminiReady]=useState<boolean|undefined>(undefined);
 const [expanded,setExpanded]=useState(false),[settings,setSettings]=useState(false),[look,setLook]=useState<Look>(readLook),[barPos,setBarPos]=useState(readBar);
 const bar=useRef<HTMLDivElement>(null),drag=useRef<{dx:number;dy:number;id:number}|undefined>(undefined);
 const [audio]=useAudioPreferences();
 const rtc=useRef<RealtimeVoice|undefined>(undefined),orb=useRef<HTMLButtonElement>(null),frame=useRef(0),session=useRef(0);
 const submit=useRef(onTranscript),save=useRef(onSaveTranscript);submit.current=onTranscript;save.current=onSaveTranscript;
 const phaseRef=useRef<Phase>('connecting');const setP=(p:Phase)=>{phaseRef.current=p;setPhase(p);};
 const waiting=useRef(false),streamId=useRef<string|undefined>(undefined),streamSpoken=useRef(''),streamFinal=useRef(true),lastReply=useRef<string|undefined>(undefined),baselineOutcome=useRef('');
 const finalAt=useRef(0),turnMs=useRef(0),firstAudio=useRef(true),toolCall=useRef<string|undefined>(undefined),saved=useRef(false),engineRef=useRef(engine),mutedRef=useRef(false);
 engineRef.current=engine;mutedRef.current=muted;
 const [sight,setSight]=useState<Sight|undefined>(),sightStream=useRef<MediaStream|undefined>(undefined),sightVideo=useRef<HTMLVideoElement>(null),sightRef=useRef<Sight|undefined>(undefined);sightRef.current=sight;
 const stopSight=()=>{sightStream.current?.getTracks().forEach(t=>t.stop());sightStream.current=undefined;setSight(undefined);};
 const toggleSight=async(kind:Sight)=>{
  if(sight===kind){stopSight();return;}
  if(engineRef.current!=='local'){setError('Camera and screen work with the Jaeger engine. Gemini Live would send video to Google; cloud vision is off.');return;}
  stopSight();
  try{
   const media=kind==='camera'?await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment',width:{ideal:1280}},audio:false}):await navigator.mediaDevices.getDisplayMedia({video:true,audio:false});
   sightStream.current=media;media.getVideoTracks()[0]?.addEventListener('ended',()=>{if(sightStream.current===media)stopSight();});setSight(kind);setError('');
  }catch(e){const name=(e as Error)?.name;if(name!=='NotAllowedError'&&name!=='AbortError')setError(kind==='camera'?'Camera unavailable.':'Screen sharing unavailable.');}
 };
 useEffect(()=>{const v=sightVideo.current;if(v&&sightStream.current&&v.srcObject!==sightStream.current){v.srcObject=sightStream.current;void v.play().catch(()=>{});}},[sight,expanded]);
 /** The words to send, plus what the local vision model sees right now. */
 const withSight=async(text:string):Promise<string>=>{
  const v=sightVideo.current,kind=sightRef.current;if(!kind||!v||engineRef.current!=='local')return text;
  const frame=grabFrame(v);if(!frame)return text;
  const seen=await describeFrame(frame,text);
  return seen?`${text}\n\n[${kind==='camera'?'Camera':'Screen'} view, described by Jaeger's local vision model: ${seen}]`:text;
 };

 const skipReply=()=>{if(streamId.current)lastReply.current=streamId.current;streamFinal.current=true;setBot('');};
 const settle=()=>{if(phaseRef.current==='connecting'||phaseRef.current==='paused')return;setP(mutedRef.current?'paused':waiting.current||toolCall.current?'thinking':'listening');};

 const onMessage=(owner:number)=>(m:ServiceMessage)=>{
  if(owner!==session.current)return;
  switch(m.t){
   case 'ready':setError('');setP(mutedRef.current?'paused':'listening');break;
   case 'user-speaking':
    viaJaeger.current=false;
    if(phaseRef.current==='speaking'||(streamId.current&&!streamFinal.current&&engineRef.current==='local'))skipReply();
    setP('hearing');break;
   case 'user-partial':setYou(m.text);break;
   case 'user-final':{
    setYou(m.text);finalAt.current=performance.now();turnMs.current=m.turnMs||0;firstAudio.current=false;
    baselineOutcome.current=JSON.stringify(outcomeRef.current);waiting.current=true;setBot('');setP('thinking');
    // While a turn is running the words steer it; if it can't take them, they
    // go next, as soon as Jaeger is free.
    const wasBusy=working.current;
    void withSight(m.text).then(t=>submit.current(t)).then(ok=>{if(ok||owner!==session.current)return;if(wasBusy){if(working.current)queued.current.push(m.text);else sendQueued(m.text);return;}waiting.current=false;setError('That wasn’t sent. Its text is in the message box.');settle();});
    break;}
   case 'interrupted':setP('hearing');break;
   // Gemini Live: the local VAD marks the end of speech for the latency readout.
   case 'user-stopped':if(engineRef.current==='gemini'){finalAt.current=performance.now();turnMs.current=m.stopMs||0;firstAudio.current=false;if(phaseRef.current==='hearing')setP('thinking');}break;
   case 'bot-speaking':
    if(m.on){
     if(!firstAudio.current&&finalAt.current){firstAudio.current=true;const ms=Math.round(performance.now()-finalAt.current+turnMs.current);setLatency(ms);window.dispatchEvent(new CustomEvent('jaeger:voice-latency',{detail:{speechEndToFirstAudioMs:ms,engine:engineRef.current}}));}
     setP('speaking');
    }else settle();
    break;
   case 'bot-text':setBot(m.text);break;
   case 'transcript':
    if(m.text.trim()&&!viaJaeger.current){saved.current=true;void Promise.resolve(save.current?.(m.role,m.text,engineRef.current,m.interrupted)).catch(()=>{});}
    break;
   case 'tool':
    // Gemini hands real work to full Jaeger (not the fast voice lane); that turn
    // records the request and answer in the chat, so this exchange's transcript is skipped.
    toolCall.current=m.id;waiting.current=true;viaJaeger.current=true;setBot('Working on it in Jaeger…');
    void submit.current(m.request,{full:true}).then(ok=>{if(!ok&&toolCall.current===m.id){rtc.current?.send({t:'tool-result',id:m.id,text:'Jaeger could not start that request right now.'});toolCall.current=undefined;waiting.current=false;}});
    break;
   case 'error':setError(m.message);break;
  }
 };
 const outcomeRef=useRef(outcome);outcomeRef.current=outcome;
 const viaJaeger=useRef(false);const working=useRef(busy);working.current=busy;const queued=useRef<string[]>([]);
 // A follow-up that arrived mid-turn: it becomes the next turn, and its reply
 // is spoken after whatever is playing now.
 const replyRef=useRef(reply);replyRef.current=reply;const queuedAfter=useRef<string|undefined>(undefined);
 const sendQueued=(text:string)=>{waiting.current=true;queuedAfter.current=replyRef.current?.id;finalAt.current=0;baselineOutcome.current=JSON.stringify(outcomeRef.current);if(phaseRef.current!=='speaking')setP('thinking');void submit.current(text).then(ok=>{if(!ok){waiting.current=false;setError('That wasn’t sent. Its text is in the message box.');settle();}});};
 useEffect(()=>{if(!open||busy||!queued.current.length)return;sendQueued(queued.current.splice(0).join(' '));},[open,busy]);

 const animate=()=>{
  const r=rtc.current;
  if(r){const level=(phaseRef.current==='speaking'?r.botLevel():mutedRef.current?0:r.micLevel()).toFixed(3);
   orb.current?.style.setProperty('--jg-voice-level',level);bar.current?.style.setProperty('--jg-voice-level',level);}
  frame.current=requestAnimationFrame(animate);
 };

 const connect=async(which:VoiceEngine)=>{
  rtc.current?.close();const owner=++session.current;
  setP('connecting');setError('');setYou('');setBot('');setLatency(undefined);waiting.current=false;toolCall.current=undefined;
  lastReply.current=reply?.id;streamId.current=undefined;streamFinal.current=true;
  const voice=new RealtimeVoice(onMessage(owner),(state,detail)=>{if(owner!==session.current)return;if(state==='failed'){setError(detail||'Voice connection failed.');setP('paused');}});
  rtc.current=voice;
  try{
   await voice.connect({engine:which,inputId:audio.inputId||undefined,outputId:audio.outputId||undefined,history:which==='gemini'?history?.():undefined});
   if(mutedRef.current)voice.setMuted(true);
  }catch(e){if(owner===session.current){setError(String((e as Error).message||e));setP('paused');}}
 };

 const start=()=>{
  setOpen(true);setExpanded(false);setSettings(false);onOpenChange?.(true);saved.current=false;
  cancelAnimationFrame(frame.current);frame.current=requestAnimationFrame(animate);
  void connect(engine);
  void realtimeStatus().then(s=>{setGeminiReady(Boolean(s.engines?.gemini?.ready));if(!s.ok)setError(s.error||'Realtime voice service is not running.');});
 };
 const close=()=>{
  session.current++;rtc.current?.close();rtc.current=undefined;cancelAnimationFrame(frame.current);
  stopSight();setOpen(false);setExpanded(false);setSettings(false);onOpenChange?.(false);setMuted(false);waiting.current=false;toolCall.current=undefined;
  onClosed?.(saved.current);saved.current=false;
 };
 useEffect(()=>()=>{session.current++;rtc.current?.close();cancelAnimationFrame(frame.current);sightStream.current?.getTracks().forEach(t=>t.stop());},[]);
 useEffect(()=>{if(!open)return;const k=(e:KeyboardEvent)=>{if(e.key!=='Escape')return;if(settings)setSettings(false);else if(expanded)setExpanded(false);else close();};window.addEventListener('keydown',k);return()=>window.removeEventListener('keydown',k);},[open,expanded,settings]);

 const switchEngine=(next:VoiceEngine)=>{
  if(next===engine)return;
  if(next==='gemini'&&geminiReady===false){setError('Gemini Live needs a Google AI Studio key (GEMINI_API_KEY in ~/.jaeger/secrets.env).');return;}
  try{localStorage.setItem(ENGINE_KEY,next);}catch{/* private mode */}
  if(next!=='local')stopSight();setEngine(next);if(open)void connect(next);
 };
 const toggleMute=()=>{const next=!muted;setMuted(next);mutedRef.current=next;rtc.current?.setMuted(next);setP(next?'paused':waiting.current||toolCall.current?'thinking':'listening');};
 const tapOrb=()=>{
  if(phaseRef.current==='speaking'){rtc.current?.send({t:'stop'});skipReply();setP('listening');return;}
  if(muted){toggleMute();return;}
  if(error&&phaseRef.current==='paused')void connect(engine);
 };

 // Local engine: speak the reply while it streams, whole sentences at a time.
 // Gemini engine: a finished reply to ask_jaeger goes back to Gemini instead.
 useEffect(()=>{
  if(!open||!reply?.text||reply.id===lastReply.current||!waiting.current)return;
  const final=reply.final!==false&&!busy;
  if(toolCall.current){
   if(final){rtc.current?.send({t:'tool-result',id:toolCall.current,text:reply.text});toolCall.current=undefined;waiting.current=false;lastReply.current=reply.id;setBot('');window.setTimeout(()=>{if(phaseRef.current==='thinking')settle();},4000);}
   return;
  }
  if(engineRef.current!=='local')return;
  if(streamId.current!==reply.id){streamId.current=reply.id;streamSpoken.current='';streamFinal.current=false;}
  const ready=speakablePrefix(reply.text,final);
  if(ready.startsWith(streamSpoken.current)){
   const fresh=ready.slice(streamSpoken.current.length);
   if(fresh.trim()){
    const first=!streamSpoken.current;streamSpoken.current=ready;
    for(const chunk of speechSentences(fresh,first))rtc.current?.send({t:'speak',text:chunk});
    setBot(ready.trim());
   }
  }
  // The reply finishing here may be the one a queued follow-up waits behind.
  if(final){lastReply.current=reply.id;streamFinal.current=true;if(reply.id===queuedAfter.current)return;queuedAfter.current=undefined;waiting.current=false;
   // Spoken audio is on its way: stay on Thinking until it starts (bot-speaking).
   if(phaseRef.current==='thinking'){if(streamSpoken.current.trim())window.setTimeout(()=>{if(phaseRef.current==='thinking')settle();},4000);else settle();}}
 },[open,reply?.id,reply?.text,reply?.final,busy]);

 useEffect(()=>{
  if(open&&waiting.current&&!busy&&outcome&&['failed','cancelled','unknown'].includes(outcome.state)&&JSON.stringify(outcome)!==baselineOutcome.current){
   waiting.current=false;if(toolCall.current){rtc.current?.send({t:'tool-result',id:toolCall.current,text:`The request ended as ${outcome.state}.`});toolCall.current=undefined;}
   setError(`That turn ended as ${outcome.state}. Check the chat.`);settle();
  }
 },[open,outcome?.id,outcome?.state,busy]);

 const pickLook=(next:Look)=>{setLook(next);try{localStorage.setItem(LOOK_KEY,next);}catch{/* private mode */}};
 const clampBar=(x:number,y:number)=>{const el=bar.current,w=el?.offsetWidth||360,h=el?.offsetHeight||64;return {x:Math.max(8,Math.min(window.innerWidth-w-8,x)),y:Math.max(8,Math.min(window.innerHeight-h-8,y))};};
 const startDrag=(e:RPointerEvent<HTMLDivElement>)=>{
  if(!canDrag()||(e.target as HTMLElement).closest('button,[role="menu"]'))return;
  const r=bar.current?.getBoundingClientRect();if(!r)return;
  drag.current={dx:e.clientX-r.left,dy:e.clientY-r.top,id:e.pointerId};bar.current?.setPointerCapture(e.pointerId);e.preventDefault();
 };
 const moveDrag=(e:RPointerEvent<HTMLDivElement>)=>{const d=drag.current;if(!d||d.id!==e.pointerId)return;setBarPos(clampBar(e.clientX-d.dx,e.clientY-d.dy));};
 const endDrag=(e:RPointerEvent<HTMLDivElement>)=>{const d=drag.current;if(!d||d.id!==e.pointerId)return;drag.current=undefined;bar.current?.releasePointerCapture(e.pointerId);setBarPos(p=>{if(p)try{localStorage.setItem(BAR_KEY,JSON.stringify(p));}catch{/* private mode */}return p;});};
 // Keep a dragged bar on screen when the window shrinks.
 useEffect(()=>{if(!open||!barPos)return;const fit=()=>setBarPos(p=>p&&clampBar(p.x,p.y));window.addEventListener('resize',fit);return()=>window.removeEventListener('resize',fit);},[open,Boolean(barPos)]);
 const avatarState=(phase==='thinking'?'thinking':phase==='speaking'?'streaming':'idle') as 'thinking'|'streaming'|'idle';
 const engineName=engine==='gemini'?'Gemini Live':'Jaeger';
 const settingsMenu=settings&&<div className="jg-vsettings" role="menu" aria-label="Voice settings">
  <p className="jg-vsettings__label">Voice engine</p>
  <div className="jg-vmode__engines" role="radiogroup" aria-label="Voice engine">
   <button type="button" role="radio" aria-checked={engine==='local'} onClick={()=>switchEngine('local')}>Jaeger</button>
   <button type="button" role="radio" aria-checked={engine==='gemini'} aria-disabled={geminiReady===false} title={geminiReady===false?'Needs a Google AI Studio key':'Gemini Live (Google, cloud)'} onClick={()=>switchEngine('gemini')}>Gemini Live{geminiReady===false&&<small> · needs key</small>}</button>
  </div>
  <p className="jg-vsettings__label">Full screen shows</p>
  <div className="jg-vmode__engines" role="radiogroup" aria-label="Full screen shows">
   <button type="button" role="radio" aria-checked={look==='orb'} onClick={()=>pickLook('orb')}>Orb</button>
   <button type="button" role="radio" aria-checked={look==='avatar'} onClick={()=>pickLook('avatar')}>Jaeger avatar</button>
  </div>
  {latency!==undefined&&<p className="jg-vsettings__note">Last reply started {(latency/1000).toFixed(1)} s after you stopped talking.</p>}
 </div>;
 const status=error&&phase==='paused'?'Voice paused':phase==='connecting'?'Connecting…':phase==='paused'?'Microphone off':phase==='hearing'?'Listening…':phase==='thinking'?(toolCall.current?'Jaeger is working…':'Thinking…'):phase==='speaking'?'Tap or speak to interrupt':'Listening';
 return <><button type="button" className={primary?'jg-send jg-send--speak jg-voice-mode__trigger':'jg-composer__icon jg-voice-mode__trigger'} aria-label="Start voice mode" title="Voice mode" aria-expanded={open} disabled={disabled} onClick={()=>{if(!open)start();}}><WaveIcon/></button>
  {open&&createPortal(<>
   {!expanded&&<div ref={bar} className="jg-vcall" role="dialog" aria-label="Voice call" data-phase={phase} data-placed={barPos&&canDrag()?true:undefined}
     style={barPos&&canDrag()?{left:barPos.x,top:barPos.y}:undefined} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
    <span className="jg-vcall__grip" aria-hidden="true"/>
    <button type="button" className="jg-vcall__avatar" aria-label="Open full screen voice" title="Full screen" onClick={()=>{setSettings(false);setExpanded(true);}}>
     <AgentAvatar id="native:jaeger" name="Jaeger" size={40} state={avatarState}/>
    </button>
    <div className="jg-vcall__info"><strong>{engineName}</strong><span role="status">{error&&phase==='paused'?error:status}</span></div>
    <span className="jg-vcall__level" aria-hidden="true"><i/><i/><i/><i/></span>
    <button type="button" className="jg-vcall__btn" aria-pressed={muted} data-active={muted} aria-label={muted?'Unmute microphone':'Mute microphone'} title={muted?'Unmute':'Mute'} onClick={toggleMute}><MicIcon/></button>
    <button type="button" className="jg-vcall__btn" aria-expanded={settings} aria-label="Voice settings" title="Settings" onClick={()=>setSettings(v=>!v)}><GearIcon/></button>
    <button type="button" className="jg-vcall__btn" aria-label="Full screen" title="Full screen" onClick={()=>{setSettings(false);setExpanded(true);}}><ExpandIcon/></button>
    <button type="button" className="jg-vcall__btn jg-vcall__end" aria-label="End voice" title="Hang up" onClick={close}><HangUpIcon/></button>
    {settingsMenu}
    {sight&&<video ref={sightVideo} className="jg-vcall__sight" muted playsInline autoPlay aria-hidden="true"/>}
   </div>}
   {expanded&&<section className="jg-vmode" role="dialog" aria-modal="true" aria-label="Voice mode" data-phase={phase}>
   <header className="jg-vmode__top">
    <button type="button" className="jg-vmode__corner" aria-label="Back to call bar" title="Back to chat" onClick={()=>{setSettings(false);setExpanded(false);}}><CollapseIcon/></button>
    <div className="jg-vmode__engines" role="radiogroup" aria-label="Voice engine">
     <button type="button" role="radio" aria-checked={engine==='local'} onClick={()=>switchEngine('local')}>Jaeger</button>
     <button type="button" role="radio" aria-checked={engine==='gemini'} aria-disabled={geminiReady===false} title={geminiReady===false?'Needs a Google AI Studio key':'Gemini Live (Google, cloud)'} onClick={()=>switchEngine('gemini')}>Gemini Live{geminiReady===false&&<small> · needs key</small>}</button>
    </div>
    <div className="jg-vmode__right">
     {latency!==undefined&&<span className="jg-vmode__latency" title="From the end of your speech to Jaeger's first audio">{(latency/1000).toFixed(1)} s</span>}
     <button type="button" className="jg-vmode__corner" aria-expanded={settings} aria-label="Voice settings" title="Settings" onClick={()=>setSettings(v=>!v)}><GearIcon/></button>
    </div>
    {settingsMenu}
   </header>
   {sight&&<div className="jg-vmode__sight" data-kind={sight}><video ref={sightVideo} muted playsInline autoPlay aria-label={sight==='camera'?'Camera preview':'Shared screen preview'}/><span>{sight==='camera'?'Camera':'Screen'} · seen on this Mac only</span></div>}
   {look==='avatar'
    ?<button type="button" ref={orb} className="jg-vmode__orb jg-vmode__orb--avatar" data-phase={phase} aria-label={phase==='speaking'?'Interrupt Jaeger':muted?'Unmute microphone':'Voice activity'} onClick={tapOrb}><ClipAvatar size={220} state={phase==='thinking'?'working':phase==='connecting'?'connecting':'idle'}/></button>
    :<button type="button" ref={orb} className="jg-vmode__orb" data-phase={phase} aria-label={phase==='speaking'?'Interrupt Jaeger':muted?'Unmute microphone':'Voice activity'} onClick={tapOrb}><span/></button>}
   <p className="jg-vmode__status" role="status">{status}</p>
   <div className="jg-vmode__captions" aria-live="polite">
    {you&&<p className="jg-vmode__you">{you}</p>}
    {bot&&<p className="jg-vmode__bot">{bot.length>320?'…'+bot.slice(-320):bot}</p>}
    {error&&<p className="jg-vmode__error" role="alert">{error}</p>}
   </div>
   <footer className="jg-vmode__controls">
    <button type="button" className="jg-vmode__control" aria-pressed={sight==='camera'} data-active={sight==='camera'} aria-disabled={engine!=='local'} aria-label={sight==='camera'?'Turn camera off':'Turn camera on'} title={engine==='local'?'Show Jaeger your camera (local vision, stays on this Mac)':'Camera needs the Jaeger engine; cloud vision is off'} onClick={()=>void toggleSight('camera')}><CameraIcon/></button>
    <button type="button" className="jg-vmode__control" aria-pressed={muted} aria-label={muted?'Unmute microphone':'Mute microphone'} data-active={muted} onClick={toggleMute}><MicIcon/></button>
    {typeof navigator!=='undefined'&&'getDisplayMedia' in (navigator.mediaDevices||{})&&<button type="button" className="jg-vmode__control" aria-pressed={sight==='screen'} data-active={sight==='screen'} aria-disabled={engine!=='local'} aria-label={sight==='screen'?'Stop sharing screen':'Share screen'} title={engine==='local'?'Show Jaeger your screen (local vision, stays on this Mac)':'Screen sharing needs the Jaeger engine; cloud vision is off'} onClick={()=>void toggleSight('screen')}><ScreenIcon/></button>}
    <button type="button" className="jg-vmode__control jg-vmode__end" aria-label="End voice mode" onClick={close}><HangUpIcon/></button>
   </footer>
  </section>}
  </>,document.body)}
 </>;
}
