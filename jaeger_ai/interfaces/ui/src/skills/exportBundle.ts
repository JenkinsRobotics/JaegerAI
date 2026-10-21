import type {PlaybookBundle} from '../api/source';
/** Data-only local export; no executable HTML/URL, publisher call or save claim. */
export async function validatedBundle(value:PlaybookBundle,name:string,revision:string):Promise<Blob>{
 if(value.format!=='jaeger-playbook-bundle-v1'||value.name!==name||value.revision!==revision||value.target!=='local_file'||value.execution_authorized!==false||value.publisher_verified!==false||value.license_verified!==false||!Array.isArray(value.files)||value.files.length>2000)throw Error('Export identity or policy mismatch');
 const paths=new Set<string>();let size=0;
 for(const file of value.files){
  if(typeof file.path!=='string'||!file.path||file.path.startsWith('/')||/[\\\u0000-\u001f]/.test(file.path)||file.path.split('/').some(p=>!p||p==='.'||p==='..')||paths.has(file.path.toLowerCase())||!Number.isSafeInteger(file.size_bytes)||file.size_bytes<0||typeof file.base64!=='string'||file.base64.length>27000000||!/^[a-f0-9]{64}$/.test(file.sha256))throw Error('Unsafe export member');
  paths.add(file.path.toLowerCase());size+=file.size_bytes;if(size>20000000)throw Error('Export exceeds byte bound');
  const raw=atob(file.base64);if(raw.length!==file.size_bytes||btoa(raw)!==file.base64)throw Error('Export byte size/encoding mismatch');const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
  const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');if(digest!==file.sha256)throw Error('Export content digest mismatch');
 }
 if(!paths.has('skill.md'))throw Error('Export is missing its playbook');
 return new Blob([JSON.stringify(value,null,2)],{type:'application/json'});
}
