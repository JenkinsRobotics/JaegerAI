// Jaeger's face in the WebUI (avatar v1): a small animated canvas face.
// Expression follows presence (GET api/jaeger/presence -> contract/presence.py
// DISPLAY labels). The mouth follows a 0..1 speech level that the companion
// feeds from real audio (AnalyserNode) or from browser-speech word boundaries.
// It only renders: it decides nothing and sends nothing.
(function(){
  'use strict';
  if(window.jaegerAvatar) return;
  const MODE_KEY='jaeger-avatar-mode';           // 'face' | 'vrm' | 'off'
  const BASE=(document.currentScript&&document.currentScript.src)||location.href;
  let v2=null, v2Loading=null;
  const EXPR={
    idle:{brow:0,eye:1,smile:.35,hue:220},
    listening:{brow:.25,eye:1.1,smile:.25,hue:200},
    thinking:{brow:.45,eye:.8,smile:.05,hue:265,look:.35},
    focused:{brow:.3,eye:.85,smile:.1,hue:190},
    waiting:{brow:.1,eye:.95,smile:.2,hue:220},
    ask_owner:{brow:.6,eye:1.15,smile:.3,hue:45},
    blocked:{brow:-.4,eye:.9,smile:-.3,hue:15},
    complete:{brow:.2,eye:.75,smile:.7,hue:140},
    safe_stopped:{brow:-.2,eye:.6,smile:-.1,hue:0},
    offline:{brow:0,eye:.4,smile:0,hue:230},
  };
  let display='idle', target=EXPR.idle, cur=Object.assign({},EXPR.idle,{look:0});
  let level=0, shown=0, speaking=false, blinkAt=performance.now()+2500, blinkT=0;
  let wrap=null, canvas=null, ctx=null, label=null, raf=0;

  function mode(){ return localStorage.getItem(MODE_KEY)||'face'; }

  function mount(){
    if(wrap) return;
    wrap=document.createElement('div');
    wrap.id='jaegerAvatar';
    wrap.title='Jaeger (click to switch face / 3D / off)';
    wrap.style.cssText='position:fixed;right:18px;bottom:120px;z-index:9999;width:72px;height:72px;border-radius:50%;overflow:hidden;cursor:pointer;box-shadow:0 6px 24px rgba(0,0,0,.4);background:#11131c';
    canvas=document.createElement('canvas');
    canvas.width=144; canvas.height=144;
    canvas.style.cssText='width:100%;height:100%;display:block';
    label=document.createElement('div');
    label.id='jaegerAvatarState';
    label.style.cssText='position:fixed;right:18px;bottom:104px;z-index:9999;font:10px system-ui;opacity:.6;color:var(--text,#ccc);width:72px;text-align:center;pointer-events:none';
    wrap.appendChild(canvas);
    document.body.append(wrap,label);
    ctx=canvas.getContext('2d');
    wrap.addEventListener('click',cycle);
  }

  function cycle(){
    const order=['face','vrm','off'];
    setMode(order[(order.indexOf(mode())+1)%order.length]);
  }

  // v2 (3D VRM) loads on demand; any failure falls back to this face.
  function startV2(){
    if(v2||v2Loading) return;
    v2Loading=Promise.resolve().then(()=>import(new URL('jaeger_avatar_vrm.js',BASE).href))
      .then(m=>m.start(api).then(()=>{ v2=m; }))
      .catch(err=>{ try{console.warn('[jaeger-avatar] 3D unavailable, using the face:',err&&err.message);}catch(_){}
        localStorage.setItem(MODE_KEY,'face'); applyMode('face'); })
      .finally(()=>{ v2Loading=null; if(mode()!=='vrm' && v2){ v2.stop(); v2=null; } });
  }

  function applyMode(m){
    if(wrap){
      wrap.style.display=m==='vrm'?'none':'block';
      wrap.style.opacity=m==='off'?'.25':'1';
    }
    if(m==='vrm') startV2(); else if(v2){ v2.stop(); v2=null; }
  }

  function setMode(m){
    localStorage.setItem(MODE_KEY,m);
    applyMode(m);
    try{ window.dispatchEvent(new CustomEvent('jaeger-avatar-mode',{detail:m})); }catch(_){}
  }

  const lerp=(a,b,t)=>a+(b-a)*t;

  function draw(now){
    raf=requestAnimationFrame(draw);
    if(!ctx || mode()!=='face') return;
    for(const k of ['brow','eye','smile','hue']) cur[k]=lerp(cur[k],target[k],.08);
    cur.look=lerp(cur.look||0,target.look||0,.05);
    shown=lerp(shown,speaking?level:0,.35);
    if(now>blinkAt){ blinkT=now; blinkAt=now+2200+Math.random()*3500; }
    const b=Math.max(0,1-Math.abs(now-blinkT-70)/70);           // 140 ms blink
    const bob=Math.sin(now/900)*2;                               // idle breathing
    const W=144,H=144; ctx.clearRect(0,0,W,H);
    const g=ctx.createRadialGradient(72,60,10,72,72,80);
    g.addColorStop(0,`hsl(${cur.hue} 55% 34%)`); g.addColorStop(1,`hsl(${cur.hue} 45% 12%)`);
    ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
    ctx.save(); ctx.translate(0,bob);
    const lx=Math.sin(now/1300)*3+cur.look*8, ly=-cur.look*4;
    for(const x of [50,94]){
      const eh=11*cur.eye*(1-b*.92);
      ctx.fillStyle='#eaf2ff'; ctx.beginPath(); ctx.ellipse(x,62,9,Math.max(1,eh),0,0,Math.PI*2); ctx.fill();
      if(eh>3){ ctx.fillStyle='#0b1020'; ctx.beginPath(); ctx.arc(x+lx,62+ly,4.2,0,Math.PI*2); ctx.fill(); }
      ctx.strokeStyle='#eaf2ff'; ctx.lineWidth=3; ctx.lineCap='round';
      const tilt=(x<72?1:-1)*cur.brow*5;
      ctx.beginPath(); ctx.moveTo(x-9,45-cur.brow*4+tilt); ctx.lineTo(x+9,45-cur.brow*4-tilt); ctx.stroke();
    }
    const open=shown*16, s=cur.smile*10;
    ctx.fillStyle='#0b1020'; ctx.strokeStyle='#eaf2ff'; ctx.lineWidth=3;
    ctx.beginPath(); ctx.moveTo(54,96); ctx.quadraticCurveTo(72,96+s+open,90,96);
    ctx.quadraticCurveTo(72,96+s-open*.35,54,96); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.restore();
  }

  function setState(d){
    display=EXPR[d]?d:'idle'; target=EXPR[display];
    if(label) label.textContent=speaking?'speaking':display.replace('_',' ');
    try{ window.dispatchEvent(new CustomEvent('jaeger-avatar-state',{detail:display})); }catch(_){}
  }

  async function poll(){
    try{
      const r=await fetch('api/jaeger/presence',{credentials:'same-origin'});
      if(r.ok){ const p=await r.json(); setState(p.display||'idle'); }
      else setState('offline');
    }catch(_){ setState('offline'); }
  }

  const api=window.jaegerAvatar={
    cycle,
    raw(){ return {display,speaking,level:speaking?level:0}; },
    setLevel(v){ level=Math.max(0,Math.min(1,+v||0)); },
    setSpeaking(on){ speaking=!!on; if(!on) level=0; if(label) label.textContent=on?'speaking':display.replace('_',' '); },
    setState, setMode, mode,
    get state(){ return {display,speaking,level:shown}; },
  };
  const start=()=>{ mount(); setMode(mode()); raf=requestAnimationFrame(draw); poll(); setInterval(poll,2000); };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
