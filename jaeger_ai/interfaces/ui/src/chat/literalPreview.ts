import type {LiteralFilePreview} from '../api/source';
/** Bound the owner contract before mounting DOM; reject malformed/foreign responses. */
export function literalPreview(value:LiteralFilePreview):LiteralFilePreview{
 if(!value||!['spreadsheet','unsupported'].includes(value.format)||typeof value.notice!=='string'||value.notice.length>1000)throw Error('Invalid bounded file preview');
 if(value.sheets!==undefined){
  if(value.format!=='spreadsheet'||!Array.isArray(value.sheets)||value.sheets.length>3)throw Error('Invalid preview sheet bounds');
  for(const sheet of value.sheets){
   if(typeof sheet.name!=='string'||sheet.name.length>500||!Array.isArray(sheet.rows)||sheet.rows.length>50||sheet.rows.some(row=>!Array.isArray(row)||row.length>20||row.some(cell=>typeof cell!=='string'||cell.length>500)))throw Error('Invalid preview cell bounds');
   if(sheet.row_numbers!==undefined&&(!Array.isArray(sheet.row_numbers)||sheet.row_numbers.length!==sheet.rows.length||sheet.row_numbers.some(n=>!Number.isSafeInteger(n)||n<1||n>1048576)))throw Error('Invalid preview row identity');
  }
 }
 return value;
}
