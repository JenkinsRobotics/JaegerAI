import {expect,it} from 'vitest';
import {validateTemplateExport} from './templateExport';
async function receipt(extra:Record<string,unknown>={}){
 const content=JSON.stringify({format:'jaeger.specialist-template',schema_version:1,version:3,visibility:'owner_local',export_policy:'prompt_only_no_grants',source_bot:{agent_id:'native:owned',configuration_revision:2},settings:{specialty:'local',summary:'original',instructions:'Supplied text only.'},tools_granted:false,credentials_included:false,history_included:false,...extra});
 const sha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(content)))].map(b=>b.toString(16).padStart(2,'0')).join('');
 return {agent_id:'native:owned',revision:2,content,sha256,visibility:'owner_local',export_policy:'prompt_only_no_grants'};
}
it('accepts exact original source-bound prompt-only bytes',async()=>{const saved=await receipt();expect(await validateTemplateExport(saved,'native:owned',2)).toBe(saved.content);});
it('rejects stale identity, altered bytes and added private/authority fields',async()=>{
 const saved=await receipt();await expect(validateTemplateExport(saved,'native:other',2)).rejects.toThrow();await expect(validateTemplateExport(saved,'native:owned',3)).rejects.toThrow();
 await expect(validateTemplateExport({...saved,content:saved.content+' '},'native:owned',2)).rejects.toThrow('bytes mismatch');
 await expect(validateTemplateExport(await receipt({history:['private']}),'native:owned',2)).rejects.toThrow('contents');
 await expect(validateTemplateExport(await receipt({tools_granted:true}),'native:owned',2)).rejects.toThrow('contents');
});
