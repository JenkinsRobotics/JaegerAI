/* Real isolated served UI. Device preferences only; no operator/native state. */
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';import path from 'node:path';
const [modulePath,listenerPath,evidence,expectation='passing']=process.argv.slice(2);
const {chromium}=await import(pathToFileURL(path.resolve(modulePath)));
const target=JSON.parse(await readFile(listenerPath,'utf8'));
if(!target.state.includes('/.jaeger/verification/blueprint-')||[8790,33418].includes(target.webui_port))throw Error('Refuse production');
await mkdir(evidence,{recursive:true});const browser=await chromium.launch({headless:true});const results=[];
try{
for(const os of ['light','dark'])for(const choice of ['system','light','dark']){
 const context=await browser.newContext({colorScheme:os,viewport:{width:1280,height:900}});const page=await context.newPage();
 await page.goto(`http://127.0.0.1:${target.webui_port}/?host=web`);
 await page.getByRole('button',{name:/Account ·/}).click();await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption(choice);
 await page.getByRole('button',{name:'Close settings',exact:true}).click();await page.reload();
 await page.getByRole('button',{name:/Builder/}).first().click({button:'right'});await page.getByRole('menu',{name:'Builder actions',exact:true}).waitFor();
 const palette=await page.evaluate(()=>{const root=getComputedStyle(document.documentElement),menu=getComputedStyle(document.querySelector('[role=menu]'));return {pane:root.getPropertyValue('--jg-color-pane').trim(),fg:root.getPropertyValue('--jg-color-fg').trim(),menu:menu.backgroundColor,menuText:menu.color,resolvedLight:document.documentElement.classList.contains('aether-light-theme'),saved:localStorage.getItem('aether-appearance')};});
 const light=choice==='light'||choice==='system'&&os==='light';
 const pass=palette.pane===(light?'#fcfcfc':'#161616')&&palette.menuText===(light?'rgb(17, 17, 17)':'rgb(242, 242, 242)')&&palette.resolvedLight===light&&palette.saved===choice;
 results.push({os,choice,pass,palette});await page.screenshot({path:path.join(evidence,`${os}-${choice}.png`)});await context.close();
}
await writeFile(path.join(evidence,'result.json'),JSON.stringify(results,null,2));
if(expectation==='passing'&&results.some(r=>!r.pass))throw Error('Appearance mismatch; see result.json');
if(expectation==='failing'&&!results.some(r=>!r.pass))throw Error('Expected pre-fix mismatch not reproduced');
console.log(JSON.stringify(results));
}finally{await browser.close();}
