import {act} from 'react';import {createRoot} from 'react-dom/client';import {it,expect,vi} from 'vitest';
import {DiagnosticCapturePanel} from './DiagnosticCapturePanel';import {DIAGNOSTIC_CAPTURE_KEY,type DiagnosticCaptureControls,type DiagnosticCaptureSnapshot} from '../api/diagnosticCapture';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
const empty:DiagnosticCaptureSnapshot={boot_id:'owned-boot',scope:'current_gateway_volatile_counters',capture:null,events:[],max_events:128,max_seconds:300,codes:{malformed_json:'parser'},retention:'volatile'};
it('requires explicit opt-in and recovers a lost ACK by status without restarting capture',async()=>{
 localStorage.clear();let current=empty;
 const start=vi.fn(async(body:{operation_id:string;duration_seconds:number})=>{current={...empty,capture:{id:'a'.repeat(32),operation_id:body.operation_id.replaceAll('-',''),state:'active',started_at:1,expires_at:Date.now()/1000+60,duration_seconds:60,occurrences:0,unique_receipts:0,overflow_occurrences:0,saturated:false}};throw Error('lost capture ACK');});
 const controls:DiagnosticCaptureControls={read:vi.fn(async()=>current),start,stop:vi.fn(),export:vi.fn(async()=>({format:'safe',...current}))};
 const el=document.createElement('div');document.body.append(el);let root=createRoot(el);const click=(text:string)=>[...el.querySelectorAll('button')].find(b=>b.textContent===text)!.click();
 try{await act(async()=>root.render(<DiagnosticCapturePanel controls={controls}/>));expect(localStorage.getItem(DIAGNOSTIC_CAPTURE_KEY)).toBeNull();await act(async()=>click('Review 60-second diagnostic capture'));expect(start).not.toHaveBeenCalled();await act(async()=>click('Enable bounded diagnostics'));expect(start).toHaveBeenCalledTimes(1);expect(localStorage.getItem(DIAGNOSTIC_CAPTURE_KEY)).toBeNull();
 await act(async()=>root.unmount());root=createRoot(el);await act(async()=>root.render(<DiagnosticCapturePanel controls={controls}/>));await act(async()=>click('Read current capture status'));expect(start).toHaveBeenCalledTimes(1);expect(JSON.parse(localStorage.getItem(DIAGNOSTIC_CAPTURE_KEY)!).id).toBe('a'.repeat(32));expect(el.textContent).toContain('Bounded reporting enabled');
 }finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
it('does not restart after a Gateway process change or enable reporting merely by reading status',async()=>{
 localStorage.clear();const intent={kind:'start',operation_id:'owned-old-intent',duration_seconds:60,boot_id:'old-boot'};localStorage.setItem('jaeger.ui.diagnostics.intent.v1',JSON.stringify(intent));
 const controls:DiagnosticCaptureControls={read:vi.fn(async()=>empty),start:vi.fn(),stop:vi.fn(),export:vi.fn()};
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);const click=(text:string)=>[...el.querySelectorAll('button')].find(b=>b.textContent===text)!.click();
 try{await act(async()=>root.render(<DiagnosticCapturePanel controls={controls}/>));await act(async()=>click('Read current capture status'));expect(el.textContent).toContain('earlier capture outcome unknown');expect(localStorage.getItem(DIAGNOSTIC_CAPTURE_KEY)).toBeNull();expect(controls.start).not.toHaveBeenCalled();expect(localStorage.getItem('jaeger.ui.diagnostics.intent.v1')).toBe(JSON.stringify(intent));}finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
