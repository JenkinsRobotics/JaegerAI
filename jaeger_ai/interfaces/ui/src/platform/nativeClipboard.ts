import{nativeBridge}from'./native';
export type ClipboardPreview={state:'text_available';text:string;max_bytes:number}|{state:'over_limit'|'no_text_or_access_unavailable'|'not_performed';max_bytes:number};
/** No browser permission fallback or automatic retry after native IPC. */
export async function writeNativeClipboard(text:string){
 const bridge=nativeBridge();if(!bridge)return false;
 const receipt=await bridge.post('clipboard.write',{text}) as {copied?:boolean};
 if(receipt?.copied!==true)throw Error('Native clipboard write unconfirmed; no automatic retry');
 return true;
}
export async function readNativeClipboard():Promise<ClipboardPreview>{
 const bridge=nativeBridge();if(!bridge)throw Error('Local clipboard preview needs the native host; browser clipboard permission is not requested');
 const receipt=await bridge.post('clipboard.read') as Partial<ClipboardPreview>;
 // Independent renderer ceiling, even if an older/untrusted native reply advertises more.
 if(!receipt||typeof receipt.max_bytes!=='number'||!Number.isSafeInteger(receipt.max_bytes)||receipt.max_bytes<=0||receipt.max_bytes>1_000_000)throw Error('Invalid clipboard preview limit');
 if(receipt.state==='text_available'){
  if(typeof receipt.text!=='string'||new TextEncoder().encode(receipt.text).byteLength>receipt.max_bytes!)throw Error('Clipboard preview exceeds native or renderer bounds');
  return receipt as ClipboardPreview;
 }
 if(!['over_limit','no_text_or_access_unavailable','not_performed'].includes(receipt.state??''))throw Error('Unsupported clipboard preview state');
 return {state:receipt.state as 'over_limit'|'no_text_or_access_unavailable'|'not_performed',max_bytes:receipt.max_bytes!};
}
