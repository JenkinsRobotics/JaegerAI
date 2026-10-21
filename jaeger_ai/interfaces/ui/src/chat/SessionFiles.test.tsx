import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect,it,vi } from 'vitest';
import { SessionFiles } from './SessionFiles';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('retains origin identity and displays a read failure without claiming a download',async()=>{
 const file={attachment_id:'owned-file',name:'fixture.txt',mime:'text/plain',size:3,sha256:'expected-digest',readable:true};
 const files={list:vi.fn(async()=>({session_id:'owned-home',files:[file],max_bytes:100})),read:vi.fn(async()=>{throw Error('Attachment changed; bytes withheld');})};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<SessionFiles files={files} sessionId="owned-home" onClose={()=>{}}/>));
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Preview fixture.txt')!.click());
  expect(files.read).toHaveBeenCalledExactlyOnceWith('owned-home','owned-file');
  expect(host.textContent).toContain('Attachment changed; bytes withheld');
  expect(host.querySelector('img')).toBeNull();expect(host.querySelector('a')).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();}
});
it('renders verified HTML-looking text literally and rejects a changed digest',async()=>{
 const {webcrypto,createHash}=await import('node:crypto');
 vi.stubGlobal('crypto',webcrypto);
 const text='<b>owned fixture</b>',digest=createHash('sha256').update(text).digest('hex');
 const file={attachment_id:'owned-file',name:'fixture.html',mime:'text/html',size:text.length,sha256:digest,readable:true};
 const read=vi.fn(async()=>({session_id:'owned-home',...file,data_base64:btoa(text)}));
 const files={list:async()=>({session_id:'owned-home',files:[file],max_bytes:100}),read};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<SessionFiles files={files} sessionId="owned-home" onClose={()=>{}}/>));
  const preview=[...host.querySelectorAll('button')].find(b=>b.textContent==='Preview fixture.html')!;
  await act(async()=>preview.click());
  await act(async()=>{await vi.waitFor(()=>expect(host.querySelector('pre')?.textContent).toBe(text),{timeout:1000});});
  expect(host.querySelector('pre')?.textContent).toBe(text);expect(host.querySelector('b')).toBeNull();expect(host.querySelector('iframe')).toBeNull();
  read.mockResolvedValueOnce({session_id:'owned-home',...file,data_base64:btoa('x'.repeat(text.length))});
  await act(async()=>preview.click());
  await act(async()=>{await vi.waitFor(()=>expect(host.textContent).toContain('File digest mismatch'),{timeout:1000});});
  expect(host.textContent).toContain('File digest mismatch');expect(host.querySelector('pre')).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
