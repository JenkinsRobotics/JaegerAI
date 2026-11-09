import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createVoiceIO } from '../chat/voiceIO';
import type { SpeechCapability, SpeechDevices, VoiceIO } from '../chat/webSpeech';
import { useAudioPreferences } from './audioPreferences';
import './audioSettings.css';
/** Live platform capabilities, with the same selection used by the chat session. */
export function AudioSettingsPanel({io:supplied}:{io?:VoiceIO}){
 const io=useMemo(()=>supplied??createVoiceIO(),[supplied]);
 const generation=useRef(0);
 const [status,setStatus]=useState<'loading'|'ready'|'error'>('loading');
 const [prefs,save]=useAudioPreferences(),[devices,setDevices]=useState<SpeechDevices>({microphones:[],speakers:[]}),[caps,setCaps]=useState<SpeechCapability>(),[error,setError]=useState(''),[saveError,setSaveError]=useState('');
 const refresh=useCallback(async()=>{
  const current=++generation.current;
  setStatus('loading');setCaps(undefined);setDevices({microphones:[],speakers:[]});setError('');
  try{
   const [capability,found]=await Promise.all([io.capability(),io.devices()]);
   if(current!==generation.current)return;
   setCaps(capability);setDevices(found);setStatus('ready');
  }catch(e){if(current===generation.current){setStatus('error');setError(String((e as Error).message||e));}}
 },[io]);
 useEffect(()=>{void refresh();return()=>{++generation.current;io.release?.();};},[io,refresh]);
 const change=(key:'inputId'|'outputId',id:string)=>{try{save({...prefs,[key]:id});setSaveError('');}catch(e){setSaveError(String((e as Error).message||e));}};
 return <div className="jg-audio-settings">
  <div className="jg-sheet__row"><span className="jg-sheet__row-label">Voice session<span className="jg-sheet__hint">Start voice in chat, speak normally, and pause for a reply. No wake phrase. End voice releases the microphone.</span></span><span className="jg-sheet__value">{status==='loading'?'Checking…':status==='error'?'Check failed':caps?.transcription&&caps.speech?'Speech services available':'Unavailable'}</span></div>
  {([['Microphone','inputId',devices.microphones],['Speaker','outputId',devices.speakers]] as const).map(([label,key,rows])=><div className="jg-sheet__row" key={key}><label className="jg-sheet__row-label" htmlFor={`audio-${key}`}>{label}</label><select id={`audio-${key}`} aria-label={`Voice ${label.toLowerCase()}`} value={prefs[key]} onChange={e=>change(key,e.target.value)}><option value="">System default</option>{prefs[key]&&!rows.some(row=>row.deviceId===prefs[key])&&<option value={prefs[key]} disabled>{status==='ready'?'Saved device unavailable':'Saved device (not verified)'}</option>}{rows.filter(row=>row.deviceId!=='default').map((row,index)=><option key={row.deviceId} value={row.deviceId}>{row.label||`${label} ${index+1}`}</option>)}</select></div>)}
  {status==='ready'&&!devices.microphones.length&&<p role="status">No microphones listed.</p>}
  {status==='ready'&&!devices.speakers.length&&<p role="status">No selectable speakers listed. Use the system default audio route.</p>}
  <p className="jg-sheet__hint">Selections apply to Jaeger on this device. System default follows the operating system’s current audio route. Device names appear after microphone access is allowed.</p>
  <p className="jg-sheet__hint">During a reply, use “Interrupt and speak” to take your turn.</p>
  {caps?.reason&&(!caps.transcription||!caps.speech)&&<p role="status">{caps.reason}</p>}{error&&<p role="alert">{error}</p>}{saveError&&<p role="alert">{saveError}</p>}
  <button type="button" className="jg-u-btn" onClick={()=>void refresh()}>Refresh audio devices</button>
 </div>;
}
