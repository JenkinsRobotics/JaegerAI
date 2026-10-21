import {it,expect} from 'vitest';import {literalPreview} from './literalPreview';
it('rejects unbounded and malformed derived previews before DOM mounting',()=>{
 expect(()=>literalPreview({format:'spreadsheet',notice:'fixture',sheets:[{name:'x',rows:[['x'.repeat(501)]]}]})).toThrow('cell bounds');
 expect(()=>literalPreview({format:'spreadsheet',notice:'fixture',sheets:[{name:'x',rows:[['x']],row_numbers:[-1]}]})).toThrow('row identity');
 expect(literalPreview({format:'unsupported',notice:'No PDF renderer is available'}).format).toBe('unsupported');
});
