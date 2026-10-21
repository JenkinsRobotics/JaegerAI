import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {highlight,resolveLang,clearHighlightCache,highlightCacheUsage} from './highlight';
import {Markdown} from './Markdown';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('renders oversized source in bounded plain portions without dropping copy or durable source',async()=>{
 const source='BEGIN '+('*large* '.repeat(10000))+' END';const onCopy=vi.fn();const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{await act(async()=>root.render(<Markdown text={source} onCopy={onCopy}/>));const pre=()=>el.querySelector('[aria-label="Large message plain portion"]')!;expect(pre()).not.toBeNull();expect(pre().textContent!.length).toBeLessThanOrEqual(16384);expect(pre().textContent).toContain('BEGIN');
 let joined=pre().textContent!;while([...el.querySelectorAll('button')].some(b=>b.textContent==='Next message portion'&&!b.disabled)){await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Next message portion')!.click());joined+=pre().textContent;}
 expect(joined).toBe(source);await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Copy full message')!.click());expect(onCopy).toHaveBeenCalledExactlyOnceWith(source);
 await act(async()=>root.render(<Markdown text="New bot short reply" onCopy={onCopy}/>));expect(el.textContent).toBe('New bot short reply');expect(el.textContent).not.toContain('BEGIN');
 }finally{await act(async()=>root.unmount());el.remove();}
});
it('refuses oversized highlighting before loading/executing the regex parser',async()=>{
 expect(await highlight('x'.repeat(33000),'typescript')).toBeNull();
 expect(await highlight('a'.repeat(5000),'json')).toBeNull();
});

it('bounds cached source plus HTML by weight and releases it explicitly',async()=>{
 clearHighlightCache();for(let i=0;i<12;i++)await highlight(('const value'+i+' = 123;\n').repeat(1000),'typescript');
 const usage=highlightCacheUsage();expect(usage.units).toBeLessThanOrEqual(usage.budget);expect(usage.entries).toBeLessThan(12);expect(usage.pending).toBe(0);clearHighlightCache();expect(highlightCacheUsage().units).toBe(0);
 const stop=new AbortController();stop.abort();expect(await highlight('const a=1','typescript',stop.signal)).toBeNull();
});

it('rejects prototype names as grammar identities',()=>{expect(resolveLang('constructor')).toBeUndefined();expect(resolveLang('__proto__')).toBeUndefined();});
