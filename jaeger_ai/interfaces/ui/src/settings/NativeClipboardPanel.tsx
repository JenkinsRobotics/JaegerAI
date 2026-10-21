import{useEffect,useRef,useState}from'react';
import{nativeBridge}from'../platform/native';
import{readNativeClipboard,writeNativeClipboard,type ClipboardPreview}from'../platform/nativeClipboard';
/** Explicit ephemeral OS text operations, not conversation input or a remote clipboard. */
export function NativeClipboardPanel(){
 const [preview,setPreview]=useState<ClipboardPreview>(),[text,setText]=useState(''),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[busy,setBusy]=useState(false);
 const generation=useRef(0),locked=useRef(false);useEffect(()=>()=>{generation.current++;},[]);
 const read=async()=>{if(locked.current)return;locked.current=true;setBusy(true);setPreview(undefined);setError(undefined);setNotice(undefined);const owner=++generation.current;
  try{const result=await readNativeClipboard();if(owner===generation.current)setPreview(result);}catch(e){if(owner===generation.current)setError(String(e));}finally{locked.current=false;if(owner===generation.current)setBusy(false);}};
 const write=async()=>{if(locked.current||!text)return;locked.current=true;setBusy(true);setError(undefined);setNotice(undefined);const owner=++generation.current;
  try{if(!await writeNativeClipboard(text))throw Error('Native clipboard is unavailable');if(owner===generation.current)setNotice('Native clipboard write acknowledged. No conversation or remote clipboard was changed.');}catch(e){if(owner===generation.current)setError(String(e)+'. No automatic retry; clipboard outcome may be unknown.');}finally{locked.current=false;if(owner===generation.current)setBusy(false);}};
 const available=Boolean(nativeBridge());
 return <section aria-label="Local clipboard"><h3>Local clipboard</h3><p>Explicit plain-text preview and copy on this Mac only. Nothing is read on opening this panel, persisted, attached or sent to a bot. Screen/input access and remote VNC clipboard are separate and are not granted here.</p>
  {!available&&<p>This browser has no native clipboard broker. No browser permission request or fallback is attempted.</p>}
  <button type="button" disabled={!available||busy} onClick={()=>void read()}>Read local clipboard preview</button><button type="button" disabled={!preview||busy} onClick={()=>setPreview(undefined)}>Clear clipboard preview</button>
  {busy&&<p role="status">Waiting for native clipboard response…</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  {preview&&<><p>Native preview ceiling: {preview.max_bytes} bytes.</p>{preview.state==='text_available'?<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:'30vh',overflow:'auto'}}>{preview.text}</pre>:<p>{preview.state==='over_limit'?'Clipboard text exceeds the preview bound; content withheld.':preview.state==='not_performed'?'The native fixture did not read clipboard content.':'No plain text or clipboard access is available; no permission state is inferred.'}</p>}</>}
  <label>Text to copy (not saved)<textarea aria-label="Local clipboard text" value={text} maxLength={1_000_000} disabled={!available||busy} onChange={e=>setText(e.target.value)}/></label><button type="button" disabled={!available||busy||!text} onClick={()=>void write()}>Write entered text to local clipboard</button>
 </section>;
}
