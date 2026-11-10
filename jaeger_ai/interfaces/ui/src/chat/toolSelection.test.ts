import {expect, test} from 'vitest';
import {mapEvent} from './eventMap';
import {applyPart} from './host';
import {messagesToTurns} from './webHost';
import {toolSelection} from './toolSelection';
test('live selection receipts replace earlier step metadata and exclude private server fields',()=>{
 const receipt={mode:'progressive',selected_count:1,catalog_count:2,tools:[{tool:'mail_search',source:'mail',selected:true,available:true,selection_reason:'Matched this task',privateToken:'SECRET'}]};
 const part=mapEvent({event:'tools.selected',payload:{receipt}})!.parts[0];
 expect(part.kind).toBe('toolSelection');
 const turns=messagesToTurns([{id:1,role:'user',content:'Question',request_id:'owned'}, {id:2,role:'assistant',content:'Answer',request_id:'owned',parts:[{type:'tool_selection',receipt},{type:'text',text:'Answer'}]}]);
 expect(turns[0].parts[0]).toEqual(part);
 expect(JSON.stringify(part)).not.toContain('SECRET');
 expect(applyPart([part],part)).toHaveLength(1);
 expect(toolSelection({selected_count:Infinity,tools:[null]}).tools).toEqual([]);
});
