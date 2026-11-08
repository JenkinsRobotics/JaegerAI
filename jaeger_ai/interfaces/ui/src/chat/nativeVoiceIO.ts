import { nativeBridge, onNativeEvent, probeSpeech } from '../platform/native';
import type { VoiceIO } from './webSpeech';
const abortError=()=>new DOMException('Voice stopped','AbortError');
/** Existing shell mic and TTS bridge; no independent audio daemon. */
export class NativeVoiceIO implements VoiceIO {
  async capability(){const caps=await probeSpeech();return {transcription:caps.dictation,speech:caps.voiceChat,reason:'Check microphone and speech permissions in macOS Settings.'};}
  async devices(){return {microphones:[],speakers:[]};}
  async capture(signal:AbortSignal,_input:string,level:(value:number)=>void,onStopReady:(stop:()=>void)=>void):Promise<string>{
    const bridge=nativeBridge();if(!bridge)throw Error('Native microphone bridge unavailable.');if(signal.aborted)throw abortError();
    return new Promise<string>((resolve,reject)=>{
      let stopped=false,started=false,speechAt=0,silenceAt=0;let finalTimer:ReturnType<typeof setTimeout>|undefined;
      const timer=setTimeout(()=>stop(),30000);
      const cleanup=()=>{clearTimeout(timer);if(finalTimer)clearTimeout(finalTimer);signal.removeEventListener('abort',abort);off();level(0);};
      const stop=()=>{if(stopped || !started)return;stopped=true;finalTimer=setTimeout(()=>{cleanup();reject(Error('Speech recognition timed out. Your recording was not sent as a chat message.'));},30000);void bridge.post('mic.stop').catch(e=>{cleanup();reject(e);});};
      const abort=()=>{stop();cleanup();reject(abortError());};
      const off=onNativeEvent(raw=>{
        const event=raw as {type:string;rms?:number;text?:string;final?:boolean;message?:string};
        if(event.type==='voice.error'){cleanup();reject(Error(event.message || 'Microphone failed.'));}
        else if(event.type==='voice.transcript' && event.final!==false){cleanup();event.text?.trim()?resolve(event.text.trim()):reject(Error('No speech recognized.'));}
        else if(event.type==='voice.level' && !stopped){const rms=event.rms || 0;level(Math.min(1,rms*12));if(rms>0.008){speechAt=Date.now();silenceAt=0;}else if(speechAt && !silenceAt)silenceAt=Date.now();else if(speechAt && silenceAt && Date.now()-silenceAt>1100)stop();}
      });
      signal.addEventListener('abort',abort,{once:true});
      void bridge.post('mic.start',{mode:'dictation'}).then(()=>{started=true;if(signal.aborted){abort();return;}onStopReady(stop);},e=>{cleanup();reject(e);});
    });
  }
  async speak(text:string,signal:AbortSignal,_output:string,onPlaying?:()=>void):Promise<void>{
    const bridge=nativeBridge();if(!bridge)throw Error('Native speech bridge unavailable.');if(signal.aborted)throw abortError();
    return new Promise<void>((resolve,reject)=>{
      const cleanup=()=>{signal.removeEventListener('abort',abort);off();};
      const abort=()=>{void bridge.post('tts.stop');cleanup();reject(abortError());};
      const off=onNativeEvent(raw=>{const event=raw as {type:string;completed?:boolean;message?:string};if(event.type==='tts.done'){cleanup();event.completed===false?reject(Error('Speech interrupted.')):resolve();}else if(event.type==='voice.error'){cleanup();reject(Error(event.message || 'Speech failed.'));}});
      signal.addEventListener('abort',abort,{once:true});void bridge.post('tts.speak',{text}).then(()=>{if(!signal.aborted)onPlaying?.();}).catch(e=>{cleanup();reject(e);});
    });
  }
}
