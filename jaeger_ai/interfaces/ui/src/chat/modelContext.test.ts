import {it,expect} from 'vitest';
import {mapEvent} from './eventMap';
import {messagesToTurns} from './webHost';
import {modelContext} from './modelContext';
it('maps actual-dispatch outlines identically live and restored, retaining separate attempts',()=>{
 const outline={shape:'messages',system_chars:12,tool_count:2,truncated:false,messages:[{role:'user',text_chars:9,omitted_blocks:1}]};
 const live=mapEvent({event:'turn.context',payload:{outline}})!.parts[0];
 const turns=messagesToTurns([{id:1,role:'user',content:'Question',request_id:'owned'},{id:2,role:'assistant',content:'Answer',request_id:'owned',parts:[{type:'model_context',outline},{type:'model_context',outline},{type:'text',text:'Answer'}]}]);
 expect(turns[0].parts).toEqual([live,live,{kind:'markdownContent',text:'Answer'}]);
});
it('does not render arbitrary strings or invalid counts from context metadata',()=>{
 expect(modelContext({shape:'SECRET',system_chars:-1,tool_count:Infinity,messages:[{role:'SECRET',text_chars:'SECRET',omitted_blocks:2}]})).toEqual({shape:'unsupported',system_chars:0,tool_count:0,truncated:false,messages:[{role:'other',text_chars:0,omitted_blocks:2}]});
});
