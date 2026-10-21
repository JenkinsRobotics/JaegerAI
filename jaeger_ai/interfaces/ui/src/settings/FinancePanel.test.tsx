import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,expect,it,vi} from 'vitest';
import {FinancePanel} from './FinancePanel';
import type {FinanceAction,FinanceControls,FinanceReceipt} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
afterEach(()=>localStorage.clear());
const row:FinanceAction={id:'act_owned',revision:'a'.repeat(64),operation:'categorize_merchant',policy_tier:'one_click',stored_status:'pending',status:'pending',expires_at:null,settlement_status:'not_observed',execution_supported:false,can_record_review:true,can_deny:true,proposed_change:{merchant:'Owned Cafe',category:'Dining'}};
function fixture(){return {status:vi.fn(async()=>({state:'existing_local_store',policy:{money_movement:'blocked',payment_cards:'unsupported',provider:'not_probed',spending_limits:'no_payment_authority',approval_scope:'local_review_record_only',unknown_operations:'blocked',execution_supported:false as const,operations:[]},actions:[row]})),decide:vi.fn<FinanceControls['decide']>(),operation:vi.fn<FinanceControls['operation']>()};}
async function mount(controls:FinanceControls){const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(async()=>root.render(<FinancePanel controls={controls}/>));return {el,close:async()=>{await act(async()=>root.unmount());el.remove();},click:async(text:string)=>{await act(async()=>{const button=Array.from(el.querySelectorAll('button')).find(b=>b.textContent===text);expect(button).toBeTruthy();button!.click();});}};}
it('reviews exact saved scope only after confirmation; never applies changes or spends',async()=>{
 const controls=fixture();controls.decide.mockImplementation(async(id,body)=>({ok:true,...body,action_id:id,status:'approved',review_only:true,execution_performed:false,reviewed_revision:body.expected_revision,http_status:200} as FinanceReceipt));
 const page=await mount(controls);try{expect(page.el.textContent).toContain('not_probed');await page.click('Record local review…');expect(controls.decide).not.toHaveBeenCalled();expect(page.el.querySelector('[role=alertdialog]')?.textContent).toContain('Owned Cafe');await page.click('Confirm local review decision');expect(controls.decide).toHaveBeenCalledExactlyOnceWith('act_owned',{operation_id:expect.any(String),expected_revision:row.revision,decision:'record_review'});expect(page.el.textContent).toContain('No payment or financial action executed');expect(localStorage.length).toBe(0);}finally{await page.close();}
});
it('lost reply survives remount; reconciles original receipt without resubmitting',async()=>{
 const controls=fixture();controls.decide.mockRejectedValue(Error('lost response'));let page=await mount(controls);
 await page.click('Record local review…');await page.click('Confirm local review decision');const body=controls.decide.mock.calls[0][1];expect(localStorage.length).toBe(1);await page.close();
 controls.operation.mockResolvedValue({receipt:null});page=await mount(controls);try{await page.click('Check original finance review');expect(page.el.textContent).toContain('outcome remains unknown');expect(controls.decide).toHaveBeenCalledTimes(1);expect(localStorage.length).toBe(1);
 controls.operation.mockResolvedValue({receipt:{ok:true,...body,action_id:'act_owned',status:'approved',review_only:true,execution_performed:false,reviewed_revision:body.expected_revision,http_status:200} as FinanceReceipt});await page.click('Check original finance review');expect(controls.operation).toHaveBeenLastCalledWith(body.operation_id);expect(localStorage.length).toBe(0);expect(controls.decide).toHaveBeenCalledTimes(1);}finally{await page.close();}
});
it('mismatched receipt is retained as uncertain, with no success or retry',async()=>{
 const controls=fixture();controls.decide.mockImplementation(async(_id,body)=>({ok:true,...body,action_id:'other',status:'approved',review_only:true,execution_performed:false,reviewed_revision:body.expected_revision,http_status:200} as FinanceReceipt));const page=await mount(controls);try{await page.click('Record local review…');await page.click('Confirm local review decision');expect(page.el.textContent).toContain('receipt mismatch');expect(page.el.textContent).not.toContain('Local review recorded.');expect(localStorage.length).toBe(1);expect(controls.decide).toHaveBeenCalledTimes(1);}finally{await page.close();}
});
