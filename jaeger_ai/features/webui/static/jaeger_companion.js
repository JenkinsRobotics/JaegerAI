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
    box.style.cssText='position:fixed;right:18px;bottom:96px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:min(380px,90vw);pointer-events:none';
    document.body.appendChild(box);
    return box;
  }

  function stopSpeaking(){ try{ if('speechSynthesis' in window) speechSynthesis.cancel(); }catch(_){} }

  function speak(text){
    if(localStorage.getItem(MUTE)==='1' || !('speechSynthesis' in window)) return;
    try{
      stopSpeaking();
      const u=new SpeechSynthesisUtterance(String(text).slice(0,600));
      const saved=localStorage.getItem('hermes-tts-voice');
      const voices=speechSynthesis.getVoices();
      if(saved&&voices.length){ const m=voices.find(v=>v.name===saved); if(m) u.voice=m; }
      const rate=parseFloat(localStorage.getItem('hermes-tts-rate')); if(!isNaN(rate)) u.rate=rate;
      speechSynthesis.speak(u);
    }catch(_){}
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

  async function poll(){
    try{
      const r=await fetch('api/jaeger/notifications?since_event_id='+cursor+'&limit=10',{credentials:'same-origin'});
      if(!r.ok) return;
      const data=await r.json();
      const items=(data&&data.notifications)||[];
      if(!primed){
        // First load: only surface what arrived in the last 10 minutes.
        const cutoff=Date.now()/1000-600;
        items.filter(n=>(n.created_at||n.timestamp||0)>=cutoff).forEach(show);
        primed=true;
      }else{
        items.forEach(show);
      }
      if(typeof data.cursor==='number' && data.cursor>cursor){
        cursor=data.cursor; localStorage.setItem(KEY,String(cursor));
      }
    }catch(_){}
  }

  document.addEventListener('keydown',e=>{ if(e.key==='Escape') stopSpeaking(); });
  document.addEventListener('input',e=>{ if(e.target&&e.target.id==='msg') stopSpeaking(); },true);
  window.jaegerCompanion={poll,show,speak,stop:stopSpeaking,
    mute(on){ localStorage.setItem(MUTE,on?'1':'0'); if(on) stopSpeaking(); }};
  const start=()=>{ poll(); setInterval(poll,4000); };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
