import { useEffect, useRef, useState } from 'react';
import type { VoiceIO, SpeechDevices } from './webSpeech';
import { WaveIcon } from '../icons';
import './voiceMode.css';
import { createVoiceIO } from './voiceIO';
import { useAudioPreferences } from '../settings/audioPreferences';
export interface SpokenReply { id:string; text:string }
/** Audio input, playback and Gateway work have independent lifetimes. */
export function VoiceMode({onTranscript,reply,outcome,busy,disabled,primary=false,onOpenChange,io:supplied}:{onTranscript(text:string):Promise<boolean>;reply?:SpokenReply;outcome?:{id:string;state:string};busy:boolean;disabled?:boolean;primary?:boolean;onOpenChange?:(open:boolean)=>void;io?:VoiceIO}){
 const io=useRef<VoiceIO>(supplied??createVoiceIO()).current;
 const [open,setOpen]=useState(false),[checking,setChecking]=useState(false),[capture,setCapture]=useState<'off'|'starting'|'listening'>('off'),[playback,setPlayback]=useState<'off'|'preparing'|'speaking'>('off');
 const [error,setError]=useState(''),[level,setLevel]=useState(0),[heard,setHeard]=useState(''),[awaiting,setAwaiting]=useState(false);
 const [devices,setDevices]=useState<SpeechDevices>({microphones:[],speakers:[]});
 const [audio,saveAudio]=useAudioPreferences();
 const enabled=useRef(false),ready=useRef(false),epoch=useRef(0),captureId=useRef(0),playId=useRef(0);
 const mic=useRef<AbortController|undefined>(undefined),speaker=useRef<AbortController|undefined>(undefined),stopCapture=useRef<(()=>void)|undefined>(undefined);
 const input=useRef(audio.inputId),output=useRef(audio.outputId),submit=useRef(onTranscript),currentReply=useRef(reply),currentOutcome=useRef(outcome),lastReply=useRef<string|undefined>(undefined),baselineOutcome=useRef(''),waiting=useRef(false);
 input.current=audio.inputId;output.current=audio.outputId;submit.current=onTranscript;currentReply.current=reply;currentOutcome.current=outcome;
 const duplex=()=>Boolean(io.fullDuplex && !output.current);
 const wait=(value:boolean)=>{waiting.current=value;setAwaiting(value);};
 const stopMic=()=>{captureId.current++;mic.current?.abort();mic.current=undefined;stopCapture.current=undefined;setCapture('off');setLevel(0);};
 const stopSpeaker=()=>{playId.current++;speaker.current?.abort();speaker.current=undefined;setPlayback('off');};
 const close=()=>{enabled.current=false;epoch.current++;stopMic();stopSpeaker();ready.current=false;setChecking(false);setOpen(false);setError('');wait(false);io.release?.();onOpenChange?.(false);};
 useEffect(()=>()=>{enabled.current=false;epoch.current++;captureId.current++;playId.current++;mic.current?.abort();speaker.current?.abort();io.release?.();},[]);
 const refreshDevices=()=>void io.devices().then(found=>{if(enabled.current)setDevices(found);}).catch(()=>{});
 const listen=async()=>{
  if(!enabled.current || !ready.current || mic.current || (speaker.current && !duplex()))return;
  const owner=++captureId.current,abort=new AbortController();mic.current=abort;setCapture('starting');setError('');
  try{
   const text=await io.capture(abort.signal,input.current,setLevel,stop=>{
    if(owner!==captureId.current || !enabled.current)return;
    stopCapture.current=stop;setCapture('listening');refreshDevices();
   },()=>{
    // AEC capability comes from the live input track. Alternate output routes
    // and adapters without echo cancellation retain explicit interruption.
    if(duplex() && speaker.current){stopSpeaker();setError('Reply interrupted. The full response remains in chat.');}
   });
   if(owner!==captureId.current || !enabled.current)return;
   mic.current=undefined;stopCapture.current=undefined;setCapture('off');setHeard(text);
   baselineOutcome.current=JSON.stringify(currentOutcome.current);wait(true);
   if(!await submit.current(text))throw Error('Voice message was not sent. Its transcript is preserved in the message field.');
   // Work can continue in the Gateway while the same client keeps listening
   // for follow-ups. The parent decides steer versus a new admitted turn.
   if(owner===captureId.current && enabled.current)void listen();
  }catch(e){
   if(owner!==captureId.current || !enabled.current)return;
   mic.current=undefined;stopCapture.current=undefined;setCapture('off');setLevel(0);wait(false);setError(String((e as Error).message||e));refreshDevices();
  }
 };
 const start=async()=>{
  enabled.current=true;ready.current=false;const owner=++epoch.current;setOpen(true);onOpenChange?.(true);setChecking(true);setError('');lastReply.current=currentReply.current?.id;
  try{
   let startupError:unknown;const preparation=io.prepare?.().catch(e=>{startupError=e;});
   const caps=await io.capability();if(owner!==epoch.current || !enabled.current)return;
   if(!caps.transcription || !caps.speech)throw Error(caps.reason||'Voice services are unavailable.');
   await preparation;if(startupError)throw startupError;if(owner!==epoch.current || !enabled.current)return;
   ready.current=true;setChecking(false);void listen();
  }catch(e){if(owner===epoch.current && enabled.current){setChecking(false);setError(String((e as Error).message||e));}}
 };
 const play=(text:string,resume=true)=>{
  stopSpeaker();if(!resume || !duplex())stopMic();
  const owner=++playId.current,abort=new AbortController();speaker.current=abort;setPlayback('preparing');setError('');
  void io.speak(text,abort.signal,output.current,()=>{if(owner===playId.current && enabled.current)setPlayback('speaking');}).then(()=>{
   if(owner!==playId.current || !enabled.current)return;
   speaker.current=undefined;setPlayback('off');if(resume)void listen();
  },e=>{if(owner===playId.current && enabled.current){speaker.current=undefined;setPlayback('off');setError(String((e as Error).message||e));}});
 };
 useEffect(()=>{
  if(!enabled.current || !waiting.current || !reply?.text || reply.id===lastReply.current || busy)return;
  lastReply.current=reply.id;wait(false);play(reply.text);
 },[reply?.id,reply?.text,busy,awaiting]);
 useEffect(()=>{
  if(enabled.current && waiting.current && !busy && outcome && ['failed','cancelled','unknown'].includes(outcome.state) && JSON.stringify(outcome)!==baselineOutcome.current){stopMic();wait(false);setError(`The chat turn ended as ${outcome.state}. Check the conversation before sending another message.`);}
 },[outcome?.id,outcome?.state,busy,awaiting]);
 const selectAudio=(key:'inputId'|'outputId',value:string)=>{
  try{saveAudio({...audio,[key]:value});setError('');if(key==='inputId'){input.current=value;if(mic.current){stopMic();void listen();}}else{output.current=value;if(speaker.current)stopSpeaker();}}
  catch(e){setError(String((e as Error).message||e));}
 };
 const interrupt=()=>{stopSpeaker();if(ready.current)void listen();else void start();};
 const status=checking?'Checking voice services…':playback==='preparing'?'Preparing speech…':playback==='speaking'?(duplex()?'Jaeger is speaking · you can interrupt':'Jaeger is speaking'):capture==='starting'?'Starting microphone · allow access if prompted':capture==='listening'?(busy?'Listening · Jaeger is working':'Listening · pause to send'):awaiting?'Jaeger is working…':error?'Voice paused':'Ready to listen';
 return <><button type="button" className={primary?'jg-send jg-send--speak jg-voice-mode__trigger':'jg-composer__icon jg-voice-mode__trigger'} aria-label={open?'Show voice mode':'Start voice mode'} title="Voice mode" aria-expanded={open} disabled={disabled} onClick={()=>{if(!open)void start();}}><WaveIcon/></button>
  {open&&<section className="jg-voice-mode" role="dialog" aria-label="Voice mode"><header><strong>Voice mode</strong><button type="button" onClick={close} aria-label="Stop voice mode">×</button></header>
   <div className="jg-voice-mode__meter" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level*100)}><span style={{transform:`scaleX(${Math.max(0.03,level)})`}}/></div>
   <p role="status">{status}</p>{heard&&<p className="jg-voice-mode__heard">You: {heard}</p>}{error&&<p role="alert">{error}</p>}
   {devices.microphones.length>0&&<label>Microphone<select aria-label="Voice microphone" value={audio.inputId} onChange={e=>selectAudio('inputId',e.target.value)}><option value="">System default</option>{devices.microphones.filter(d=>d.deviceId!=='default').map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||`Microphone ${i+1}`}</option>)}</select></label>}
   {devices.speakers.length>0&&<label>Speaker<select aria-label="Voice speaker" value={audio.outputId} onChange={e=>selectAudio('outputId',e.target.value)}><option value="">System default</option>{devices.speakers.filter(d=>d.deviceId!=='default').map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||`Speaker ${i+1}`}</option>)}</select></label>}
   <div className="jg-voice-mode__actions">{playback!=='off'?<button type="button" onClick={interrupt}>Interrupt and speak</button>:capture==='listening'?<button type="button" onClick={()=>stopCapture.current?.()}>Send voice message</button>:<button type="button" disabled={checking||capture==='starting'} onClick={()=>ready.current?void listen():void start()}>Speak now</button>}<button type="button" disabled={checking||playback!=='off'} onClick={()=>play('Jaeger voice is connected.',false)}>Test speaker</button><button type="button" onClick={close}>End voice</button></div>
  </section>}
 </>;
}
