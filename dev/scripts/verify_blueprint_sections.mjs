/* Owned fixture UI→authenticated proxy→canonical presentation store; no execution changes. */
import {readFile,writeFile,mkdir} from 'node:fs/promises';import {pathToFileURL} from 'node:url';import path from 'node:path';import {randomUUID} from 'node:crypto';
const [modulePath,listenerPath,evidence]=process.argv.slice(2);const {chromium}=await import(pathToFileURL(path.resolve(modulePath)));const target=JSON.parse(await readFile(listenerPath,'utf8'));
if(!target.state.includes('/.jaeger/verification/blueprint-')||[8790,33418].includes(target.webui_port))throw Error('Refuse production');
await mkdir(evidence,{recursive:true});const b=await chromium.launch({headless:true});const p=await b.newPage({baseURL:`http://127.0.0.1:${target.webui_port}`,viewport:{width:1280,height:900}});const checks=[];
const api=async(url,data,method)=>{const r=await p.request.fetch(url,{method:method??(data?'POST':'GET'),data});if(!r.ok())throw Error(`${url} ${r.status()}`);return r.json();};
try{
await p.goto('/?host=web');const suffix=randomUUID().slice(0,8),name='Section Fixture '+suffix;
const agent=await api('/v1/agents',{name:'section-fixture-'+suffix,display_name:name,role:'specialist',kind:'jaeger_native',metadata:{allowed_tools:['read_file']}});
const section=await api('/v1/sections',{name:'Owned section '+suffix});const original=await api('/v1/agents/'+encodeURIComponent(agent.id));const home=await api('/v1/agents/'+encodeURIComponent(agent.id)+'/home');
const open=async()=>{await p.getByRole('button',{name:new RegExp(name)}).first().click({button:'right'});await p.getByRole('menuitem',{name:/^Move to/}).click();await p.getByRole('menu',{name:'Move bot to section'}).waitFor();};
await p.reload();await open();await p.getByRole('menuitemradio',{name:section.name,exact:true}).click();await p.getByText('Sidebar section updated',{exact:true}).waitFor();
await p.reload();await open();if(await p.getByRole('menuitemradio',{name:section.name,exact:true}).getAttribute('aria-checked')!=='true')throw Error('Membership not durable');checks.push('Existing section move persisted and restored after reload');
await p.screenshot({path:path.join(evidence,'move-existing.png')});await p.keyboard.press('Escape');await p.keyboard.press('Escape');
let rejected=false;await p.route('**/v1/agents/'+encodeURIComponent(agent.id),async route=>{if(route.request().method()==='PATCH'){rejected=true;await route.continue({postData:JSON.stringify({section_id:'section_'+'0'.repeat(32)})});}else await route.continue();});
await open();await p.getByRole('menuitemradio',{name:'Unassigned',exact:true}).click();await p.getByText(/Couldn't update agent presentation/).waitFor();if(!rejected)throw Error('Rejection not exercised');await p.unroute('**/v1/agents/'+encodeURIComponent(agent.id));
if((await api('/v1/agents/'+encodeURIComponent(agent.id))).section_id!==section.id)throw Error('Rejected move changed membership');checks.push('Actual backend rejects unknown section; UI reports failure, membership unchanged');
await open();await p.getByRole('menuitemradio',{name:'Unassigned',exact:true}).click();await p.getByText('Sidebar section updated',{exact:true}).waitFor();await p.reload();
const current=await api('/v1/agents/'+encodeURIComponent(agent.id));if(current.section_id!==null)throw Error('Unassigned not persisted');
for(const key of ['id','role','kind','metadata','tools','permissions'])if(JSON.stringify(original[key])!==JSON.stringify(current[key]))throw Error('Execution identity changed: '+key);
if((await api('/v1/agents/'+encodeURIComponent(agent.id)+'/home')).session_id!==home.session_id)throw Error('History ownership changed');checks.push('Unassigned persists; immutable identity, execution configuration and home ID unchanged');
await writeFile(path.join(evidence,'result.json'),JSON.stringify({checks,agent_id:agent.id,section_id:section.id,home_session_id:home.session_id,time:new Date().toISOString()},null,2));console.log(checks);
}catch(e){await p.screenshot({path:path.join(evidence,'failure.png')});throw e;}finally{await b.close();}
