import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { LibraryPanel } from './LibraryPanel'; import type { LibraryControls } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('loads UTF-8 file as unsent document draft, preserves the previous draft and rejects invalid bytes', async()=>{
 const key='jaeger.ui.library.draft.v1.new';localStorage.setItem(key,JSON.stringify({title:'Previous draft',content:'Keep original'}));
 const mutate=vi.fn();const controls={list:async()=>({documents:[],collections:[],limits:{document_bytes:2000000}}),mutate}as unknown as LibraryControls;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<LibraryPanel controls={controls}/>));
 const input=element.querySelector<HTMLInputElement>('[aria-label="Import text document"]')!;
 const bytes=new TextEncoder().encode('Owned UTF-8 content');const file=new File([bytes],'owned.md',{type:'text/markdown'});Object.defineProperty(file,'arrayBuffer',{value:async()=>bytes.buffer});
 await act(async()=>{Object.defineProperty(input,'files',{value:[file],configurable:true});input.dispatchEvent(new Event('change',{bubbles:true}));});
 expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Document content"]')?.value).toBe('Owned UTF-8 content');expect(mutate).not.toHaveBeenCalled();
 const backups=Object.keys(localStorage).filter(k=>k.startsWith(key+'.backup.'));expect(backups).toHaveLength(1);expect(localStorage.getItem(backups[0])).toContain('Keep original');
 const invalid=new Uint8Array([255]);const bad=new File([invalid],'bad.txt');Object.defineProperty(bad,'arrayBuffer',{value:async()=>invalid.buffer});
 await act(async()=>{Object.defineProperty(input,'files',{value:[bad],configurable:true});input.dispatchEvent(new Event('change',{bubbles:true}));});
 expect(element.textContent).toContain('Text import failed');expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Document content"]')?.value).toBe('Owned UTF-8 content');expect(mutate).not.toHaveBeenCalled();
 await act(async()=>root.unmount());element.remove();localStorage.removeItem(key);backups.forEach(k=>localStorage.removeItem(k));
});
