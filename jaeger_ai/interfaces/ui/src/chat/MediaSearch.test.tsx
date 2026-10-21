import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {MediaSearch} from './MediaSearch';
import {stageSavedMedia,toAttachments} from './composer';
import type {SessionFiles} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('retires older-query results and previews without selecting, uploading or sending',async()=>{
 let release!:(value:Awaited<ReturnType<NonNullable<SessionFiles['media']>>>)=>void;
 const row={attachment_id:'owned',name:'dogs.png',mime:'image/png',size:3,sha256:'a'.repeat(64),readable:true};
 const result=(query:string)=>({session_id:'home',query,files:[{...row,name:query+'.png'}],next_after:null,source:'existing_session_attachments' as const,licensing:'not_verified' as const,selection_attaches:false as const});
 const media=vi.fn(async(_sid:string,q:string)=>q==='cats'?new Promise<Awaited<ReturnType<NonNullable<SessionFiles['media']>>>>(resolve=>{release=resolve;}):result(q));
 const onPreview=vi.fn(),read=vi.fn();const files={media,list:vi.fn(),read};const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 const query=async(text:string)=>{await act(async()=>{const input=el.querySelector('input')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,text);input.dispatchEvent(new Event('input',{bubbles:true}));});await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Search saved media')!.click());};
 try{await act(async()=>root.render(<MediaSearch files={files} sessionId="home" onPreview={onPreview}/>));await query('cats');await query('dogs');await act(async()=>release(result('cats')));expect(el.textContent).toContain('dogs.png');expect(el.textContent).not.toContain('cats.png');expect(onPreview).not.toHaveBeenCalled();expect(read).not.toHaveBeenCalled();await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Preview saved media dogs.png')!.click());expect(onPreview).toHaveBeenCalledOnce();expect(read).not.toHaveBeenCalled();expect(el.textContent).toContain('licensing/redistribution rights are not verified');}finally{await act(async()=>root.unmount());el.remove();}
});
it('stages only the exact active-session media once and removal yields no attachable files',()=>{
 const file={session_id:'home',attachment_id:'owned',name:'owned.png',mime:'image/png',size:3,sha256:'a'.repeat(64),data_base64:'YWJj'};
 const first=stageSavedMedia([],'home',file);expect(first.files).toHaveLength(1);expect(first.note).toContain('not sent');expect(stageSavedMedia(first.files,'home',file).files).toBe(first.files);
 expect(()=>stageSavedMedia([],'other',file)).toThrow('different conversation');expect(()=>stageSavedMedia([],'home',{...file,mime:'image/svg+xml'})).toThrow('unsupported');
 const removed=first.files.filter(row=>row.id!==first.files[0].id);expect(removed).toEqual([]);expect(toAttachments(removed)).toEqual([]);expect(toAttachments(first.files)).toEqual([{name:file.name,mimeType:file.mime,size:file.size,data:file.data_base64}]);
});
