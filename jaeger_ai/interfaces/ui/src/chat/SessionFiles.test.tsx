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
  expect(host.querySelector('pre')?.textContent).toBe(text);expect(host.querySelector('b')).toBeNull();expect(host.querySelector('iframe')).toBeNull();
  read.mockResolvedValueOnce({session_id:'owned-home',...file,data_base64:btoa('x'.repeat(text.length))});
  await act(async()=>preview.click());
  expect(host.textContent).toContain('File digest mismatch');expect(host.querySelector('pre')).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
