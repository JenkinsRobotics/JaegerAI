#!/usr/bin/env node
// Isolated component/browser regression: real UI components + CSS, no live account/session writes.
// Run from interfaces/ui: node scripts/phone-chat-regression.mjs [/tmp/output-directory]
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
const out = process.argv[2] ?? '/tmp/jaeger-phone-chat-regression';
mkdirSync(out, { recursive: true });
const fixture = `
import React from 'react';
import {createRoot} from 'react-dom/client';
import '@aether/ui/tokens.css';
import '@aether/ui/widgets.css';
import '/src/shell/tokens.jaeger.css';
import '/src/shell/feels.css';
import '/src/shell/shell.css';
import '/src/shell/presets.css';
import '/src/chat/chat.css';
import '/src/settings/settings.css';
import '/src/avatar/avatar.css';
import '/src/unified/unified.css';
import '/src/phone/phone.css';
import {MinimalChat} from '/src/chat/MinimalChat';
import {WebHost} from '/src/chat/webHost';
import {PhoneChat} from '/src/phone/PhoneShell';
import {AppChrome} from '/src/shell/AppChrome';
import {applyPreset} from '/src/shell/layoutPresets';
applyPreset('glass');
document.documentElement.classList.add('jg-phone', 'aether-light-theme');
const source = {
 kind:'live', agents:async()=>[{id:'builder',name:'Builder'}],
 session:async()=>({session_id:'fixture',agent_id:'builder',messages:[
  ...Array.from({length:location.search.includes('short')?0:30},(_,i)=>[{role:'user',request_id:'old-'+i,content:'Earlier message '+i,timestamp:1793470740+i}, {role:'assistant',request_id:'old-'+i,content:'A previous response for scroll verification. '+i}]).flat(),
  {role:'user',request_id:'current',content:'Ping from a Safari check. Please reply with the single word pong.',timestamp:1793470790}]}),
 sessionControl:async()=>({latest_request:{request_id:'current',status:'running'}}),
 requestStatus:async()=>({session_id:'fixture',request_id:'current',status:window.fixtureFinished?'completed':'running',input_text:'Ping from a Safari check. Please reply with the single word pong.',result:window.fixtureFinished?{output:window.fixtureAnswer}:undefined}),
 pendingApprovals:async()=>[], clarifications:async()=>[],
 stream:async(_s,_c,emit,signal)=>{window.fixtureEmit=emit;await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));},
 send:async()=>{throw Error('Regression fixture must never send execution');},
};
window.fixtureAnswer='';window.fixtureSeq=1;
window.fixtureToken=(delta)=>{window.fixtureAnswer+=delta;window.fixtureEmit({event:'turn.delta',event_id:window.fixtureSeq++,request_id:'current',payload:{delta}});};
window.fixtureFinish=()=>{window.fixtureFinished=true;window.fixtureEmit({event:'turn.finish',event_id:window.fixtureSeq++,request_id:'current',payload:{output:window.fixtureAnswer}});};
const host=new WebHost(source);
createRoot(document.getElementById('root')).render(<AppChrome active="chat" pages={['chat','home','tasks','settings']} phone onPick={()=>{}} onSearch={()=>{}}><PhoneChat agentId="builder" agentName="Builder" onBack={()=>{}} onInfo={()=>{}}><div className="jg-av-chat"><div className="jg-chat-voice-host"><MinimalChat host={host} sessionId="fixture"/></div></div></PhoneChat></AppChrome>);
`;
const plugin = {
 name: 'isolated-phone-chat-regression',
 resolveId(id) { if (id === '/__phone-regression.tsx') return path.join(process.cwd(), '__phone-regression.tsx'); },
 load(id) { if (id === path.join(process.cwd(), '__phone-regression.tsx')) return fixture; },
 configureServer(server) {
  server.middlewares.use('/__phone-check', async (_req, res) => {
   const html = await server.transformIndexHtml('/__phone-check', '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>html,body,#root{height:100%;margin:0}#root{display:flex}</style></head><body><div id="root"></div><script type="module" src="/__phone-regression.tsx"></script></body></html>');
   res.setHeader('Content-Type','text/html');res.end(html);
  });
 }
};
const server = await createServer({plugins:[plugin],server:{host:'127.0.0.1',port:0,open:false}});
let browser;
try {
 await server.listen();
 const base = server.resolvedUrls.local[0];
 browser = await chromium.launch({headless:true});
 const context = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:1});
 // No test request may escape to the live gateway or an external host.
 await context.route('**/*', route => {
  const url=new URL(route.request().url());
  if(url.origin!==new URL(base).origin || /^\/(api|v1)\//.test(url.pathname)) return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  return route.continue();
 });
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>{errors.push(String(e));console.error('browser:',String(e));});page.on('console',m=>{if(m.type()==='error')console.error('console:',m.text());});
 await page.goto(base+'__phone-check');
 try { await page.waitForFunction(()=>typeof window.fixtureEmit==='function',{},{timeout:10000}); } catch(e) { await page.screenshot({path:path.join(out,'startup-failed.png')});console.error((await page.locator('body').innerText()).slice(0,5000));throw e; }
 await page.waitForFunction(()=>!document.body.textContent.includes('Checking saved work'));
 const geometry=()=>page.evaluate(()=>{
  const rect=sel=>{const r=document.querySelector(sel).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height};};
  const scroll=document.querySelector('.jg-chat__scroll');
  const turns=[...document.querySelectorAll('.jg-turn')];
  return {composer:rect('.jg-composer'),input:rect('.jg-composer__input'),bar:rect('.jg-composer__bar'),tabs:rect('.phone-tabs'),header:rect('.jg-pbar'),last:(()=>{const r=turns.at(-1).getBoundingClientRect();return {top:r.top,bottom:r.bottom}})(),voice:document.querySelector('.jg-voice')?rect('.jg-voice'):null,gap:scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop,scrollHeight:scroll.scrollHeight,scrollClient:scroll.clientHeight,overflowX:document.documentElement.scrollWidth>innerWidth};
 });
 const validate=g=>{
  assert(g.composer.bottom<=g.tabs.top-8,'composer overlaps floating tabs');
  assert(g.input.bottom<=g.bar.top,'input overlaps composer controls');
  assert(g.last.bottom<=g.composer.top,'latest message overlaps composer');
  assert(g.composer.top-g.last.bottom<=20,'unexpected void above composer');
  assert(g.gap<=2,'latest message is not followed');
  assert(!g.overflowX,'horizontal overflow');
  if(g.voice) { assert(g.voice.top>=g.bar.top && g.voice.bottom<=g.bar.bottom,'dictation must stay in the composer control bar'); assert(g.voice.left>=g.input.left && g.voice.right<=g.input.right,'dictation leaves the composer width'); }
 };
 const report={};
 for(const [name,size] of Object.entries({phone:{width:390,height:844},keyboard:{width:390,height:508},narrow:{width:320,height:568}})){
  await page.setViewportSize(size);
  await page.waitForTimeout(250);
  // Resize must follow even without a new token.
  const g=await geometry();await page.screenshot({path:path.join(out,name+"-debug.png")});validate(g);report[name]=g;
  await page.screenshot({path:path.join(out,name+'.png')});
 }
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>window.fixtureToken('The first streamed words'));
 await page.waitForFunction(()=>[...document.querySelectorAll('.jg-turn')].at(-1)?.querySelector('.jg-bubble--assistant')?.textContent.includes('streamed'));
 assert.equal(await page.locator('.jg-turn').last().locator('.jg-progress-line').count(),0);
 await page.evaluate(()=>window.fixtureToken(' grow in the same assistant bubble.'));
 await page.waitForFunction(()=>[...document.querySelectorAll('.jg-turn')].at(-1)?.querySelector('.jg-bubble--assistant')?.textContent.includes('same assistant bubble'));
 assert.equal(await page.locator('.jg-turn').last().locator('.jg-bubble--assistant').count(),1);
 await page.waitForTimeout(350);report.streaming=await geometry();validate(report.streaming);
 await page.screenshot({path:path.join(out,'streaming.png')});
 // A large draft must remeasure both composer and its sibling voice orb.
 await page.locator('.jg-composer__input').fill(Array.from({length:8},(_,i)=>'Draft line '+i).join('\n'));
 await page.waitForTimeout(250);report.multiline=await geometry();validate(report.multiline);
 // Native reader movement pauses follow. More tokens must not steal the scroll.
 await page.locator('.jg-chat__scroll').evaluate(el=>{el.dispatchEvent(new WheelEvent('wheel',{bubbles:true,deltaY:-300}));el.scrollTop=0;el.dispatchEvent(new Event('scroll',{bubbles:true}));});
 await page.evaluate(()=>window.fixtureToken(' More tokens while reading older messages.'));
 await page.waitForTimeout(250);
 assert.equal(await page.locator('.jg-chat__scroll').evaluate(el=>el.scrollTop),0);
 await page.locator('[aria-label^="Scroll to bottom"]').click();
 await page.waitForTimeout(600);
 await page.evaluate(()=>window.fixtureFinish());
 await page.waitForFunction(()=>!document.querySelector('[aria-label^="Stop"]'));
 assert.equal(await page.locator('.jg-progress-line').count(),0);
 assert.equal(await page.locator('.jg-composer .jg-recovery').count(),0);
 assert.deepEqual(errors,[]);
 report.errors=errors;
 writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({checks:Object.keys(report),consoleErrors:errors,phoneGap:report.phone.gap,keyboardGap:report.keyboard.gap,narrowGap:report.narrow.gap,composerToTabs:report.phone.tabs.top-report.phone.composer.bottom,latestToComposer:report.phone.composer.top-report.phone.last.bottom,output:out},null,2));
} finally {await browser?.close();await server.close();}
