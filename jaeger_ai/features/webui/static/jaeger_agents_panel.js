// Jaeger persistent agents: a short roster above the chat list (Grok Bot style).
// Jaeger (the lead) first, then the standing specialists, then connected
// third-party agents. A click opens that agent's one home session; the gateway
// owns the id and routing (metadata.agent_id), this file only renders.
(function(){
  'use strict';
  const ORDER={lead:0,specialist:1};
  // sessions.js declares S with let at top level: a global binding, not a window property.
  function curSid(){try{return (typeof S!=='undefined'&&S&&S.session&&S.session.session_id)||null;}catch(_){return null;}}
  function visible(a){return a&&!a.hidden&&(a.role==='lead'||a.role==='specialist');}
  function label(a){return a.role==='lead'?'Jaeger':(a.display_name||a.name||a.id);}
  function sortAgents(list){
    return list.filter(visible).sort((x,y)=>
      (ORDER[x.role]-ORDER[y.role])||((x.kind==='third_party')-(y.kind==='third_party'))||label(x).localeCompare(label(y)));
  }
  function homeId(a){
    const n=String(a.name||String(a.id||'').split(':').pop()).toLowerCase().replace(/[^a-z0-9_-]/g,'-').slice(0,48)||'jaeger';
    return 'agent-'+n;
  }
  async function getJSON(url,opts){const r=await fetch(url,Object.assign({credentials:'same-origin'},opts||{}));if(!r.ok)throw new Error(url+' '+r.status);return r.json();}
  async function open(a){
    const s=await getJSON('api/jaeger/agent-home',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_id:a.id})});
    const sid=s.session_id||homeId(a);
    if(typeof window.loadSession==='function') await window.loadSession(sid);
    if(typeof window.renderSessionList==='function') try{window.renderSessionList();}catch(_){}
    mark(sid);
  }
  function mark(sid){
    document.querySelectorAll('#jaegerAgents [data-home]').forEach(el=>el.classList.toggle('active',el.dataset.home===sid));
  }
  function render(root,agents){
    root.innerHTML='';
    const h=document.createElement('div');h.className='jaeger-agents-title';h.textContent='Agents';
    const fx=document.createElement('button');fx.type='button';fx.className='jaeger-fw-btn';fx.textContent='Frameworks…';fx.title='Other agent frameworks on this Mac';
    fx.addEventListener('click',()=>window.jaegerFrameworks&&window.jaegerFrameworks.open().catch(e=>console.warn('frameworks',e)));
    h.appendChild(fx);root.appendChild(h);
    for(const a of agents){
      const b=document.createElement('button');b.type='button';b.className='jaeger-agent';b.dataset.home=homeId(a);
      b.title=a.summary||(a.metadata&&a.metadata.summary)||label(a);
      const dot=document.createElement('span');dot.className='jaeger-agent-dot'+(a.role==='lead'?' lead':'');
      const t=document.createElement('span');t.textContent=label(a);
      b.appendChild(dot);b.appendChild(t);
      b.addEventListener('click',()=>open(a).catch(e=>console.warn('agent open',e)));
      root.appendChild(b);
    }
    const cur=curSid();if(cur)mark(cur);
  }
  function css(){
    if(document.getElementById('jaegerAgentsCss'))return;
    const st=document.createElement('style');st.id='jaegerAgentsCss';
    st.textContent='#jaegerAgents{padding:6px 8px 8px;border-bottom:1px solid var(--border,rgba(127,127,127,.2));margin-bottom:4px}'+
      '.jaeger-agents-title{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.6;margin:2px 4px 4px}'+
      '.jaeger-agent{display:flex;align-items:center;gap:8px;width:100%;padding:6px 8px;border:0;border-radius:8px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}'+
      '.jaeger-agent:hover{background:var(--hover,rgba(127,127,127,.12))}.jaeger-agent.active{background:var(--active,rgba(127,127,127,.2));font-weight:600}'+
      '.jaeger-agent-chip{border:1px solid var(--border,rgba(127,127,127,.35));border-radius:999px;background:transparent;color:inherit;padding:2px 10px;cursor:pointer;font:inherit}'+
      '.jaeger-agent-menu{position:absolute;top:26px;left:0;z-index:50;min-width:200px;background:var(--bg,#111);border:1px solid var(--border,rgba(127,127,127,.35));border-radius:8px;padding:4px}'+
      '.jaeger-agent-menu button{display:block;width:100%;text-align:left;background:transparent;border:0;color:inherit;padding:6px 8px;border-radius:6px;cursor:pointer;font:inherit}.jaeger-agent-menu button:hover{background:rgba(127,127,127,.15)}'+
      '.jaeger-routed{opacity:.8}.jaeger-undo{background:transparent;border:0;color:#4af;cursor:pointer;font:inherit;padding:0;text-decoration:underline}'+
      '.jaeger-fw-btn{float:right;background:transparent;border:0;color:#4af;cursor:pointer;font:inherit;text-transform:none;letter-spacing:0;font-size:11px}'+
      '.jaeger-agent-dot{width:8px;height:8px;border-radius:50%;background:#7a8;flex:none}.jaeger-agent-dot.lead{background:#4af}';
    document.head.appendChild(st);
  }
  async function boot(){
    const list=document.getElementById('sessionList');if(!list)return;
    let root=document.getElementById('jaegerAgents');
    if(!root){root=document.createElement('div');root.id='jaegerAgents';list.parentNode.insertBefore(root,list.previousElementSibling||list);}
    css();
    try{const d=await getJSON('api/agents');roster=sortAgents(d.agents||d||[]);render(root,roster);setInterval(()=>refreshChip().catch(()=>{}),2000);}
    catch(e){root.remove();console.warn('agents roster',e);}
  }

  // ── Chat header: which agent owns this conversation + "Hand off to…" ──
  let roster=[],chipSid=null,chipAt=0;
  function agentById(id){return roster.find(a=>a.id===id);}
  function chipText(sess){
    const a=agentById(sess.agent_id||'native:jaeger');
    return 'with '+(a?label(a):(sess.display_name||'Jaeger'));
  }
  function menuItems(sess){
    const cur=sess.agent_id||'native:jaeger', sug=(sess.metadata||{}).suggested_agent_id;
    return roster.filter(a=>a.id!==cur).map(a=>({id:a.id,text:(a.id===sug?'★ Suggested: ':'Hand off to ')+label(a)}))
      .sort((x,y)=>(y.text.startsWith('★'))-(x.text.startsWith('★')));
  }
  function routedNotice(sess){
    const m=sess.metadata||{};if(m.routed_by!=='auto'||!m.previous_agent_id)return null;
    const a=agentById(sess.agent_id);return {text:'Jaeger handed this to '+(a?label(a):sess.agent_id),undoTo:m.previous_agent_id};
  }
  async function handoff(sid,to){
    await getJSON('api/jaeger/sessions/'+encodeURIComponent(sid)+'/handoff',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({to_agent_id:to,reason:'owner',keep_history:true})});
    chipSid=null;await refreshChip();
  }
  async function refreshChip(){
    const sid=curSid();
    let chip=document.getElementById('jaegerAgentChip');
    if(!sid){if(chip)chip.hidden=true;return;}
    if(sid===chipSid&&chip&&!chip.hidden&&Date.now()-chipAt<4000)return;
    chipSid=sid;chipAt=Date.now();
    let sess;try{sess=await getJSON('api/jaeger/sessions/'+encodeURIComponent(sid));}catch(_){if(chip)chip.hidden=true;return;}
    if(!chip){
      const host=document.getElementById('appTitlebarTitle');if(!host||!host.parentNode)return;
      chip=document.createElement('span');chip.id='jaegerAgentChip';chip.style.cssText='position:relative;margin-left:10px;font-size:12px';
      host.parentNode.insertBefore(chip,host.nextSibling);
    }
    chip.hidden=false;chip.innerHTML='';
    const b=document.createElement('button');b.type='button';b.className='jaeger-agent-chip';b.textContent=chipText(sess)+' ▾';
    const sug=(sess.metadata||{}).suggested_agent_id;if(sug&&sug!==(sess.agent_id||'native:jaeger'))b.textContent+=' ★';
    const m=document.createElement('div');m.className='jaeger-agent-menu';m.hidden=true;
    for(const it of menuItems(sess)){const o=document.createElement('button');o.type='button';o.textContent=it.text;
      o.addEventListener('click',()=>{m.hidden=true;handoff(sid,it.id).catch(e=>console.warn('handoff',e));});m.appendChild(o);}
    b.addEventListener('click',()=>{m.hidden=!m.hidden;});
    chip.appendChild(b);chip.appendChild(m);
    const n=routedNotice(sess);
    if(n){const t=document.createElement('span');t.className='jaeger-routed';t.textContent=' '+n.text+' · ';
      const u=document.createElement('button');u.type='button';u.className='jaeger-undo';u.textContent='Undo';
      u.addEventListener('click',()=>handoff(sid,n.undoTo).catch(e=>console.warn('undo',e)));t.appendChild(u);chip.appendChild(t);}
  }
  window.jaegerAgents={sortAgents,label,homeId,boot,chipText,menuItems,routedNotice,setRoster:r=>{roster=r;}};
  if(typeof document!=='undefined'&&document.readyState!=='loading')boot();else document.addEventListener('DOMContentLoaded',boot);
})();
