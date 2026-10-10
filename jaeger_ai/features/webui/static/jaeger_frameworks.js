// Other agent frameworks on this Mac: what was detected, and the owner's
// per-framework grants. Nothing is read until the owner turns a grant on here.
(function(){
  'use strict';
  const CAP_LABEL={read_sessions:'Read sessions',read_memory:'Read memory',delegate:'Hand tasks to it'};
  async function getJSON(url,opts){const r=await fetch(url,Object.assign({credentials:'same-origin'},opts||{}));if(!r.ok)throw new Error(url+' '+r.status);return r.json();}
  function confirmText(fw,cap,on){
    if(!on)return 'Revoke "'+CAP_LABEL[cap]+'" for '+fw.name+'?';
    if(cap==='delegate')return 'Allow Jaeger to hand tasks to '+fw.name+'?\n\nEach handoff still asks for your approval before it runs.';
    return 'Allow Jaeger to read '+fw.name+' '+(cap==='read_sessions'?'session history':'memory files')+'?\n\n'+
      'Read-only and local: content stays on this Mac, is treated as untrusted, and login/token files are never opened.';
  }
  function row(fw,caps,onToggle){
    const tr=document.createElement('tr');
    const name=document.createElement('td');name.innerHTML='';const b=document.createElement('b');b.textContent=fw.name;name.appendChild(b);
    const sub=document.createElement('div');sub.className='jf-sub';
    sub.textContent=fw.installed?[fw.data_root,fw.cli?('CLI '+fw.cli):'',(fw.apps||[]).join(', '),fw.counts?(fw.counts.sessions+' sessions · '+fw.counts.memory+' memory files'):'',fw.notes].filter(Boolean).join(' · '):'not installed';
    name.appendChild(sub);tr.appendChild(name);
    for(const c of caps){
      const td=document.createElement('td');
      const usable=fw.installed&&(c==='delegate'?!!fw.handoff:fw.readable);
      if(!usable){td.textContent='—';td.className='jf-na';}
      else{const cb=document.createElement('input');cb.type='checkbox';cb.checked=!!(fw.grants||{})[c];cb.dataset.fw=fw.id;cb.dataset.cap=c;
        cb.addEventListener('change',()=>onToggle(fw,c,cb));td.appendChild(cb);}
      tr.appendChild(td);
    }
    return tr;
  }
  async function toggle(fw,cap,cb){
    const on=cb.checked;
    if(!window.confirm(confirmText(fw,cap,on))){cb.checked=!on;return;}
    try{await getJSON('api/jaeger/frameworks/'+encodeURIComponent(fw.id)+'/grants',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capability:cap,granted:on})});}
    catch(e){cb.checked=!on;console.warn('grant',e);}
  }
  async function open(){
    let dlg=document.getElementById('jaegerFrameworks');
    if(!dlg){dlg=document.createElement('div');dlg.id='jaegerFrameworks';document.body.appendChild(dlg);css();}
    dlg.hidden=false;dlg.innerHTML='<div class="jf-card"><div class="jf-head"><b>Agent frameworks on this Mac</b><button type="button" class="jf-x">×</button></div><div class="jf-body">Detecting…</div></div>';
    dlg.querySelector('.jf-x').onclick=()=>{dlg.hidden=true;};
    const d=await getJSON('api/jaeger/frameworks?refresh=1');
    const caps=d.capabilities||Object.keys(CAP_LABEL);
    const t=document.createElement('table');const h=document.createElement('tr');
    h.innerHTML='<th>Framework</th>'+caps.map(c=>'<th>'+CAP_LABEL[c]+'</th>').join('');t.appendChild(h);
    const list=(d.frameworks||[]).slice().sort((a,b)=>(b.installed-a.installed));
    for(const fw of list)t.appendChild(row(fw,caps,toggle));
    const body=dlg.querySelector('.jf-body');body.innerHTML='';
    const p=document.createElement('p');p.className='jf-sub';p.textContent='Detected by file and app presence only. Nothing is read until you allow it here; you can revoke at any time.';
    body.appendChild(p);body.appendChild(t);
  }
  function css(){
    const st=document.createElement('style');
    st.textContent='#jaegerFrameworks{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;display:flex;align-items:center;justify-content:center}#jaegerFrameworks[hidden]{display:none}'+
      '.jf-card{background:var(--bg,#14161a);color:inherit;border:1px solid rgba(127,127,127,.35);border-radius:12px;width:min(920px,94vw);max-height:84vh;overflow:auto;padding:14px 18px}'+
      '.jf-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}.jf-x{background:transparent;border:0;color:inherit;font-size:20px;cursor:pointer}'+
      '#jaegerFrameworks table{width:100%;border-collapse:collapse;font-size:13px}#jaegerFrameworks th,#jaegerFrameworks td{padding:7px 8px;border-bottom:1px solid rgba(127,127,127,.18);text-align:left;vertical-align:top}'+
      '.jf-sub{opacity:.65;font-size:11.5px;margin-top:2px;word-break:break-all}.jf-na{opacity:.4}';
    document.head.appendChild(st);
  }
  window.jaegerFrameworks={open,confirmText};
})();
