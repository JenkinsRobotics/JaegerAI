// Jaeger speaks first: show and speak proactive messages from jaegerd.
// Docked in a dedicated top-right notification slot with explicit Reply and
// Dismiss controls so notifications never overlap status messages or the composer.
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
    box.setAttribute('role','region');
    box.setAttribute('aria-label','Notifications');
    box.setAttribute('aria-live','polite');
    box.style.cssText='position:fixed;top:60px;right:20px;bottom:auto;z-index:9500;display:flex;flex-direction:column;align-items:flex-end;gap:10px;max-width:min(380px,calc(100vw - 32px));pointer-events:none';
    document.body.appendChild(box);
    return box;
  }

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

  async function speakAudio(url, payload){
    const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)});
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
      pulseTimer=setInterval(()=>{ hit*=.82; face()&&face().setLevel(.25+.45*Math.abs(Math.sin(performance.now()/90))*(.4+hit)); },45); };
    u.onboundary=()=>{ hit=1; };
    u.onend=u.onerror=()=>stopSpeaking();
    speechSynthesis.speak(u);
  }

  function speak(text){
    if(localStorage.getItem(MUTE)==='1') return;
    stopSpeaking();
    const engine=localStorage.getItem('hermes-tts-engine')||'browser';
    const t=String(text).slice(0,600);
    const req=(engine==='browser'||engine==='kokoro')
      ? speakAudio('api/jaeger/tts',{text:t})
      : speakAudio('api/tts',{text:t,engine,voice:localStorage.getItem('hermes-tts-voice')||undefined});
    req.catch(()=>{ try{ speakBrowser(t); }catch(_){} });
  }

  function show(n){
    const el=document.createElement('div');
    el.className='jaeger-companion-msg';
    el.dataset.salience=n.salience||'digest';
    el.style.cssText='pointer-events:auto;background:var(--surface,#171a22);color:var(--text,#f3f5f8);border:1px solid var(--border,rgba(255,255,255,.14));border-left:3px solid var(--accent,#3b82f6);border-radius:14px;padding:12px 14px;box-shadow:0 10px 30px rgba(0,0,0,.45);font-size:13.5px;line-height:1.45;width:100%';

    const topRow=document.createElement('div');
    topRow.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px';
    const head=document.createElement('div');
    head.style.cssText='font-weight:600;font-size:12px;color:var(--text,#fff);opacity:.9';
    head.textContent=(n.title||'Jaeger')+' · Notification';
    const closeBtn=document.createElement('button');
    closeBtn.type='button';
    closeBtn.className='jaeger-companion-dismiss';
    closeBtn.setAttribute('aria-label','Dismiss notification');
    closeBtn.title='Dismiss';
    closeBtn.style.cssText='background:transparent;border:0;color:var(--text-muted,#9aa2b2);font-size:16px;line-height:1;padding:2px 6px;border-radius:6px;cursor:pointer';
    closeBtn.textContent='×';
    closeBtn.addEventListener('click',(e)=>{ e.stopPropagation(); stopSpeaking(); el.remove(); });
    topRow.append(head,closeBtn);

    const body=document.createElement('div');
    body.style.cssText='margin-bottom:10px;color:var(--text,#e5e9f0)';
    body.textContent=n.body||'';

    const actions=document.createElement('div');
    actions.style.cssText='display:flex;align-items:center;justify-content:flex-end;gap:8px';
    const replyBtn=document.createElement('button');
    replyBtn.type='button';
    replyBtn.className='jaeger-companion-reply-btn';
    replyBtn.style.cssText='background:var(--accent,#3b82f6);color:#fff;border:0;border-radius:999px;padding:4px 12px;font-size:12px;font-weight:600;cursor:pointer';
    replyBtn.textContent='Reply in chat';
    replyBtn.addEventListener('click',(e)=>{
      e.stopPropagation();
      stopSpeaking();
      const msgInput=document.getElementById('msg');
      if(msgInput){ msgInput.focus(); }
      el.remove();
    });
    const dismissBtn=document.createElement('button');
    dismissBtn.type='button';
    dismissBtn.className='jaeger-companion-dismiss-btn';
    dismissBtn.style.cssText='background:rgba(255,255,255,.07);color:var(--text,#eee);border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:4px 12px;font-size:12px;cursor:pointer';
    dismissBtn.textContent='Dismiss';
    dismissBtn.addEventListener('click',(e)=>{ e.stopPropagation(); stopSpeaking(); el.remove(); });
    actions.append(replyBtn,dismissBtn);

    el.append(topRow,body,actions);
    ensureBox().appendChild(el);
    setTimeout(()=>{ if(el.isConnected) el.remove(); }, n.salience==='immediate'?120000:45000);
    try{
      if(document.hidden && 'Notification' in window && Notification.permission==='granted'){
        new Notification(n.title||'Jaeger',{body:n.body||'',tag:'jaeger-'+n.event_id});
      }
    }catch(_){}
    if(n.speak!==false) speak(n.body||'');
  }

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
