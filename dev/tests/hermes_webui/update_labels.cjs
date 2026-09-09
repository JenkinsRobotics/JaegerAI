// Run against the assembled overlay: node update_labels.cjs /path/to/staged/static/ui.js
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
function extract(name) {
  const start = source.indexOf('function '+name+'(');
  assert(start >= 0, name);
  const tail = source.slice(start);
  const next = tail.slice(1).search(/\n(?:async )?function /);
  return next < 0 ? tail : tail.slice(0,next+1);
}
const elements = new Map();
const context = vm.createContext({window:{}, URL, t:(_,fallback)=>fallback,
  $:id=> {
    if(!elements.has(id)) elements.set(id,{style:{},dataset:{},classList:{add(){},remove(){}}});
    return elements.get(id);
  },
  _renderUpdateWhatsNewLinks(){}
});
for(const name of ['_updateApplyTargets','_updateApplyLabel','_formatUpdateTargetStatus',
  '_formatManualUpdateInstruction','_isSafeUpdateCompareUrl','_updateCompareUrl',
  '_updateWhatsNewTargets','_showUpdateBanner']) vm.runInContext(extract(name),context);
const agent={behind:1,current_version:'v1',latest_version:'v2',release_based:true,compare_url:'https://example.org/agent'};
const webui={...agent,compare_url:'https://example.org/webui'};
for(const [data,label] of [
  [{agent},'Update Hermes Agent'],
  [{webui},'Update Hermes WebUI'],
  [{agent,webui},'Update Hermes Agent + Hermes WebUI'],
  [{agent,webui:{...webui,manual_update:true}},'Update Hermes Agent'],
  [{},'No automatic updates'],
]) {
  context._showUpdateBanner(data);
  assert.equal(elements.get('btnApplyUpdate').textContent,label);
  if(data.agent) assert.match(elements.get('updateMsg').textContent,/Hermes Agent/);
  if(data.webui) assert.match(elements.get('updateMsg').textContent,/Hermes WebUI/);
  if(data.agent||data.webui) assert.match(elements.get('updateMsg').textContent,/JaegerAI and OpenClaw are not checked here/);
}
assert.deepEqual(Array.from(context._updateWhatsNewTargets({agent,webui}), x=>x.label),['Hermes WebUI','Hermes Agent']);
assert.deepEqual(Array.from(context._updateApplyTargets({agent,webui:{...webui,manual_update:true}})),['agent']);
console.log('Update labels: 5 banner cases, release-link identities and apply target mapping passed.');
