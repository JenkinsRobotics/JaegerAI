import { useEffect, useRef, useState } from 'react';
import {literalPreview} from './literalPreview';
import type { SessionFiles as Files, SessionFile, LiteralFilePreview } from '../api/source';

/** Files stay in their originating session. Never render untrusted HTML/SVG. */
export function SessionFiles({files,sessionId,onClose}:{files:Files;sessionId:string;onClose:()=>void}){
  const [rows,setRows]=useState<SessionFile[]>(),[error,setError]=useState<string>(),[busy,setBusy]=useState(false);
  const [preview,setPreview]=useState<{name:string;text?:string;image?:string;unsupported?:boolean;mime?:string;literal?:LiteralFilePreview}>();
  const generation=useRef(0),objectUrl=useRef<string | undefined>(undefined);
  const release=()=>{if(objectUrl.current){URL.revokeObjectURL(objectUrl.current);objectUrl.current=undefined;}};
  useEffect(()=>{const token=++generation.current;setRows(undefined);setError(undefined);setPreview(undefined);setBusy(false);release();
    void files.list(sessionId).then(result=>{if(token!==generation.current)return;if(result.session_id!==sessionId)throw Error('File listing identity mismatch');setRows(result.files);}).catch(e=>{if(token===generation.current)setError(String(e));});
    return()=>{generation.current++;release();};
  },[files,sessionId]);
  const open=async(row:SessionFile,download=false)=>{
    const token=++generation.current;setBusy(true);setError(undefined);setPreview(undefined);release();
    try{
      if(!download&&files.preview&&/\.(xlsx|csv|tsv)$/i.test(row.name)){
        const result=await files.preview(sessionId,row.attachment_id);if(token!==generation.current)return;
        if(result.session_id!==sessionId||result.attachment_id!==row.attachment_id||result.sha256!==row.sha256||result.size!==row.size||result.name!==row.name||result.mime!==row.mime)throw Error('File preview identity or revision mismatch');
        setPreview({name:result.name,mime:result.mime,literal:literalPreview(result.preview)});return;
      }
      const result=await files.read(sessionId,row.attachment_id);if(token!==generation.current)return;
      if(result.session_id!==sessionId||result.attachment_id!==row.attachment_id||result.sha256!==row.sha256||result.size!==row.size||result.name!==row.name||result.mime!==row.mime)throw Error('File identity or revision mismatch');
      const bytes=Uint8Array.from(atob(result.data_base64),c=>c.charCodeAt(0));
      if(bytes.byteLength!==row.size)throw Error('File size mismatch');
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
      if(token!==generation.current)return;if(hash!==row.sha256)throw Error('File digest mismatch');
      if(download){const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));objectUrl.current=url;const link=document.createElement('a');link.href=url;link.download=result.name.replace(/[\\/\x00-\x1f]/g,'_');link.click();return;}
      const mime=result.mime.split(';')[0].trim().toLowerCase();
      if(['image/png','image/jpeg','image/webp','image/gif'].includes(mime)){const image=URL.createObjectURL(new Blob([bytes],{type:mime}));objectUrl.current=image;setPreview({name:result.name,image});}
      else if(mime.startsWith('text/')||['application/json','application/xml','application/yaml'].includes(mime)){
        if(bytes.length>1_000_000){setPreview({name:result.name,unsupported:true});return;}
        const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);if(text.includes('\0'))throw Error('Binary content cannot be previewed as text');setPreview({name:result.name,text});
      }else setPreview({name:result.name,unsupported:true});
    }catch(e){if(token===generation.current)setError(String(e));}finally{if(token===generation.current)setBusy(false);}
  };
  return <section aria-label="Conversation files" className="jg-card"><h3>Conversation files</h3><button type="button" onClick={onClose}>Close files</button><p>Files registered in this conversation, including staged uploads. Opening does not attach them to another turn. Text is shown literally; previews do not execute file content.</p>
    {error&&<p role="alert">{error}</p>}{!rows&&!error&&<p role="status">Loading files…</p>}{rows?.length===0&&<p>No registered files.</p>}
    {rows?.map(row=><article key={row.attachment_id}><strong>{row.name}</strong><p>{row.mime} · {row.size} bytes</p>{row.readable?<><button type="button" onClick={()=>void open(row)}>Preview {row.name}</button><button disabled={busy} type="button" onClick={()=>void open(row,true)}>Download {row.name}</button></>:<p>{row.unavailable_reason??'File access unavailable'}</p>}</article>)}
    {busy&&<p role="status">Verifying file bytes…</p>}{preview&&<section aria-label={`Preview ${preview.name}`}><h4>{preview.name}</h4>{preview.mime&&<p>{preview.mime}</p>}{preview.literal&&<><p>{preview.literal.notice}</p>{preview.literal.sheets?.map((sheet,index)=><section key={index} aria-label={`Sheet ${sheet.name}`}><h5>{sheet.name}</h5><div style={{overflow:'auto',maxHeight:'60vh'}}><table><thead><tr><th scope="col">Row</th>{Array.from({length:Math.min(20,Math.max(0,...sheet.rows.map(r=>r.length)))},(_,i)=><th key={i} scope="col">{String.fromCharCode(65+i)}</th>)}</tr></thead><tbody>{sheet.rows.map((row,i)=><tr key={i}><th scope="row">{sheet.row_numbers?.[i]??i+1}</th>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div></section>)}</>}{preview.image&&<img src={preview.image} alt={preview.name} style={{maxWidth:'100%',maxHeight:'60vh'}}/>}{preview.text!==undefined&&<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:'60vh',overflow:'auto'}}>{preview.text}</pre>}{preview.unsupported&&<p>This format or size has no inline preview. Download the verified file to use an appropriate viewer.</p>}</section>}
  </section>;
}