it('keeps the newer spreadsheet identity when an earlier preview arrives late and never mounts active cells',async()=>{
 const a={attachment_id:'a',name:'a.xlsx',mime:'application/octet-stream',size:3,sha256:'a'.repeat(64),readable:true},b={...a,attachment_id:'b',name:'b.xlsx',sha256:'b'.repeat(64)};
 let resolveA!:(value:import('../api/source').SessionFilePreview)=>void;
 const preview=vi.fn(async(_sid:string,id:string)=>id==='a'?new Promise<import('../api/source').SessionFilePreview>(resolve=>{resolveA=resolve;}):{session_id:'owned',...b,preview:{format:'spreadsheet' as const,notice:'Cached literal values only',sheets:[{name:'Second',rows:[['<script>never run</script>','=1+1']],row_numbers:[10]}]}});
 const files={list:async()=>({session_id:'owned',files:[a,b],max_bytes:100}),read:vi.fn(),preview};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<SessionFiles files={files} sessionId="owned" onClose={()=>{}}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(el=>el.textContent==='Preview a.xlsx')!.click());
 await act(async()=>[...host.querySelectorAll('button')].find(el=>el.textContent==='Preview b.xlsx')!.click());
 expect(host.querySelector('[aria-label="Preview b.xlsx"]')?.textContent).toContain('<script>never run</script>');expect(host.querySelector('script')).toBeNull();expect(host.querySelector('td')?.textContent).toBe('<script>never run</script>');
 await act(async()=>resolveA({session_id:'owned',...a,preview:{format:'spreadsheet',notice:'old',sheets:[{name:'OLD',rows:[['old']]}]}}));
 expect(host.querySelector('[aria-label="Preview b.xlsx"]')).not.toBeNull();expect(host.querySelector('[aria-label="Preview a.xlsx"]')).toBeNull();expect(files.read).not.toHaveBeenCalled();
 await act(async()=>root.unmount());host.remove();
});
it('renders static PDF pages through scoped preview only and validates exact returned page',async()=>{
 const file={attachment_id:'owned-pdf',name:'owned.pdf',mime:'application/pdf',size:123,sha256:'a'.repeat(64),readable:true};
 const image='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2tI8AAAAASUVORK5CYII=';
 const preview=vi.fn(async(_session:string,_id:string,page?:number)=>({session_id:'owned',...file,preview:{format:'pdf' as const,notice:'Static page only',page:page??1,page_count:2,page_limit:20,width:1,height:1,text:'<script>literal page '+page+'</script>',image_base64:image}}));
 const files={list:async()=>({session_id:'owned',files:[file],max_bytes:1000}),preview,read:vi.fn()};const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!.click());
 try{
  await act(async()=>root.render(<SessionFiles files={files} sessionId="owned" onClose={()=>{}}/>));await click('Preview owned.pdf');
  expect(preview).toHaveBeenCalledExactlyOnceWith('owned','owned-pdf',1);expect(host.querySelector('img')?.src).toContain('data:image/png;base64,');expect(host.querySelector('iframe')).toBeNull();expect(host.querySelector('script')).toBeNull();
  await click('Next PDF page');expect(preview).toHaveBeenLastCalledWith('owned','owned-pdf',2);expect(host.textContent).toContain('Page 2 of 2');expect(files.read).not.toHaveBeenCalled();
  preview.mockResolvedValueOnce({session_id:'owned',...file,preview:{format:'pdf',notice:'wrong page',page:2,page_count:2,page_limit:20,width:1,height:1,text:'wrong',image_base64:image}});
  await click('Previous PDF page');expect(host.textContent).toContain('page identity mismatch');expect(host.querySelector('img')).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();}
});
it('discards an old PDF result after another artifact becomes the selected preview',async()=>{
 const a={attachment_id:'a',name:'a.pdf',mime:'application/pdf',size:3,sha256:'a'.repeat(64),readable:true},b={...a,attachment_id:'b',name:'b.csv',mime:'text/csv',sha256:'b'.repeat(64)};
 let resolve!:(value:import('../api/source').SessionFilePreview)=>void;
 const preview=vi.fn(async(_sid:string,id:string)=>id==='a'?new Promise<import('../api/source').SessionFilePreview>(done=>{resolve=done;}):{session_id:'owned',...b,preview:{format:'spreadsheet' as const,notice:'Current literal cells',sheets:[{name:'B',rows:[['CURRENT']]}]}});
 const files={list:async()=>({session_id:'owned',files:[a,b],max_bytes:100}),read:vi.fn(),preview};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(button=>button.textContent===text)!.click());
 try{
  await act(async()=>root.render(<SessionFiles files={files} sessionId="owned" onClose={()=>{}}/>));await click('Preview a.pdf');await click('Preview b.csv');
  await act(async()=>resolve({session_id:'owned',...a,preview:{format:'unsupported',notice:'OLD PDF RESULT'}}));
  expect(host.querySelector('[aria-label="Preview b.csv"]')).not.toBeNull();expect(host.textContent).toContain('CURRENT');expect(host.textContent).not.toContain('OLD PDF RESULT');expect(host.querySelector('iframe')).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();}
});
