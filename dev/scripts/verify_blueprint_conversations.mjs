/* Owned-browser acceptance. No production ports, credentials, external messages or uncertain replay. */
import {readFile,writeFile,mkdir,access} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
const [modulePath,listenerPath,evidence]=process.argv.slice(2);
const {chromium}=await import(pathToFileURL(path.resolve(modulePath)));
const target=JSON.parse(await readFile(listenerPath,'utf8'));
if(!target.state.includes('/.jaeger/verification/blueprint-')||[8790,33418].includes(target.webui_port)||[8790,33418].includes(target.gateway_port))throw new Error('Refuse nonfixture target');
await mkdir(evidence,{recursive:true});const profile=path.resolve(evidence,'owned-browser-profile');
try{await access(profile);throw new Error('Refuse reuse of prior browser scenario');}catch(e){if(e.code!=='ENOENT')throw e;}
const base=`http://127.0.0.1:${target.webui_port}`;const runId=randomUUID().slice(0,8);let context,page;const proof={checks:[],requests:[],errors:[],source_sha256:target.source_sha256};
const launch=async()=>{context=await chromium.launchPersistentContext(profile,{headless:true,baseURL:base,viewport:{width:1280,height:900}});page=await context.newPage();page.on('pageerror',e=>proof.errors.push(String(e)));await page.goto('/?host=web');};
const api=async(url,body)=>{const r=body?await page.request.post(url,{data:body}):await page.request.get(url);if(!r.ok())throw new Error(`${url}: ${r.status()}`);return r.json();};
const openBot=async(name)=>{await page.getByRole('button',{name:new RegExp(name)}).first().click();await page.getByRole('textbox',{name:'Message',exact:true}).waitFor();};
const draftText=()=>page.getByRole('textbox',{name:'Message',exact:true});
const saved=async(sessionId)=>page.evaluate(id=>new Promise((resolve,reject)=>{const q=indexedDB.open('jaeger.ui.drafts',1);q.onerror=()=>reject(q.error);q.onsuccess=()=>{const db=q.result,r=db.transaction('drafts').objectStore('drafts').get(id);r.onsuccess=()=>{resolve(r.result);db.close();};};}),sessionId);
const wait=async(fn,label)=>{const end=Date.now()+20000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,50));}throw new Error(label);};
try{
 await launch();
 const agents={};for(const label of ['Alpha','Beta'])agents[label]=await api('/v1/agents',{name:'journey-'+label.toLowerCase()+'-'+runId,display_name:'Journey '+label+' '+runId,role:'specialist',kind:'jaeger_native',metadata:{allowed_tools:['read_file']}});
 await page.reload();await openBot('Journey Alpha '+runId);await draftText().fill('BLUEPRINT-PING');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByText('BLUEPRINT-ANSWER',{exact:true}).waitFor({timeout:20000});
 await page.locator('.jg-bubble--assistant').filter({hasText:'BLUEPRINT-ANSWER'}).last().click({button:'right'});await page.getByRole('menuitem').filter({hasText:'Reply'}).click();
 await draftText().fill('DRAFT-D1');await draftText().fill('DRAFT-D2');await draftText().fill('BLUEPRINT-DRAFT-D3');
 const bytes=Buffer.from('BLUEPRINT-OWNED-ATTACHMENT');
 await page.locator('input[type=file]').setInputFiles({name:'blueprint.txt',mimeType:'text/plain',buffer:bytes});
 const alphaHome='agent-'+agents.Alpha.id;
 await wait(async()=>{const d=await saved(alphaHome);return d?.text==='BLUEPRINT-DRAFT-D3'&&d.quote?.text.includes('BLUEPRINT-ANSWER')&&d.files?.[0]?.data===bytes.toString('base64');},'Draft D3/quote/file bytes not durable');
 const before=await saved(alphaHome);
 await openBot('Journey Beta '+runId);await draftText().fill('BETA-INDEPENDENT');await openBot('Journey Alpha '+runId);await wait(async()=>await draftText().inputValue()==='BLUEPRINT-DRAFT-D3','Draft crossed bot ownership');
 // Kill only this owned headless browser, after its IndexedDB transaction completed.
 const lines=execFileSync('ps',['-axo','pid,command'],{encoding:'utf8'}).split('\n').filter(l=>l.includes('--user-data-dir='+profile)&&!l.includes('--type='));
 if(lines.length!==1)throw new Error('Cannot identify exact owned browser PID; no crash performed');
 const browserPid=Number(lines[0].trim().split(/\s+/)[0]);process.kill(browserPid,'SIGKILL');await context.close().catch(()=>{});
 await launch();await openBot('Journey Alpha '+runId);await wait(async()=>await draftText().inputValue()==='BLUEPRINT-DRAFT-D3','Crash lost saved draft');
 const after=await saved(alphaHome);
 if(after.quote?.text!==before.quote.text||after.files[0]?.id!==before.files[0].id||after.files[0].data!==before.files[0].data)throw new Error('Crash changed quote/file identity or bytes');
 await page.getByRole('button',{name:'Cancel reply',exact:true}).click();if(await draftText().inputValue()!=='BLUEPRINT-DRAFT-D3')throw new Error('Cancel quote changed body');
 proof.checks.push('D3 text, separate quote and exact staged file ID/bytes survive navigation and actual owned-browser crash; cancelling quote preserves body');
 let selected;const capture=r=>{if(r.method()==='POST'&&r.url().endsWith('/turns')){selected=r.postDataJSON();proof.requests.push(selected.request_id);}};page.on('request',capture);
 await page.getByRole('button',{name:'Send',exact:true}).click();await wait(async()=>selected?.attachment_ids?.length===1,'Selected file IDs were not submitted');
 await wait(async()=> (await api(`/v1/sessions/${encodeURIComponent(alphaHome)}/requests/${selected.request_id}`)).status==='completed','Uploaded turn did not settle');
 const attachments=await api(`/v1/sessions/${encodeURIComponent(alphaHome)}/attachments`);const list=Array.isArray(attachments)?attachments:attachments.attachments;
 const uploaded=list.find(a=>a.attachment_id===selected.attachment_ids[0]);
 if(uploaded?.sha256!==createHash('sha256').update(bytes).digest('hex'))throw new Error('Gateway staged bytes/hash mismatch');
 proof.checks.push('Actual bytes upload committed exactly the selected attachment ID with exact SHA256');
 await wait(async()=> (await saved(alphaHome))?.text==='','Accepted draft did not clear');
 let posts=0;await page.route('**/v1/sessions/*/turns',async route=>{posts++;await route.fetch();await route.abort('failed');});
 await draftText().fill('BLUEPRINT-LOST-ADMISSION');await page.getByRole('button',{name:'Send',exact:true}).click();
 await wait(async()=>selected?.text==='BLUEPRINT-LOST-ADMISSION'&&(await api(`/v1/sessions/${encodeURIComponent(alphaHome)}/requests/${selected.request_id}`)).status==='completed','Lost reply not reconciled');
 await wait(async()=> (await saved(alphaHome))?.text==='','Lost reply left accepted draft uncleared');if(posts!==1)throw new Error('Lost response caused duplicate POST');await page.unroute('**/v1/sessions/*/turns');
 proof.checks.push('One POST after admission-response loss; same-ID lookup recovers completion without resend');
 const nonce=randomUUID(),body={text:'BLUEPRINT-NONCE',request_id:nonce,attachment_ids:[]};await api(`/v1/sessions/${encodeURIComponent(alphaHome)}/turns`,body);
 const replay=await api(`/v1/sessions/${encodeURIComponent(alphaHome)}/turns`,body);if(!replay.replayed)throw new Error('Repeated intent not replayed');
 const conflict=await page.request.post(`/v1/sessions/${encodeURIComponent(alphaHome)}/turns`,{data:{...body,text:'changed'}});if(conflict.status()!==409)throw new Error('Changed intent not rejected');
 await wait(async()=> (await api(`/v1/sessions/${encodeURIComponent(alphaHome)}/requests/${nonce}`)).status==='completed','Nonce fixture not settled');
 proof.checks.push('Same nonce replays original receipt; changed text conflicts409 without overwrite');
 await page.reload();await openBot('Journey Alpha '+runId);await draftText().fill('BLUEPRINT-SLOW');await page.getByRole('button',{name:'Send',exact:true}).click();
 await page.locator('.jg-bubble--assistant').filter({hasText:'SLOW-0'}).last().waitFor({timeout:20000});
 const slowId=selected.request_id;await openBot('Journey Beta '+runId);if(await draftText().inputValue()!=='BETA-INDEPENDENT')throw new Error('Background request damaged Beta draft');
 await openBot('Journey Alpha '+runId);await context.setOffline(true);await new Promise(r=>setTimeout(r,300));await context.setOffline(false);
 await page.locator('.jg-bubble--assistant').filter({hasText:'SLOW-19'}).last().waitFor({timeout:20000});
 if(proof.requests.filter(id=>id===slowId).length!==1)throw new Error('Reconnect replayed submission');proof.checks.push('Background accepted turn and isolated offline/reconnect retain result without duplicate submit');
 await openBot('Researcher');await page.getByRole('button',{name:'Check saved request',exact:true}).waitFor({timeout:20000});await draftText().fill('UNSENT-WHILE-UNKNOWN');const count=proof.requests.length;
 await page.getByRole('button',{name:'Check saved request',exact:true}).click();await page.getByRole('button',{name:'Check saved request',exact:true}).waitFor();
 if(!(await page.getByRole('button',{name:'Send',exact:true}).isDisabled())||await draftText().inputValue()!=='UNSENT-WHILE-UNKNOWN'||proof.requests.length!==count)throw new Error('Unknown recovery resent or cleared device draft');
 proof.checks.push('Seeded canonical unknown is rediscovered without local journal; check preserves own draft and cannot submit/replay');
 await openBot('Builder');await page.getByText('BLUEPRINT-HISTORY-130',{exact:true}).waitFor();
 for(let i=0;i<4;i++){
  await wait(async()=>!(await page.getByText('Loading earlier messages…',{exact:true}).count()),'Older page did not settle');
  if(await page.getByText('BLUEPRINT-HISTORY-001',{exact:true}).count())break;
  await page.getByRole('button',{name:'Show earlier messages',exact:true}).click();
 }
 await page.getByText('BLUEPRINT-HISTORY-001',{exact:true}).waitFor();if(await page.getByText('BLUEPRINT-HISTORY-050',{exact:true}).count()!==1)throw new Error('Duplicate paged entry');proof.checks.push('130 canonical seeded history entries remain inline and unique');
 const html=await (await page.request.get('/')).body();if(!html.equals(await readFile(path.join(target.dist,'index.html'))))throw new Error('Served build differs');proof.assets={};
 for(const match of html.toString().matchAll(/(?:src|href)="\.\/([^\"]+\.(?:js|css))"/g)){const data=await(await page.request.get('/'+match[1])).body();if(!data.equals(await readFile(path.join(target.dist,match[1]))))throw new Error('Asset mismatch');proof.assets[match[1]]=createHash('sha256').update(data).digest('hex');}
 await page.screenshot({path:path.join(evidence,'conversation.png')});if(proof.errors.length)throw new Error('Browser errors '+proof.errors.join(';'));
 await writeFile(path.join(evidence,'result.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
}catch(error){proof.error=String(error);await page?.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{});await writeFile(path.join(evidence,'failure.json'),JSON.stringify(proof,null,2));throw error;}
finally{await context?.close().catch(()=>{});}
