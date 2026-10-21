/* Real UI→proxy→Gateway→approval→tool→disk/Stop verification, model boundary scripted.
 * node dev/scripts/verify_blueprint_effects.mjs <external playwright index.mjs> <fixture listener.json> <external evidence dir>
 */
import { readFile, writeFile, mkdir, access } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const [modulePath, listenerPath, evidence]=process.argv.slice(2);
if(!modulePath||!listenerPath||!evidence)throw new Error('Require module, owned listener and external evidence paths');
const {chromium}=await import(pathToFileURL(path.resolve(modulePath)));
const target=JSON.parse(await readFile(listenerPath,'utf8'));
if(!target.state.includes('/.jaeger/verification/')||[8790,33418].includes(target.webui_port)||[8790,33418].includes(target.gateway_port))throw new Error('Refuse production/nonfixture target');
await mkdir(evidence,{recursive:true});
const base=`http://127.0.0.1:${target.webui_port}`;
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({baseURL:base,viewport:{width:1280,height:900}});
const proof={target:{...target},checks:[],receipts:[],errors:[]};
page.on('pageerror',error=>proof.errors.push(String(error)));
const exists=async p=>{try{await access(p);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}};
const bounded=async(fn,label)=>{const end=Date.now()+20000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw new Error(label);};
const api=async(p,body)=>{
 const r=body?await page.request.post(p,{data:body}):await page.request.get(p);if(!r.ok())throw new Error(`Fixture API ${p}: ${r.status()}`);return r.json();
};
try {
 const agents={};
 const stopOnly=process.argv.includes('--stop-only');
 for(const kind of ['deny','allow','process']) {
  if(stopOnly) {const catalog=await api('/v1/agents');agents[kind]=catalog.agents.find(a=>a.name==='blueprint-effect-'+kind);if(!agents[kind])throw new Error('Missing owned fixture agent');continue;}
  agents[kind]=await api('/v1/agents',{name:'blueprint-effect-'+kind,display_name:'Effect '+kind,role:'specialist',kind:'jaeger_native',metadata:{allowed_tools:kind==='process'?['terminal']:['write_file']}});
 }
 await page.goto('/?host=web');
 for(const decision of (stopOnly?[]:['deny','allow'])) {
  const exactFile=path.join(target.state,'instances/fixture/workspace',decision==='allow'?'allowed.txt':'denied.txt');
  if(await exists(exactFile))throw new Error('Fresh fixture effect already exists; never reuse this case');
  await page.getByRole('button',{name:new RegExp('Effect '+decision)}).first().click();
  await page.getByRole('textbox',{name:'Message',exact:true}).fill('BLUEPRINT-WRITE-'+decision.toUpperCase());
  let requestId;const listener=req=>{if(req.url().endsWith('/turns')&&req.method()==='POST')requestId=req.postDataJSON().request_id;};page.on('request',listener);
  await page.getByRole('button',{name:'Send',exact:true}).click();
  const button=page.getByRole('button',{name:decision==='allow'?/^Allow once$/:/^Deny once/});
  await button.waitFor({timeout:20000});
  if(await exists(exactFile))throw new Error('Tool effect occurred before the decision');
  // Force real reload while pending. Recover the existing approval/request; never resubmit.
  await page.reload();await page.getByRole('button',{name:new RegExp('Effect '+decision)}).first().click();
  await button.waitFor({timeout:20000});
  await button.click();
  await bounded(async()=>['completed','cancelled','failed','execution_unknown'].includes((await api(`/v1/sessions/${encodeURIComponent('agent-'+agents[decision].id)}/requests/${requestId}`)).status),'No authoritative tool settlement');
  const receipt=await api(`/v1/sessions/${encodeURIComponent('agent-'+agents[decision].id)}/requests/${requestId}`);proof.receipts.push({request_id:requestId,status:receipt.status});
  if(decision==='allow') {
   if(await readFile(exactFile,'utf8')!=='BLUEPRINT-VERIFIED-BYTES')throw new Error('Actual write bytes differ');
  } else if(await exists(exactFile))throw new Error('Denied tool produced a file');
  proof.checks.push(`${decision}: pending survives actual reload; exact file effect ${decision==='allow'?'present':'absent'}`);
  await page.screenshot({path:path.join(evidence,`effect-${decision}.png`)});page.off('request',listener);
 }
 await page.getByRole('button',{name:/Effect process/}).first().click();
 await page.getByRole('textbox',{name:'Message',exact:true}).fill('BLUEPRINT-PROCESS');
 let cancelCount=0;page.on('request',req=>{if(req.url().endsWith('/cancel'))cancelCount++;});
 await page.getByRole('button',{name:'Send',exact:true}).click();
 await page.getByRole('button',{name:'Allow once',exact:true}).click({timeout:20000});
 const pidFile=path.join(target.state,'instances/fixture/workspace/owned-process.pid');
 await bounded(()=>exists(pidFile),'Owned subprocess did not start');
 const pid=Number(await readFile(pidFile,'utf8'));if(!Number.isSafeInteger(pid)||pid<=1)throw new Error('Invalid owned fixture PID');
 await page.getByRole('button',{name:'Stop (⌘Esc)',exact:true}).evaluate(button=>{button.click();button.click();});
 await bounded(async()=>{try{process.kill(pid,0);return false;}catch(e){if(e.code==='ESRCH')return true;throw e;}},'Stop did not terminate owned subprocess');
 if(cancelCount!==1)throw new Error('Expected one cancellation intent; got '+cancelCount);
 const sessionId='agent-'+agents.process.id;
 await bounded(async()=> (await api(`/v1/sessions/${encodeURIComponent(sessionId)}?view=control`)).latest_request?.status==='cancelled','Owned process gone but request did not settle cancelled');
 const terminal=(await api(`/v1/sessions/${encodeURIComponent(sessionId)}?view=control`)).latest_request;
 proof.receipts.push({request_id:terminal.request_id,status:terminal.status});
 proof.checks.push('Stop double click produced one cancellation intent and owned OS process disappeared');
 await page.screenshot({path:path.join(evidence,'stop.png')});
 if(proof.errors.length)throw new Error('Browser page errors: '+proof.errors.join(';'));
 await writeFile(path.join(evidence,'result.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
} catch(error) {
 proof.error=String(error);await page.screenshot({path:path.join(evidence,'failure.png')});await writeFile(path.join(evidence,'failure.json'),JSON.stringify(proof,null,2));throw error;
} finally {await browser.close();}
