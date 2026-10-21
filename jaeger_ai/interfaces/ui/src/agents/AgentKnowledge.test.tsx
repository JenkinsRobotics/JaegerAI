import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { AgentKnowledge } from './AgentKnowledge'; import type { AgentKnowledgeControls } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('reconciles uncertain bindings by read and retains the operator selection without saving again', async () => {
  const key='jaeger.ui.agent-knowledge.v1.native%3Aowned';localStorage.setItem(key,JSON.stringify({ids:['a'],revision:0,pending:true}));
  const save=vi.fn();const controls={read:async()=>({limits:{max_documents:8,context_chars:32000},agent_id:'native:owned',revision:1,editable:true,documents:[{id:'b',revision:1,digest:'b'}],available:[{id:'a',title:'Owned A',revision:2,digest:'a',archived:false},{id:'b',title:'Owned B',revision:1,digest:'b',archived:false}]}),save}as AgentKnowledgeControls;
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<AgentKnowledge agentId="native:owned" controls={controls} onClose={()=>{}} onSaved={()=>{}}/>));
  const button=(label:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent===label)!;
  expect(button('Save knowledge bindings').disabled).toBe(true);
  await act(async()=>button('Read current knowledge bindings').click());
  expect(save).not.toHaveBeenCalled();expect(document.body.textContent).toContain('Your selection is preserved');
  const inputs=[...document.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];expect(inputs.map(i=>i.checked)).toEqual([true,false]);
  expect(JSON.parse(localStorage.getItem(key)!)).toMatchObject({ids:['a'],revision:1,pending:false});
  await act(async()=>root.unmount());element.remove();localStorage.removeItem(key);
});
