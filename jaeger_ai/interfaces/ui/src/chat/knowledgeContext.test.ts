import { it, expect } from 'vitest'; import { mapEvent } from './eventMap'; import { applyPart } from './host'; import { messagesToTurns } from './webHost';
it('maps the same context receipt live and persisted without making it an answer or tool execution',()=>{
 const documents=[{id:'doc_owned',title:'Owned reference',revision:1,digest:'owned-digest'}];
 const live=mapEvent({event:'agent.knowledge',payload:{documents}})!.parts[0];
 expect(live).toEqual({kind:'knowledgeContext',documents});expect(applyPart([live],live)).toHaveLength(1);
 expect(applyPart([live,{kind:'markdownContent',text:'Answer'}],live).map(part=>part.kind)).toEqual(['knowledgeContext','markdownContent']);
 const turns=messagesToTurns([{id:1,role:'user',content:'Question',request_id:'owned'},{id:2,role:'assistant',content:'Answer',request_id:'owned',parts:[{type:'knowledge',documents},{type:'text',text:'Answer'}]}]);
 expect(turns[0].parts).toEqual([live,{kind:'markdownContent',text:'Answer'}]);
});
