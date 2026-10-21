import {it,expect} from 'vitest';import {literalPreview} from './literalPreview';
it('rejects unbounded and malformed derived previews before DOM mounting',()=>{
 expect(()=>literalPreview({format:'spreadsheet',notice:'fixture',sheets:[{name:'x',rows:[['x'.repeat(501)]]}]})).toThrow('cell bounds');
 expect(()=>literalPreview({format:'spreadsheet',notice:'fixture',sheets:[{name:'x',rows:[['x']],row_numbers:[-1]}]})).toThrow('row identity');
 expect(literalPreview({format:'unsupported',notice:'No PDF renderer is available'}).format).toBe('unsupported');
});
it('accepts only bounded static PNG pages with exact dimensions and page identity',()=>{
 const page={format:'pdf' as const,notice:'Static image only',page:1,page_count:2,page_limit:20,width:1,height:1,text:'<script>literal</script>',image_base64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2tI8AAAAASUVORK5CYII='};
 expect(literalPreview(page).format).toBe('pdf');
 expect(()=>literalPreview({...page,page:3})).toThrow('PDF preview');
 expect(()=>literalPreview({...page,width:2})).toThrow('dimensions');
 expect(()=>literalPreview({...page,image_base64:btoa('<svg>never mount</svg>')})).toThrow('PDF raster');
 expect(()=>literalPreview({...page,text:'x'.repeat(64001)})).toThrow('PDF preview');
});
