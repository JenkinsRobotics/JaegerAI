// Offline authoring only. The app plays the encoded MP4s, not this animation.
import {chromium} from 'playwright-core';
import {readFile,mkdir,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const output=resolve('public/assets/avatar/jaeger'), temp=await mkdtemp(join(tmpdir(),'jaeger-avatar-render-'));
const art=`data:image/png;base64,${(await readFile('src/assets/characters/jaeger-sculpted.png')).toString('base64')}`;
await mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
 const page=await browser.newPage({viewport:{width:512,height:512},deviceScaleFactor:1});
 await page.setContent(`<style>body{margin:0;background:white}img{width:512px;height:512px}</style><img src="${art}">`);
 await page.locator('img').evaluate(img=>img.decode());await page.screenshot({path:join(output,'portrait.png')});
 await page.setViewportSize({width:420,height:720});
 await page.setContent(`<style>body{margin:0;background:white}svg{display:block}</style><svg width="420" height="720"><defs><filter id="soft"><feGaussianBlur stdDeviation="2"/></filter><mask id="mouth"><ellipse cx="208" cy="147" rx="65" ry="36" fill="white" filter="url(#soft)"/></mask></defs><g id="body"><image href="${art}" width="420" height="420"/><g id="smile"><image href="${art}" width="420" height="420" mask="url(#mouth)"/></g></g><g id="laptop"><path d="M123 450L285 450 300 524 136 524Z" fill="#c9cbd0" stroke="#8c8e94" stroke-width="2"/><path d="M136 524L300 524 320 535 145 535Z" fill="#e5e6e9"/><circle cx="215" cy="488" r="8" fill="#eff0f2"/></g><g id="cube"><path d="M198 434L229 417 260 434 229 453Z" fill="#e5e5e5" stroke="#aaa"/><path d="M198 434V468L229 486V453Z" fill="#ccc" stroke="#aaa"/><path d="M229 453L260 434V468L229 486Z" fill="#fafafa" stroke="#aaa"/></g><g id="sparks" stroke="#6d6d6d" stroke-width="3" stroke-linecap="round"><path d="M90 210v16m-8-8h16M329 243v16m-8-8h16M110 390v12m-6-6h12"/></g></svg>`);
 await page.evaluate(async()=>{await Promise.all([...document.querySelectorAll('image')].map(el=>new Promise((resolve,reject)=>{const img=new Image();img.onload=resolve;img.onerror=reject;img.src=el.getAttribute('href');})));});
 for(const state of ['idle','working','making_something','waiting','connecting','milestone']) {
  const duration=state==='connecting'?3:4,frames=duration*24;
  for(let frame=0;frame<frames;frame++) {
   await page.evaluate(({state,phase})=>{
    const s=Math.sin(phase),c=(1-Math.cos(phase))/2;
    const bounce=state==='milestone'?18*c:state==='working'?3*Math.sin(phase*2):2*c;
    const body=document.getElementById('body');body.setAttribute('transform',`translate(0 ${155-bounce}) rotate(${(state==='waiting'?2:1)*s} 210 390)`);body.style.opacity=state==='connecting'?String(.84+.16*c):'1';
    document.getElementById('smile').setAttribute('transform',`translate(208 147) scale(${1+.05*c} ${1+.08*c}) translate(-208 -147)`);
    for(const [id,show] of [['laptop',state==='working'],['cube',state==='making_something'],['sparks',state==='milestone']])document.getElementById(id).style.display=show?'':'none';
    document.getElementById('cube').setAttribute('transform',`translate(0 ${-5*c}) rotate(${3*s} 229 453)`);document.getElementById('sparks').style.opacity=String(c);
   },{state,phase:frame/frames*2*Math.PI});
   await page.screenshot({path:join(temp,`${String(frame).padStart(4,'0')}.png`)});
  }
  execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-y','-framerate','24','-i',join(temp,'%04d.png'),'-frames:v',String(frames),'-an','-c:v','libx264','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',join(output,`${state}.mp4`)]);
  console.log(`Rendered ${state}: ${duration}s, 420x720, silent H.264`);
 }
} finally {await browser.close();await rm(temp,{recursive:true,force:true});}
