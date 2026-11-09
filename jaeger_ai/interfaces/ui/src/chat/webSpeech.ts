import { csrfHeader } from '../api/gateway';
import { getJson, sendJson } from '../unified/webui';
export interface SpeechCapability { transcription: boolean; speech: boolean; reason?: string }
export interface AudioEndpoint { deviceId:string; label:string }
export interface SpeechDevices { microphones: AudioEndpoint[]; speakers: AudioEndpoint[] }
export interface VoiceIO {
  readonly fullDuplex?:boolean;
  prepare?(): Promise<void>;
  release?(): void;
  capability(): Promise<SpeechCapability>;
  devices(): Promise<SpeechDevices>;
  capture(signal: AbortSignal, inputId: string, level: (value: number) => void, onStopReady: (stop: () => void) => void, onSpeechStart?:()=>void): Promise<string>;
  speak(text: string, signal: AbortSignal, outputId: string, onPlaying?: () => void): Promise<void>;
}
const aborted = () => new DOMException('Voice stopped', 'AbortError');
export function speechChunks(text: string): string[] {
  const clean = text.replace(/```[\s\S]*?```/g, 'Code is available in the chat.').replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/^[#>*\s-]+/gm, '').replace(/[*_`]/g, '').trim();
  const chunks: string[] = []; let rest=clean;
  while(rest.length>500){const candidate=rest.slice(0,500);const cut=Math.max(candidate.lastIndexOf('. '),candidate.lastIndexOf('? '),candidate.lastIndexOf('! '));const end=cut>150?cut+1:Math.max(1,candidate.lastIndexOf(' '));chunks.push(rest.slice(0,end));rest=rest.slice(end).trim();}
  if(rest)chunks.push(rest);return chunks;
}
/** Client-owned microphone and audio element. No model execution or system audio routing. */
export class BrowserVoiceIO implements VoiceIO {
  private context?:AudioContext;
  private echoCancellation=false;
  get fullDuplex(){return this.echoCancellation;}
  prepare() {
    if(!this.context || this.context.state==='closed')this.context=new AudioContext();
    return this.context.resume();
  }
  release(){const context=this.context;this.context=undefined;if(context && context.state!=='closed')void context.close().catch(()=>{});}
  capability() { return getJson<SpeechCapability>('/api/jaeger/voice/capability'); }
  async devices() {const rows=await navigator.mediaDevices.enumerateDevices();return {microphones:rows.filter(row=>row.kind==='audioinput'),speakers:typeof AudioContext!=='undefined' && typeof (AudioContext.prototype as AudioContext & {setSinkId?:unknown}).setSinkId==='function'?rows.filter(row=>row.kind==='audiooutput'):[]};}
  async capture(signal: AbortSignal, inputId: string, level: (value:number)=>void, onStopReady:(stop:()=>void)=>void,onSpeechStart?:()=>void):Promise<string> {
    // Bounded silent recordings are discarded locally. Silence is not a
    // device failure or a message, and the session stays ready without a wake word.
    while(!signal.aborted){const text=await this.captureSegment(signal,inputId,level,onStopReady,onSpeechStart);if(text!==undefined)return text;}
    throw aborted();
  }
  private async captureSegment(signal: AbortSignal, inputId: string, level: (value:number)=>void, onStopReady:(stop:()=>void)=>void,onSpeechStart?:()=>void):Promise<string|undefined> {
    if(signal.aborted)throw aborted();
    if(!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder==='undefined')throw Error('Microphone recording is unavailable in this browser. Open the secure Jaeger URL in a supported browser.');
    const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,...(inputId?{deviceId:{exact:inputId}}:{})}});
    this.echoCancellation=stream.getAudioTracks()[0]?.getSettings().echoCancellation===true;
    let source:MediaStreamAudioSourceNode|undefined, analyser:AnalyserNode|undefined, timer:ReturnType<typeof setInterval>|undefined;
    try {
      if(signal.aborted)throw aborted();
      if(!this.context || this.context.state==='closed')this.context=new AudioContext();
      const context=this.context;await context.resume();
      analyser=context.createAnalyser();analyser.fftSize=1024;source=context.createMediaStreamSource(stream);source.connect(analyser);
      const types=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus','audio/webm'];
      const mime=types.find(type=>MediaRecorder.isTypeSupported(type));if(!mime)throw Error('No supported microphone recording format.');
      const recorder=new MediaRecorder(stream,{mimeType:mime});const samples=new Float32Array(analyser.fftSize);
      const chunks:BlobPart[]=[];let peak=0,started=Date.now(),speechAt=0,speechStartedAt=0,silenceAt=0,speechFrames=0,noise=0.003,automatic=false;
      const blob=await new Promise<Blob>((resolve,reject)=>{
        const stop=()=>{if(recorder.state!=='inactive')recorder.stop();};
        const abort=()=>{stop();reject(aborted());};signal.addEventListener('abort',abort,{once:true});
        recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
        recorder.onerror=()=>{signal.removeEventListener('abort',abort);reject(Error('Microphone recording failed.'));};
        recorder.onstop=()=>{signal.removeEventListener('abort',abort);resolve(new Blob(chunks,{type:mime}));};
        recorder.start(200);onStopReady(stop);
        timer=setInterval(()=>{
          if(signal.aborted){abort();return;}
          analyser!.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,value)=>sum+value*value,0)/samples.length);peak=Math.max(peak,rms);level(Math.min(1,rms*12));
          const elapsed=Date.now()-started;
          if(elapsed<500){noise=Math.min(0.012,Math.max(noise,rms));return;}
          if(rms>Math.max(0.008,Math.min(0.045,noise*2.2))){if(!speechStartedAt)speechStartedAt=Date.now();speechAt=Date.now();speechFrames++;if(speechFrames===3)onSpeechStart?.();silenceAt=0;}
          else if(speechAt && !silenceAt)silenceAt=Date.now();
          if((!speechAt && elapsed>20000) || (speechAt && silenceAt && Date.now()-silenceAt>1100) || (speechStartedAt && Date.now()-speechStartedAt>30000)){automatic=true;stop();}
        },80);
      });
      if(timer){clearInterval(timer);timer=undefined;}stream.getTracks().forEach(track=>track.stop());source?.disconnect();source=undefined;analyser?.disconnect();analyser=undefined;
      if(signal.aborted)throw aborted();
      if(automatic && speechFrames<3)return undefined;
      if(peak<0.003 || speechFrames<3 || !blob.size)throw Error('No microphone signal detected. Choose another microphone and try again.');
      const encoded=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Recording could not be read.'));reader.readAsDataURL(blob);});
      const result=await sendJson<{transcript:string}>('POST','/api/jaeger/transcribe',{audio_base64:encoded,mime});
      if(signal.aborted)throw aborted();
      if(!result.transcript?.trim())throw Error('No speech recognized. Speak clearly or choose another microphone.');
      return result.transcript.trim();
    } finally {if(timer)clearInterval(timer);stream.getTracks().forEach(track=>track.stop());source?.disconnect();analyser?.disconnect();level(0);}
  }
  async speak(text:string,signal:AbortSignal,outputId:string,onPlaying?:()=>void){
    for(const chunk of speechChunks(text)){
      if(signal.aborted)throw aborted();
      const response=await fetch('/api/jaeger/tts',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json',...csrfHeader('POST')},body:JSON.stringify({text:chunk}),signal});
      if(!response.ok)throw Error(`Speech synthesis failed (${response.status}). Your reply remains in chat.`);
      const blob=await response.blob();if(!blob.type.startsWith('audio/'))throw Error('Speech endpoint returned no audio.');
      if(!this.context || this.context.state==='closed')this.context=new AudioContext();
      const context=this.context;
      const sink=context as AudioContext & {setSinkId?:(id:string)=>Promise<void>};
      if(outputId && !sink.setSinkId)throw Error('This browser cannot select a speaker. Use the system default.');
      if(sink.setSinkId)await sink.setSinkId(outputId);
      const buffer=await context.decodeAudioData(await blob.arrayBuffer());
      if(signal.aborted)throw aborted();
      // Reuse the AudioContext unlocked by the initial user gesture. WebKit
      // can leave detached HTMLAudioElement blob playback pending forever.
      const source=context.createBufferSource();source.buffer=buffer;source.connect(context.destination);
      try {
        await new Promise<void>((resolve,reject)=>{
          let timer:ReturnType<typeof setTimeout>;
          const clear=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);source.onended=null;};
          const abort=()=>{clear();try{source.stop();}catch{}reject(aborted());};
          signal.addEventListener('abort',abort,{once:true});
          source.onended=()=>{clear();resolve();};
          timer=setTimeout(()=>{clear();try{source.stop();}catch{}reject(Error('Audio playback did not finish. Check browser audio permissions and your selected speaker.'));},Math.max(15000,(buffer.duration+5)*1000));
          if(signal.aborted){abort();return;}
          void context.resume().then(()=>{
            if(signal.aborted || !source.onended)return;
            try{source.start();onPlaying?.();window.dispatchEvent(new CustomEvent('jaeger:tts',{detail:{speaking:true,text:chunk}}));}catch(error){clear();reject(error);}
          },error=>{clear();reject(Error(`Audio playback was blocked: ${String(error)}. Tap Speak now to resume.`));});
        });
      }finally{source.disconnect();window.dispatchEvent(new CustomEvent('jaeger:tts',{detail:{speaking:false}}));}
    }
  }
}
