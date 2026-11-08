import { useEffect, useRef, useState } from 'react';
import { BrowserVoiceIO, type VoiceIO, type SpeechDevices } from './webSpeech';
import { WaveIcon } from '../icons';
import './voiceMode.css';
import { nativeBridge } from '../platform/native';
import { NativeVoiceIO } from './nativeVoiceIO';
export interface SpokenReply { id: string; text: string }
type Phase = 'off'|'checking'|'starting'|'listening'|'waiting'|'preparing'|'speaking'|'paused';
/** A client audio loop. Turn execution and history remain in the parent chat/Gateway. */
export function VoiceMode({ onTranscript, reply, outcome, busy, disabled, primary = false, onOpenChange, io: supplied }: { onTranscript(text:string):Promise<boolean>; reply?:SpokenReply; outcome?:{id:string;state:string}; busy:boolean; disabled?:boolean; primary?:boolean; onOpenChange?:(open:boolean)=>void; io?:VoiceIO }) {
  const io=useRef<VoiceIO>(supplied ?? (nativeBridge()?new NativeVoiceIO():new BrowserVoiceIO())).current;
  const [phase,setPhase]=useState<Phase>('off'),[error,setError]=useState(''),[level,setLevel]=useState(0),[heard,setHeard]=useState('');
  const [devices,setDevices]=useState<SpeechDevices>({microphones:[],speakers:[]});
  const [input,setInput]=useState(''),[output,setOutput]=useState('');
  const ready=useRef(false);
  const controller=useRef<AbortController | undefined>(undefined),enabled=useRef(false),stopCapture=useRef<(()=>void) | undefined>(undefined),generation=useRef(0),lastReply=useRef<string | undefined>(undefined);
  const inputRef=useRef(input),outputRef=useRef(output),transcript=useRef(onTranscript),currentReply=useRef(reply),currentOutcome=useRef(outcome),baselineOutcome=useRef('');
  inputRef.current=input;outputRef.current=output;transcript.current=onTranscript;currentReply.current=reply;currentOutcome.current=outcome;
  const cancelAudio=()=>{generation.current++;controller.current?.abort();controller.current=undefined;stopCapture.current=undefined;};
  const close=()=>{enabled.current=false;cancelAudio();setPhase('off');setLevel(0);setError('');io.release?.();onOpenChange?.(false);};
  useEffect(()=>()=>{enabled.current=false;cancelAudio();io.release?.();},[]);
  const refreshDevices=()=>void io.devices().then(setDevices).catch(()=>{});
  const listen=async()=>{
    cancelAudio();baselineOutcome.current=JSON.stringify(currentOutcome.current);const owner=generation.current,abort=new AbortController();controller.current=abort;setError('');setPhase('starting');
    try {
      const text=await io.capture(abort.signal,inputRef.current,setLevel,stop=>{if(owner===generation.current && enabled.current){stopCapture.current=stop;setPhase('listening');refreshDevices();}});
      if(owner!==generation.current || !enabled.current)return;
      stopCapture.current=undefined;setHeard(text);setPhase('waiting');if(!await transcript.current(text))throw Error('Voice message was not sent. Its transcript is preserved in the message field.');
    }catch(e){if(owner===generation.current && enabled.current){setError(String((e as Error).message||e));setPhase('paused');refreshDevices();}}
  };
  const start=async()=>{
    enabled.current=true;ready.current=false;onOpenChange?.(true);cancelAudio();const owner=generation.current;setPhase('checking');setError('');lastReply.current=currentReply.current?.id;
    try {let startupError:unknown;const preparation=io.prepare?.().catch(error=>{startupError=error;});const caps=await io.capability();if(owner!==generation.current || !enabled.current)return;if(!caps.transcription || !caps.speech)throw Error(caps.reason || 'Voice services are unavailable.');await preparation;if(startupError)throw startupError;if(owner!==generation.current || !enabled.current)return;ready.current=true;await listen();}
    catch(e){if(owner===generation.current && enabled.current){setError(String((e as Error).message||e));setPhase('paused');}}
  };
  const play = (text:string, resume=true) => {
    cancelAudio();const owner=generation.current,abort=new AbortController();controller.current=abort;setPhase('preparing');setError('');
    void io.speak(text,abort.signal,outputRef.current,()=>{if(owner===generation.current && enabled.current)setPhase('speaking');}).then(()=>{if(owner===generation.current && enabled.current){if(resume)void listen();else setPhase('paused');}},e=>{if(owner===generation.current && enabled.current){setError(String((e as Error).message||e));setPhase('paused');}});
  };
  useEffect(()=>{
    if(!enabled.current || phase!=='waiting' || !reply?.text || reply.id===lastReply.current || busy)return;
    lastReply.current=reply.id;play(reply.text);
  },[reply?.id,reply?.text,busy,phase]);
  useEffect(()=>{if(enabled.current && phase==='waiting' && !busy && outcome && ['failed','cancelled','unknown'].includes(outcome.state) && JSON.stringify(outcome)!==baselineOutcome.current){setPhase('paused');setError(`The chat turn ended as ${outcome.state}. Check the conversation before sending another message.`);}},[outcome?.id,outcome?.state,busy,phase]);
  return <><button type="button" className={primary?"jg-send jg-send--speak jg-voice-mode__trigger":"jg-composer__icon jg-voice-mode__trigger"} aria-label={phase==='off'?'Start voice mode':'Show voice mode'} title="Voice mode" aria-expanded={phase!=='off'} disabled={disabled} onClick={()=>phase==='off'?void start():undefined}><WaveIcon/></button>
    {phase!=='off' && <section className="jg-voice-mode" role="dialog" aria-label="Voice mode"><header><strong>Voice mode</strong><button type="button" onClick={close} aria-label="Stop voice mode">×</button></header>
      <div className="jg-voice-mode__meter" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level*100)}><span style={{transform:`scaleX(${Math.max(0.03,level)})`}}/></div>
      <p role="status">{phase==='checking'?'Checking voice services…':phase==='starting'?'Starting microphone · allow access if prompted':phase==='listening'?'Listening · pause to send':phase==='waiting'?'Jaeger is working…':phase==='preparing'?'Preparing speech…':phase==='speaking'?'Jaeger is speaking':error?'Voice paused':'Ready to listen'}</p>
      {heard && <p className="jg-voice-mode__heard">You: {heard}</p>}{error && <p role="alert">{error}</p>}
      {devices.microphones.length>0 && <label>Microphone<select aria-label="Voice microphone" value={input} onChange={e=>{setInput(e.target.value);inputRef.current=e.target.value;if(phase==='listening')void listen();}}><option value="">System default</option>{devices.microphones.filter(device=>device.deviceId!=='default').map((device,index)=><option key={device.deviceId} value={device.deviceId}>{device.label || `Microphone ${index+1}`}</option>)}</select></label>}
      {devices.speakers.length>0 && <label>Speaker<select aria-label="Voice speaker" value={output} onChange={e=>setOutput(e.target.value)}><option value="">System default</option>{devices.speakers.filter(device=>device.deviceId!=='default').map((device,index)=><option key={device.deviceId} value={device.deviceId}>{device.label || `Speaker ${index+1}`}</option>)}</select></label>}
      <div className="jg-voice-mode__actions">{phase==='listening'?<button type="button" onClick={()=>stopCapture.current?.()}>Send voice message</button>:<button type="button" disabled={phase==='checking' || phase==='starting'} onClick={()=>ready.current?void listen():void start()}>{(phase==='speaking' || phase==='preparing')?'Interrupt and speak':'Speak now'}</button>}<button type="button" disabled={phase==='checking' || phase==='preparing' || phase==='speaking'} onClick={()=>play('Jaeger voice is connected.',false)}>Test speaker</button><button type="button" onClick={close}>End voice</button></div>
    </section>}
  </>;
}
