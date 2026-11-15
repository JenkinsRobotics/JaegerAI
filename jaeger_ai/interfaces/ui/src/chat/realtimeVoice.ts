/** WebRTC client for Jaeger's realtime voice service (Pipecat SmallWebRTC behind
 * /api/jaeger/rtc/*). Audio goes peer to peer (on the tailnet from the phone);
 * the data channel carries captions, turn ends and the reply text to speak. */

import { getJson, sendJson } from '../unified/webui';

export type VoiceEngine = 'local' | 'gemini';
export interface RealtimeStatus { ok:boolean; error?:string; engines:{local?:{ready:boolean};gemini?:{ready:boolean;needs?:string|null;model?:string}} }
export type ServiceMessage =
 | {t:'ready';engine:VoiceEngine}
 | {t:'user-speaking';bot?:boolean}
 | {t:'user-partial';text:string}
 | {t:'user-final';text:string;turnMs?:number}
 | {t:'interrupted'}
 | {t:'bot-speaking';on:boolean;ttsMs?:number}
 | {t:'bot-text';text:string}
 | {t:'transcript';role:'user'|'assistant';text:string;interrupted?:boolean}
 | {t:'tool';id:string;request:string}
 | {t:'error';message:string};

export interface ConnectOptions { engine:VoiceEngine; inputId?:string; outputId?:string; history?:{role:string;content:string}[] }

const post=<T,>(path:string, body:unknown)=>sendJson<T>('POST',path,body);

export async function realtimeStatus():Promise<RealtimeStatus>{
 try{return await getJson<RealtimeStatus>('/api/jaeger/rtc/status');}
 catch{return {ok:false,engines:{},error:'Realtime voice service is not reachable'};}
}

/** Microphone level 0..1 from an analyser, smoothed for the orb. */
function meter(ctx:AudioContext, stream:MediaStream){
 const src=ctx.createMediaStreamSource(stream),an=ctx.createAnalyser();an.fftSize=512;an.smoothingTimeConstant=0.6;src.connect(an);
 const buf=new Uint8Array(an.fftSize);
 return ()=>{an.getByteTimeDomainData(buf);let sum=0;for(const v of buf){const x=(v-128)/128;sum+=x*x;}return Math.min(1,Math.sqrt(sum/buf.length)*4);};
}

export class RealtimeVoice {
 private pc?:RTCPeerConnection; private dc?:RTCDataChannel; private mic?:MediaStream; private audio?:HTMLAudioElement;
 private ctx?:AudioContext; private ping?:number; private pcId?:string; private pendingIce:RTCIceCandidate[]=[]; private closed=false;
 micLevel:()=>number=()=>0; botLevel:()=>number=()=>0;
 constructor(private onMessage:(m:ServiceMessage)=>void, private onState:(s:'connecting'|'connected'|'failed'|'closed', detail?:string)=>void){}

 /** Must run inside the user's tap (Safari audio and mic permission). */
 async connect(opts:ConnectOptions){
  this.audio=new Audio();this.audio.autoplay=true;(this.audio as HTMLAudioElement & {playsInline?:boolean}).playsInline=true;
  const Ctx=window.AudioContext||(window as unknown as {webkitAudioContext:typeof AudioContext}).webkitAudioContext;
  this.ctx=new Ctx();void this.ctx.resume();
  this.onState('connecting');
  try{
   this.mic=await navigator.mediaDevices.getUserMedia({audio:{deviceId:opts.inputId?{exact:opts.inputId}:undefined,echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
  }catch(e){
   const name=(e as Error).name;
   throw Error(name==='NotAllowedError'?'Microphone access is blocked. Allow it for this site (Safari: aA › Website Settings; Chrome: the lock icon) and try again.':name==='NotFoundError'?'No microphone was found.':`Microphone unavailable: ${(e as Error).message||name}`);
  }
  if(this.closed)return this.stopTracks();
  this.micLevel=meter(this.ctx,this.mic);
  const pc=this.pc=new RTCPeerConnection({iceServers:[]});
  pc.addTransceiver(this.mic.getAudioTracks()[0],{direction:'sendrecv'});
  pc.ontrack=ev=>{
   const stream=ev.streams[0]||new MediaStream([ev.track]);
   if(this.audio){this.audio.srcObject=stream;if(opts.outputId&&'setSinkId' in this.audio)void (this.audio as HTMLAudioElement & {setSinkId(id:string):Promise<void>}).setSinkId(opts.outputId).catch(()=>{});void this.audio.play().catch(()=>{});}
   if(this.ctx)this.botLevel=meter(this.ctx,stream);
  };
  pc.onicecandidate=ev=>{if(!ev.candidate)return;if(this.pcId)void this.sendIce([ev.candidate]);else this.pendingIce.push(ev.candidate);};
  pc.onconnectionstatechange=()=>{
   const s=pc.connectionState;
   if(s==='connected')this.onState('connected');
   else if(s==='failed')this.onState('failed','The voice connection failed. Check that this device is on the tailnet.');
   else if(s==='disconnected'||s==='closed'){if(!this.closed)this.onState('failed','The voice connection dropped.');}
  };
  const dc=this.dc=pc.createDataChannel('jaeger',{ordered:true});
  dc.onopen=()=>{this.ping=window.setInterval(()=>{if(dc.readyState==='open')dc.send('ping: '+Date.now());},1000);dc.send('ping: '+Date.now());};
  dc.onmessage=ev=>{
   if(typeof ev.data!=='string')return;
   try{const m=JSON.parse(ev.data);if(m&&typeof m.t==='string')this.onMessage(m as ServiceMessage);}catch{/* not ours */}
  };
  await pc.setLocalDescription(await pc.createOffer());
  const answer=await post<{sdp:string;type:RTCSdpType;pc_id:string}>('/api/jaeger/rtc/offer',{sdp:pc.localDescription!.sdp,type:pc.localDescription!.type,request_data:{engine:opts.engine,history:(opts.history||[]).slice(-12)}});
  if(this.closed)return;
  this.pcId=answer.pc_id;
  await pc.setRemoteDescription({sdp:answer.sdp,type:answer.type});
  if(this.pendingIce.length){void this.sendIce(this.pendingIce.splice(0));}
 }

 private async sendIce(cands:RTCIceCandidate[]){
  try{await post('/api/jaeger/rtc/ice',{pc_id:this.pcId,candidates:cands.map(c=>({candidate:c.candidate,sdp_mid:c.sdpMid,sdp_mline_index:c.sdpMLineIndex}))});}catch{/* host candidates in the SDP usually suffice */}
 }

 send(message:Record<string,unknown>){if(this.dc?.readyState==='open')this.dc.send(JSON.stringify({type:'jaeger',...message}));}
 setMuted(muted:boolean){this.mic?.getAudioTracks().forEach(t=>{t.enabled=!muted;});}
 private stopTracks(){this.mic?.getTracks().forEach(t=>t.stop());}
 close(){
  this.closed=true;if(this.ping)window.clearInterval(this.ping);
  try{this.dc?.close();}catch{/* closing */}
  try{this.pc?.close();}catch{/* closing */}
  this.stopTracks();if(this.audio){this.audio.pause();this.audio.srcObject=null;}
  void this.ctx?.close().catch(()=>{});this.micLevel=()=>0;this.botLevel=()=>0;this.onState('closed');
 }
}
