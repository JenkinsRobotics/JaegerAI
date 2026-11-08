import { useEffect, useRef, useState } from 'react';
import { createVoiceIO } from '../chat/voiceIO';
import type { SpeechCapability, SpeechDevices, VoiceIO } from '../chat/webSpeech';
import { useAudioPreferences } from './audioPreferences';
/** Live platform capabilities, with the same selection used by the chat session. */
export function AudioSettingsPanel({io:supplied}:{io?:VoiceIO}){
 const io=useRef(supplied??createVoiceIO()).current;
 const [prefs,save]=useAudioPreferences(),[devices,setDevices]=useState<SpeechDevices>({microphones:[],speakers:[]}),[caps,setCaps]=useState<SpeechCapability>(),[error,setError]=useState('');
 const refresh=async()=>{setError('');try{const [capability,found]=await Promise.all([io.capability(),io.devices()]);setCaps(capability);setDevices(found);}catch(e){setError(String((e as Error).message||e));}};
 useEffect(()=>{void refresh();return()=>io.release?.();},[]);
 const change=(key:'inputId'|'outputId',id:string)=>{try{save({...prefs,[key]:id});setError('');}catch(e){setError(String((e as Error).message||e));}};
 return <div>
  <div className="jg-sheet__row"><span className="jg-sheet__row-label">Voice session<span className="jg-sheet__hint">Start voice in chat, speak normally, and pause for a reply. No wake phrase. End voice releases the microphone.</span></span><span className="jg-sheet__value">{caps ? caps.transcription&&caps.speech?'Speech services available':'Unavailable':'Checking…'}</span></div>
  {([['Microphone','inputId',devices.microphones],['Speaker','outputId',devices.speakers]] as const).map(([label,key,rows])=><div className="jg-sheet__row" key={key}><label className="jg-sheet__row-label" htmlFor={`audio-${key}`}>{label}</label><select id={`audio-${key}`} aria-label={`Voice ${label.toLowerCase()}`} value={prefs[key]} onChange={e=>change(key,e.target.value)}><option value="">System default</option>{prefs[key]&&!rows.some(row=>row.deviceId===prefs[key])&&<option value={prefs[key]} disabled>Saved device unavailable</option>}{rows.filter(row=>row.deviceId!=='default').map((row,index)=><option key={row.deviceId} value={row.deviceId}>{row.label||`${label} ${index+1}`}</option>)}</select></div>)}
  <p className="jg-sheet__hint">Selections apply to Jaeger on this device. System default follows the operating system’s current audio route. Device names appear after microphone access is allowed.</p>
  <p className="jg-sheet__hint">During a reply, use “Interrupt and speak” to take your turn.</p>
  {caps?.reason&&(!caps.transcription||!caps.speech)&&<p role="status">{caps.reason}</p>}{error&&<p role="alert">{error}</p>}
  <button type="button" className="jg-u-btn" onClick={()=>void refresh()}>Refresh audio devices</button>
 </div>;
}
