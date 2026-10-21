import {PDF_PREVIEW_BOUNDS,type LiteralFilePreview} from '../api/source';
/** Bound the owner contract before mounting DOM; reject malformed/foreign responses. */
export function literalPreview(value:LiteralFilePreview):LiteralFilePreview{
 if(!value||!['spreadsheet','pdf','unsupported'].includes(value.format)||typeof value.notice!=='string'||value.notice.length>1000)throw Error('Invalid bounded file preview');
 if(value.format==='pdf'){
  if(!Number.isSafeInteger(value.page)||!Number.isSafeInteger(value.page_count)||!Number.isSafeInteger(value.page_limit)||value.page!<1||value.page_count!<1||value.page_count!>PDF_PREVIEW_BOUNDS.documentPages||value.page_limit!==PDF_PREVIEW_BOUNDS.pages||value.page!>Math.min(value.page_count!,PDF_PREVIEW_BOUNDS.pages)||!Number.isSafeInteger(value.width)||!Number.isSafeInteger(value.height)||value.width!<1||value.height!<1||value.width!>PDF_PREVIEW_BOUNDS.dimension||value.height!>PDF_PREVIEW_BOUNDS.dimension||typeof value.text!=='string'||value.text.length>PDF_PREVIEW_BOUNDS.textBytes||typeof value.image_base64!=='string'||value.image_base64.length>Math.ceil(PDF_PREVIEW_BOUNDS.imageBytes/3)*4||value.image_base64.length%4!==0||!/^[A-Za-z0-9+/]+={0,2}$/.test(value.image_base64))throw Error('Invalid bounded PDF preview');
  const header=Uint8Array.from(atob(value.image_base64.slice(0,44)),c=>c.charCodeAt(0));
  if(header.length<24||[137,80,78,71,13,10,26,10].some((v,i)=>header[i]!==v)||String.fromCharCode(...header.slice(12,16))!=='IHDR')throw Error('Invalid PDF raster');
  const view=new DataView(header.buffer);if(view.getUint32(16)!==value.width||view.getUint32(20)!==value.height)throw Error('PDF raster dimensions mismatch');
 }
 if(value.sheets!==undefined){
  if(value.format!=='spreadsheet'||!Array.isArray(value.sheets)||value.sheets.length>3)throw Error('Invalid preview sheet bounds');
  for(const sheet of value.sheets){
   if(typeof sheet.name!=='string'||sheet.name.length>500||!Array.isArray(sheet.rows)||sheet.rows.length>50||sheet.rows.some(row=>!Array.isArray(row)||row.length>20||row.some(cell=>typeof cell!=='string'||cell.length>500)))throw Error('Invalid preview cell bounds');
   if(sheet.row_numbers!==undefined&&(!Array.isArray(sheet.row_numbers)||sheet.row_numbers.length!==sheet.rows.length||sheet.row_numbers.some(n=>!Number.isSafeInteger(n)||n<1||n>1048576)))throw Error('Invalid preview row identity');
  }
 }
 return value;
}
