/** Exact prompt-only owner-local contract, before any browser download. */
export async function validateTemplateExport(receipt:{agent_id:string;revision:number;content:string;sha256:string;visibility:string;export_policy:string},id:string,revision:number){
 if(receipt.agent_id!==id||receipt.revision!==revision||receipt.visibility!=='owner_local'||receipt.export_policy!=='prompt_only_no_grants'||typeof receipt.content!=='string'||receipt.content.length>100000)throw Error('Template source or policy mismatch');
 const bytes=new TextEncoder().encode(receipt.content);const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
 if(hash!==receipt.sha256)throw Error('Template bytes mismatch');
 const payload=JSON.parse(receipt.content);
 const fields=['format','schema_version','version','visibility','export_policy','source_bot','settings','tools_granted','credentials_included','history_included'];
 if(!payload||Object.keys(payload).sort().join()!==fields.sort().join()||payload.format!=='jaeger.specialist-template'||payload.schema_version!==1||payload.version!==revision+1||payload.visibility!=='owner_local'||payload.export_policy!=='prompt_only_no_grants'||payload.tools_granted!==false||payload.credentials_included!==false||payload.history_included!==false||payload.source_bot?.agent_id!==id||payload.source_bot?.configuration_revision!==revision||Object.keys(payload.source_bot).sort().join()!=='agent_id,configuration_revision'||!payload.settings||Object.keys(payload.settings).sort().join()!=='instructions,specialty,summary'||!Object.values(payload.settings).every(v=>typeof v==='string'))throw Error('Unsupported template contents');
 return receipt.content;
}
