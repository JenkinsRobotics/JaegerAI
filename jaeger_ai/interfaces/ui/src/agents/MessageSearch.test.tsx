import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { MessageSearch } from './MessageSearch'; import type { JaegerSource, MessageSearchPage } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('ignores a late previous-bot search response after the new bot search resolves', async () => {
  let oldResolve!: (page: MessageSearchPage) => void;
  const result = (agent_id: string, content: string): MessageSearchPage => ({ agent_id, matches:[{message_id:content,session_id:'owned',role:'user',kind:'message',title:'Owned',timestamp:1,snippet:content,content,truncated:false}], next_before:null,matching:'literal_sqlite_lower' });
  const searchMessages = vi.fn((id:string) => id === 'a' ? new Promise<MessageSearchPage>(r=>{oldResolve=r;}) : Promise.resolve(result('b','Current bot content')));
  const source = {searchMessages} as unknown as JaegerSource;
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  const render=(id:string)=><MessageSearch source={source} agentId={id} name={id} onClose={()=>{}}/>;
  await act(async()=>root.render(render('a')));
  const input=document.querySelector<HTMLInputElement>('[aria-label="Search bot messages"]')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'needle');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>{await new Promise(r=>setTimeout(r,230));});
  expect(searchMessages).toHaveBeenCalledWith('a','needle');
  await act(async()=>root.render(render('b')));await act(async()=>{await new Promise(r=>setTimeout(r,230));});
  await act(async()=>oldResolve(result('a','Stale private content')));
  expect(document.body.textContent).toContain('Current bot content');expect(document.body.textContent).not.toContain('Stale private content');
  await act(async()=>root.unmount());element.remove();
});

it('opens a large match at its exact source offset and replaces bounded portions without sending',async()=>{
 const hit={message_id:'23',session_id:'owned-history',role:'assistant',kind:'message',title:'Owned',timestamp:1,snippet:'Straße at match',content:'First preview',truncated:true,match_offset:9000,content_revision:'r1'};
 const savedMessage=vi.fn(async(id:string,message:string,offset:number)=>({agent_id:id,message_id:message,session_id:'owned-history',role:'assistant',kind:'message',content:offset===9000?'Exact match portion':'Final portion',offset,end_offset:offset===9000?17000:18000,total_chars:18000,revision:'r1',next_offset:offset===9000?17000:null,previous_offset:1000}));
 const source={searchMessages:vi.fn(async()=>({agent_id:'a',matches:[hit],matching:'literal_unicode_casefold',next_before:null})),savedMessage} as unknown as JaegerSource;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
 try{
  await act(async()=>root.render(<MessageSearch source={source} agentId="a" name="Owned" onClose={()=>{}}/>));
  const input=document.querySelector<HTMLInputElement>('[aria-label="Search bot messages"]')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'STRASSE');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>{await new Promise(r=>setTimeout(r,230));});
  const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent===text)!;
  await act(async()=>button('Open full saved message at match').click());
  expect(savedMessage).toHaveBeenCalledWith('a','23',9000,'r1');expect(document.body.textContent).toContain('Exact match portion');
  await act(async()=>button('Next message portion').click());
  expect(savedMessage).toHaveBeenLastCalledWith('a','23',17000,'r1');expect(document.body.textContent).toContain('Final portion');expect(document.body.textContent).not.toContain('Exact match portion');
  expect(document.body.textContent).toContain('Your open chat, draft and unread state are unchanged');
 }finally{await act(async()=>root.unmount());element.remove();}
});

it('rejects a full-message response from a foreign bot without rendering its text',async()=>{
 const source={searchMessages:async()=>({agent_id:'a',matches:[{message_id:'23',session_id:'owned',role:'user',kind:'message',title:'Owned',timestamp:1,snippet:'Owned match',content:'Owned preview',truncated:true}],matching:'literal_unicode_casefold',next_before:null}),savedMessage:vi.fn(async()=>({agent_id:'foreign',message_id:'23',session_id:'foreign',content:'PRIVATE-FOREIGN'}))} as unknown as JaegerSource;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
 try{await act(async()=>root.render(<MessageSearch source={source} agentId="a" name="Owned" onClose={()=>{}}/>));const input=document.querySelector<HTMLInputElement>('[aria-label="Search bot messages"]')!;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Owned');input.dispatchEvent(new Event('input',{bubbles:true}));});await act(async()=>{await new Promise(r=>setTimeout(r,230));});
 await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Open full saved message at match')!.click());expect(document.body.textContent).toContain('identity/revision mismatch');expect(document.body.textContent).not.toContain('PRIVATE-FOREIGN');
 }finally{await act(async()=>root.unmount());element.remove();}
});
