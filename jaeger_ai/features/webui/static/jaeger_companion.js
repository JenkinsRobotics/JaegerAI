// Jaeger speaks first: show and speak proactive messages from jaegerd.
// Polls the durable /api/jaeger/notifications feed (Gateway
// notification.proactive events), so it works for any session and survives
// reconnects. Speaking is interruptible: typing, clicking the bubble or
// pressing Escape stops it (same rule as the voice-mode TTS).
(function(){
  'use strict';
  if(window.__jaegerCompanion) return;
  window.__jaegerCompanion=true;
  const KEY='jaeger-companion-cursor';
  const MUTE='jaeger-companion-muted';
  let cursor=parseInt(localStorage.getItem(KEY)||'0',10)||0;
  let primed=cursor>0;
  let box=null;

  function ensureBox(){
    if(box) return box;
    box=document.createElement('div');
    box.id='jaegerCompanion';
    box.setAttribute('role','log');
    box.setAttribute('aria-live','polite');
    box.style.cssText='position:fixed;right:196px;bottom:120px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:min(380px,90vw);pointer-events:none';
    document.body.appendChild(box);
    return box;
  }

  // The avatar's mouth follows a 0..1 level: real audio when a server engine
  // (or Kokoro) returns a clip, word boundaries for browser speech.
  const face=()=>window.jaegerAvatar;
  let audioEl=null, audioCtx=null, meterRaf=0, pulseTimer=0;

  function stopSpeaking(){
    try{ if('speechSynthesis' in window) speechSynthesis.cancel(); }catch(_){}
    try{ if(audioEl){ audioEl.pause(); audioEl=null; } }catch(_){}
    cancelAnimationFrame(meterRaf); clearInterval(pulseTimer);
    if(face()) face().setSpeaking(false);
  }

  function meter(el){
    try{
      audioCtx=audioCtx||new (window.AudioContext||window.webkitAudioContext)();
      const src=audioCtx.createMediaElementSource(el), an=audioCtx.createAnalyser();
      an.fftSize=512; src.connect(an); an.connect(audioCtx.destination);
      const buf=new Uint8Array(an.fftSize);
      const tick=()=>{ an.getByteTimeDomainData(buf); let sum=0;
        for(const v of buf){ const d=(v-128)/128; sum+=d*d; }
        if(face()) face().setLevel(Math.min(1,Math.sqrt(sum/buf.length)*4));
        meterRaf=requestAnimationFrame(tick); };
      tick();
    }catch(_){}
  }

  async function speakAudio(text, engine){
    const r=await fetch('api/tts',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:String(text).slice(0,600),engine,voice:localStorage.getItem('hermes-tts-voice')||undefined})});
    if(!r.ok) throw new Error('tts '+r.status);
    const el=new Audio(URL.createObjectURL(await r.blob()));
    audioEl=el; meter(el);
    el.onplay=()=>face()&&face().setSpeaking(true);
    el.onended=el.onerror=()=>stopSpeaking();
    await el.play();
  }

  function speakBrowser(text){
    if(!('speechSynthesis' in window)) return;
    const u=new SpeechSynthesisUtterance(String(text).slice(0,600));
    const saved=localStorage.getItem('hermes-tts-voice');
    const voices=speechSynthesis.getVoices();
    if(saved&&voices.length){ const m=voices.find(v=>v.name===saved); if(m) u.voice=m; }
    const rate=parseFloat(localStorage.getItem('hermes-tts-rate')); if(!isNaN(rate)) u.rate=rate;
    let hit=0;
    u.onstart=()=>{ if(!face()) return; face().setSpeaking(true);
      // Envelope: a syllable-rate wobble, re-energised by every word boundary.
      pulseTimer=setInterval(()=>{ hit*=.82; face()&&face().setLevel(.25+.45*Math.abs(Math.sin(performance.now()/90))*(.4+hit)); },45); };
    u.onboundary=()=>{ hit=1; };
    u.onend=u.onerror=()=>stopSpeaking();
    speechSynthesis.speak(u);
  }

  function speak(text){
    if(localStorage.getItem(MUTE)==='1') return;
    stopSpeaking();
    const engine=localStorage.getItem('hermes-tts-engine')||'browser';
    if(engine!=='browser'){ speakAudio(text,engine).catch(()=>speakBrowser(text)); return; }
    try{ speakBrowser(text); }catch(_){}
  }

  function show(n){
    const el=document.createElement('div');
    el.className='jaeger-companion-msg';
    el.dataset.salience=n.salience||'digest';
    el.style.cssText='pointer-events:auto;background:var(--surface,#1d1d2e);color:var(--text,#eee);border:1px solid var(--accent,#6b8afd);border-radius:14px;padding:10px 12px;box-shadow:0 6px 24px rgba(0,0,0,.35);font-size:14px;line-height:1.4;cursor:pointer';
    const head=document.createElement('div');
    head.style.cssText='font-weight:600;font-size:12px;opacity:.8;margin-bottom:4px';
    head.textContent=(n.title||'Jaeger')+' \u00b7 messaged you first';
    const body=document.createElement('div');
    body.textContent=n.body||'';
    const hint=document.createElement('div');
    hint.style.cssText='font-size:11px;opacity:.6;margin-top:6px';
    hint.textContent='Reply in chat to answer. Click to dismiss.';
    el.append(head,body,hint);
    el.addEventListener('click',()=>{ stopSpeaking(); el.remove(); });
    ensureBox().appendChild(el);
    setTimeout(()=>{ if(el.isConnected) el.remove(); }, n.salience==='immediate'?120000:45000);
    try{
      if(document.hidden && 'Notification' in window && Notification.permission==='granted'){
        new Notification(n.title||'Jaeger',{body:n.body||'',tag:'jaeger-'+n.event_id});
      }
    }catch(_){}
    if(n.speak!==false) speak(n.body||'');
  }

  // One poll at a time. A slow first response (cold gateway) used to overlap
  // the next interval tick: the first to return set primed=true, then the other,
  // still holding since_event_id=0, showed every item unfiltered (the stale
  // replay). Also never show an event at or below the cursor, or one twice.
  let inflight=false;
  const seen=new Set();
  function fresh(n){
    const id=+n.event_id||0;
    if(id && (id<=cursor || seen.has(id))) return false;
    if(id) seen.add(id);
    return true;
  }
  async function poll(){
    if(inflight) return;
    inflight=true;
    try{
      const r=await fetch('api/jaeger/notifications?since_event_id='+cursor+'&limit=10',{credentials:'same-origin'});
      if(!r.ok) return;
      const data=await r.json();
      const items=(data&&data.notifications)||[];
      if(!primed){
        // First load: only surface what arrived in the last 10 minutes.
        const cutoff=Date.now()/1000-600;
        items.filter(n=>(n.created_at||n.timestamp||0)>=cutoff).filter(fresh).forEach(show);
        primed=true;
      }else{
        items.filter(fresh).forEach(show);
      }
      if(typeof data.cursor==='number' && data.cursor>cursor){
        cursor=data.cursor; localStorage.setItem(KEY,String(cursor));
      }
    }catch(_){
    }finally{ inflight=false; }
  }

  document.addEventListener('keydown',e=>{ if(e.key==='Escape') stopSpeaking(); });
  document.addEventListener('input',e=>{ if(e.target&&e.target.id==='msg') stopSpeaking(); },true);
  window.jaegerCompanion={poll,show,speak,stop:stopSpeaking,
    mute(on){ localStorage.setItem(MUTE,on?'1':'0'); if(on) stopSpeaking(); }};
  const start=()=>{ poll(); setInterval(poll,4000); };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
