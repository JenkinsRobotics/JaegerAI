// Jaeger persistent agents: a short roster above the chat list (Grok Bot style).
// Jaeger (the lead) first, then the standing specialists, then connected
// third-party agents. A click opens that agent's one home session; the gateway
// owns the id and routing (metadata.agent_id), this file only renders.
(function(){
  'use strict';
  const ORDER={lead:0,specialist:1};
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
    const h=document.createElement('div');h.className='jaeger-agents-title';h.textContent='Agents';root.appendChild(h);
    for(const a of agents){
      const b=document.createElement('button');b.type='button';b.className='jaeger-agent';b.dataset.home=homeId(a);
      b.title=a.summary||(a.metadata&&a.metadata.summary)||label(a);
      const dot=document.createElement('span');dot.className='jaeger-agent-dot'+(a.role==='lead'?' lead':'');
      const t=document.createElement('span');t.textContent=label(a);
      b.appendChild(dot);b.appendChild(t);
      b.addEventListener('click',()=>open(a).catch(e=>console.warn('agent open',e)));
      root.appendChild(b);
    }
    const cur=window.S&&S.session&&S.session.session_id;if(cur)mark(cur);
  }
  function css(){
    if(document.getElementById('jaegerAgentsCss'))return;
    const st=document.createElement('style');st.id='jaegerAgentsCss';
    st.textContent='#jaegerAgents{padding:6px 8px 8px;border-bottom:1px solid var(--border,rgba(127,127,127,.2));margin-bottom:4px}'+
      '.jaeger-agents-title{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.6;margin:2px 4px 4px}'+
      '.jaeger-agent{display:flex;align-items:center;gap:8px;width:100%;padding:6px 8px;border:0;border-radius:8px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}'+
      '.jaeger-agent:hover{background:var(--hover,rgba(127,127,127,.12))}.jaeger-agent.active{background:var(--active,rgba(127,127,127,.2));font-weight:600}'+
      '.jaeger-agent-dot{width:8px;height:8px;border-radius:50%;background:#7a8;flex:none}.jaeger-agent-dot.lead{background:#4af}';
    document.head.appendChild(st);
  }
  async function boot(){
    const list=document.getElementById('sessionList');if(!list)return;
    let root=document.getElementById('jaegerAgents');
    if(!root){root=document.createElement('div');root.id='jaegerAgents';list.parentNode.insertBefore(root,list.previousElementSibling||list);}
    css();
    try{const d=await getJSON('api/agents');render(root,sortAgents(d.agents||d||[]));}
    catch(e){root.remove();console.warn('agents roster',e);}
  }
  window.jaegerAgents={sortAgents,label,homeId,boot};
  if(typeof document!=='undefined'&&document.readyState!=='loading')boot();else document.addEventListener('DOMContentLoaded',boot);
})();
