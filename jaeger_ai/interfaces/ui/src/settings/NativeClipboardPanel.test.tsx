import{act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{NativeClipboardPanel}from'./NativeClipboardPanel';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('reads only on explicit action, renders literal text and never attaches, persists or auto-writes it',async()=>{
 const post=vi.fn(async(type:string)=>{if(type==='clipboard.read')return{state:'text_available',text:'<b>Owned clipboard text</b>',content_type:'text/plain',max_bytes:100000};throw Error('Unexpected write, permission or service action');});
 const before=window.jaegerNative;window.jaegerNative={post};const storageBefore=JSON.stringify({...localStorage});const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<NativeClipboardPanel/>));expect(post).not.toHaveBeenCalled();
  await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Read local clipboard preview')!.click());
  expect(post).toHaveBeenCalledExactlyOnceWith('clipboard.read');expect(el.querySelector('pre')!.textContent).toBe('<b>Owned clipboard text</b>');expect(el.querySelector('b')).toBeNull();expect(el.querySelector('textarea')!.value).toBe('');expect(JSON.stringify({...localStorage})).toBe(storageBefore);
  await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Clear clipboard preview')!.click());expect(el.querySelector('pre')).toBeNull();expect(post).toHaveBeenCalledOnce();
 }finally{await act(async()=>root.unmount());el.remove();window.jaegerNative=before;}
});
it('preserves entered copy text after an unknown write and does not retry it',async()=>{
 const post=vi.fn(async()=>{throw Error('Lost native clipboard reply');});const before=window.jaegerNative;window.jaegerNative={post};const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<NativeClipboardPanel/>));const text=el.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(text,'Owned entered text');text.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Write entered text to local clipboard')!.click());
  expect(post).toHaveBeenCalledExactlyOnceWith('clipboard.write',{text:'Owned entered text'});expect(text.value).toBe('Owned entered text');expect(el.textContent).toContain('No automatic retry');expect(el.textContent).not.toContain('write acknowledged');
  await act(async()=>root.render(<NativeClipboardPanel/>));expect(post).toHaveBeenCalledOnce();
 }finally{await act(async()=>root.unmount());el.remove();window.jaegerNative=before;}
});
