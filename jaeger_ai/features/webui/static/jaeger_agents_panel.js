// Jaeger Agent-First Navigation & Selected-Agent Workspace Header (ARES layout).
// 1. Left sidebar (#jaegerAgents) lists user-facing configured agents with avatars
//    (lead Jaeger + non-internal configured specialists; internal 'gateway' and
//    'surfaces' components and raw framework adapters are excluded).
// 2. Main workspace header (#assistantHeader) displays the prominent selected-agent
//    avatar, name, connection status dot, History drawer toggle, New conversation
//    action, and Voice Call control.
(function(){
  'use strict';
  const INTERNAL_IDS=new Set(['native:gateway','native:surfaces','gateway','surfaces']);
  const INTERNAL_NAMES=new Set(['gateway','surfaces']);
  const ORDER={lead:0,specialist:1};
  let roster=[], selectedAgentId='native:jaeger';

  function curSid(){
    try{return (typeof S!=='undefined'&&S&&S.session&&S.session.session_id)||null;}catch(_){return null;}
  }

  function visible(a){
    if(!a||a.hidden) return false;
    const id=String(a.id||'').toLowerCase();
    const name=String(a.name||'').toLowerCase();
    const meta=a.metadata||{};
    if(meta.internal===true||INTERNAL_IDS.has(id)||INTERNAL_NAMES.has(name)) return false;
    // Exclude raw third-party framework adapters (Hermes, OpenClaw, Roundtable) from user-facing specialist list
    if(a.kind==='third_party'||id.startsWith('tp:')) return false;
    return a.role==='lead'||a.role==='specialist'||a.kind==='native';
  }

  function label(a){
    if(!a) return 'Jaeger';
    return a.role==='lead'?'Jaeger':(a.display_name||a.name||a.id);
  }

  function sortAgents(list){
    return (list||[]).filter(visible).sort((x,y)=>
      ((ORDER[x.role]??2)-(ORDER[y.role]??2))||label(x).localeCompare(label(y)));
  }

  function homeId(a){
    const n=String(a.name||String(a.id||'').split(':').pop()).toLowerCase().replace(/[^a-z0-9_-]/g,'-').slice(0,48)||'jaeger';
    return 'agent-'+n;
  }

  function avatarSvgFor(a){
    const name=String((a&&a.name)||'').toLowerCase();
    const isLead=!a||a.role==='lead'||name==='jaeger'||name==='ares';
    if(isLead){
      return '<svg viewBox="0 0 36 38" width="30" height="32" aria-hidden="true">' +
        '<defs>' +
        '<linearGradient id="jgFlameGrad" x1="0" y1="1" x2="0" y2="0">' +
        '<stop offset="0%" stop-color="#f77f00"/><stop offset="60%" stop-color="#fcbf49"/><stop offset="100%" stop-color="#ffeaa7"/>' +
        '</linearGradient>' +
        '<linearGradient id="jgFlameInner" x1="0" y1="1" x2="0" y2="0">' +
        '<stop offset="0%" stop-color="#d62828"/><stop offset="100%" stop-color="#f77f00"/>' +
        '</linearGradient>' +
        '</defs>' +
        '<path d="M18 1 C14 7, 7 10, 8 18 C9 22, 13 22, 14 20 C14 22, 18 24, 22 20 C23 22, 27 22, 28 18 C29 10, 22 7, 18 1 Z" fill="url(#jgFlameGrad)" stroke="#b02a02" stroke-width="1.2"/>' +
        '<path d="M18 5 C16 9, 12 12, 12 17 C13 19, 15 19, 16 18 C16 19, 18 20, 20 18 C21 19, 23 19, 24 17 C24 12, 20 9, 18 5 Z" fill="url(#jgFlameInner)"/>' +
        '<circle cx="8" cy="23" r="2.5" fill="#fcd5b5" stroke="#70360a" stroke-width="1"/>' +
        '<circle cx="28" cy="23" r="2.5" fill="#fcd5b5" stroke="#70360a" stroke-width="1"/>' +
        '<rect x="9" y="16" width="18" height="14" rx="4" fill="#fcd5b5" stroke="#70360a" stroke-width="1.2"/>' +
        '<circle cx="14" cy="22" r="1.5" fill="#1f140e"/>' +
        '<circle cx="22" cy="22" r="1.5" fill="#1f140e"/>' +
        '<circle cx="12" cy="25" r="1.2" fill="#ff7b72" opacity="0.6"/>' +
        '<circle cx="24" cy="25" r="1.2" fill="#ff7b72" opacity="0.6"/>' +
        '<path d="M16 25.5 Q18 27.5 20 25.5" stroke="#1f140e" stroke-width="1.2" stroke-linecap="round" fill="none"/>' +
        '<path d="M12 30 L12 34 C12 35.5, 24 35.5, 24 34 L24 30 Z" fill="#e76f51" stroke="#70360a" stroke-width="1.2"/>' +
        '<rect x="14" y="30" width="8" height="2" rx="1" fill="#fcd5b5"/>' +
        '</svg>';
    }
    return '<svg viewBox="0 0 36 36" width="28" height="28" aria-hidden="true">' +
      '<defs><linearGradient id="jgAvSpec" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f59e0b"/><stop offset="100%" stop-color="#ea580c"/></linearGradient></defs>' +
      '<rect width="36" height="36" rx="10" fill="url(#jgAvSpec)"/>' +
      '<rect x="9" y="10" width="18" height="15" rx="4" fill="#1e293b"/>' +
      '<circle cx="14.5" cy="17" r="2" fill="#fbbf24"/><circle cx="21.5" cy="17" r="2" fill="#fbbf24"/>' +
      '<line x1="18" y1="5" x2="18" y2="10" stroke="#fff" stroke-width="2" stroke-linecap="round"/>' +
      '</svg>';
  }

  async function getJSON(url,opts){
    const r=await fetch(url,Object.assign({credentials:'same-origin'},opts||{}));
    if(!r.ok)throw new Error(url+' '+r.status);
    return r.json();
  }


  function filterHistoryForSelectedAgent(){
    const drawerTitle=document.querySelector('.agent-history-drawer-title');
    const a=roster.find(x=>x.id===selectedAgentId)||roster[0]||{id:'native:jaeger',name:'jaeger',display_name:'Jaeger',role:'lead'};
    if(drawerTitle) drawerTitle.textContent=label(a)+' \u00b7 History';
    const expectedHome=homeId(a);
    const isLead=(a.role==='lead'||expectedHome==='agent-jaeger');
    const rows=document.querySelectorAll('#sessionList .session-item');
    rows.forEach(row=>{
      const sid=String(row.dataset.sessionId||row.dataset.sid||row.id||'');
      const rowAgent=String(row.dataset.agentId||'');
      if(!sid){ return; }
      if(rowAgent){
        row.style.display=(rowAgent===selectedAgentId)?'':'none';
      }else if(sid.startsWith('agent-')){
        row.style.display=(sid===expectedHome)?'':'none';
      }else{
        const ownerMap=window._jaegerSessionAgentMap||{};
        const mapped=ownerMap[sid];
        if(mapped){
          row.style.display=(mapped===selectedAgentId)?'':'none';
        }else{
          row.style.display=isLead?'':'none';
        }
      }
    });
  }
  window.filterHistoryForSelectedAgent=filterHistoryForSelectedAgent;

  function syncAssistantHeader(agentObj){
    const a=agentObj||roster.find(x=>x.id===selectedAgentId)||roster[0]||{id:'native:jaeger',name:'jaeger',display_name:'Jaeger',role:'lead'};
    const avEl=document.getElementById('assistantHeaderAvatar');
    const nameEl=document.getElementById('appTitlebarTitle');
    const summaryEl=document.getElementById('assistantHeaderSummary');
    if(avEl) avEl.innerHTML=avatarSvgFor(a);
    const summaryText=a.summary||(a.metadata&&a.metadata.summary)||'Personal companion';
    if(nameEl){
      nameEl.textContent=label(a);
      nameEl.title=summaryText;
    }
    if(summaryEl) summaryEl.textContent=summaryText;
    const msgInput=document.getElementById('msg');
    if(msgInput) msgInput.placeholder=window.innerWidth<=768?'Message':('Ask '+label(a)+'\u2026');
    try{filterHistoryForSelectedAgent();}catch(_){}
  }

  async function open(a){
    selectedAgentId=a.id||'native:jaeger';
    syncAssistantHeader(a);
    const s=await getJSON('api/jaeger/agent-home',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_id:a.id})});
    const sid=s.session_id||homeId(a);
    if(typeof window.switchPanel==='function') window.switchPanel('chat',{fromRailClick:true});
    if(typeof window.loadSession==='function') await window.loadSession(sid);
    if(typeof window.renderSessionList==='function') try{Promise.resolve(window.renderSessionList()).then(()=>setTimeout(filterHistoryForSelectedAgent,80));}catch(_){}
    mark(sid);
  }

  function mark(sid){
    document.querySelectorAll('#jaegerAgents [data-home]').forEach(el=>{
      const isMatch=el.dataset.home===sid || el.dataset.agentId===selectedAgentId;
      el.classList.toggle('active',isMatch);
    });
  }

  function toggleHistoryDrawer(force){
    const drawer=document.getElementById('agentHistoryDrawer');
    if(!drawer) return;
    const next=typeof force==='boolean'?force:drawer.hasAttribute('hidden');
    if(next){
      drawer.removeAttribute('hidden');
      if(typeof window.renderSessionList==='function') try{Promise.resolve(window.renderSessionList()).then(()=>setTimeout(filterHistoryForSelectedAgent,80));}catch(_){}
    }else{
      drawer.setAttribute('hidden','');
    }
    const btn=document.getElementById('btnAgentHistoryToggle');
    if(btn) btn.setAttribute('aria-expanded',String(next));
  }
  window.toggleAgentHistoryDrawer=toggleHistoryDrawer;

  function render(root,agents){
    root.innerHTML='';
    const h=document.createElement('div');
    h.className='jaeger-agents-title';
    h.textContent='Agents';
    root.appendChild(h);
    for(const a of agents){
      const b=document.createElement('button');
      b.type='button';
      b.className='jaeger-agent';
      b.dataset.home=homeId(a);
      b.dataset.agentId=a.id||'';
      b.title=a.summary||(a.metadata&&a.metadata.summary)||label(a);
      const av=document.createElement('span');
      av.className='jaeger-agent-avatar';
      av.innerHTML=avatarSvgFor(a);
      const textWrap=document.createElement('span');
      textWrap.className='jaeger-agent-meta';
      const t=document.createElement('span');
      t.className='jaeger-agent-name';
      t.textContent=label(a);
      const sub=document.createElement('span');
      sub.className='jaeger-agent-sub';
      sub.textContent=a.role==='lead'?'Companion':(a.summary||'Specialist');
      textWrap.append(t,sub);
      b.append(av,textWrap);
      b.addEventListener('click',()=>open(a).catch(e=>console.warn('agent open',e)));
      root.appendChild(b);
    }
    const cur=curSid();
    mark(cur||'agent-jaeger');
    syncAssistantHeader();
  }

  function css(){
    if(document.getElementById('jaegerAgentsCss'))return;
    const st=document.createElement('style');
    st.id='jaegerAgentsCss';
    st.textContent=
      '#jaegerAgents{padding:8px 10px 10px;display:flex;flex-direction:column;gap:4px}'+
      '.jaeger-agents-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted,#8e96a8);padding:4px 8px 6px}'+
      '.jaeger-agent{display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border:1px solid transparent;border-radius:12px;background:transparent;color:var(--text,#f3f5f8);font:inherit;text-align:left;cursor:pointer;transition:background .15s ease,border-color .15s ease}'+
      '.jaeger-agent:hover{background:rgba(255,255,255,.06)}'+
      '.jaeger-agent.active{background:rgba(59,130,246,.14);border-color:rgba(59,130,246,.32);font-weight:600}'+
      '.jaeger-agent-avatar{width:28px;height:28px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}'+
      '.jaeger-agent-meta{display:flex;flex-direction:column;min-width:0;flex:1}'+
      '.jaeger-agent-name{font-size:13.5px;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'+
      '.jaeger-agent-sub{font-size:11px;line-height:1.2;color:var(--text-muted,#8e96a8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}';
    document.head.appendChild(st);
  }

  function chipText(sess){
    const a=roster.find(x=>x.id===(sess.agent_id||'native:jaeger'));
    return 'with '+(a?label(a):(sess.display_name||'Jaeger'));
  }
  function menuItems(sess){
    const cur=sess.agent_id||'native:jaeger', sug=(sess.metadata||{}).suggested_agent_id;
    return roster.filter(a=>a.id!==cur).map(a=>({id:a.id,text:(a.id===sug?'★ Suggested: ':'Hand off to ')+label(a)}))
      .sort((x,y)=>(y.text.startsWith('★'))-(x.text.startsWith('★')));
  }
  function routedNotice(sess){
    const m=sess.metadata||{};if(m.routed_by!=='auto'||!m.previous_agent_id)return null;
    const a=roster.find(x=>x.id===sess.agent_id);return {text:'Jaeger handed this to '+(a?label(a):sess.agent_id),undoTo:m.previous_agent_id};
  }

  async function boot(){
    const staleChip=document.getElementById('jaegerAgentChip');
    if(staleChip) staleChip.remove();
    const nav=document.getElementById('sidebarPrimaryNav');
    const panelChat=document.getElementById('panelChat');
    if(!panelChat)return;
    let root=document.getElementById('jaegerAgents');
    if(!root){
      root=document.createElement('div');
      root.id='jaegerAgents';
      if(nav) panelChat.insertBefore(root,nav);
      else panelChat.appendChild(root);
    }
    css();
    try{
      const d=await getJSON('api/agents');
      roster=sortAgents(d.agents||d||[]);
      if(!roster.length){
        roster=[{id:'native:jaeger',name:'jaeger',display_name:'Jaeger',role:'lead',kind:'native'}];
      }
      render(root,roster);
    }catch(e){
      roster=[{id:'native:jaeger',name:'jaeger',display_name:'Jaeger',role:'lead',kind:'native'}];
      render(root,roster);
    }
  }

  window.jaegerAgents={sortAgents,label,homeId,boot,chipText,menuItems,routedNotice,toggleHistoryDrawer,syncAssistantHeader,setRoster:r=>{roster=sortAgents(r);}};
  if(typeof document!=='undefined'&&document.readyState!=='loading')boot();else document.addEventListener('DOMContentLoaded',boot);
})();
