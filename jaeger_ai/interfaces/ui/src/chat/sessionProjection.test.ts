import {expect,it} from 'vitest';
import {mergeSessionSnapshot} from './sessionProjection';
import type {ChatSession} from './host';
it('late snapshot cannot erase streamed text, settle unknown work, or remove older pages',()=>{
 const current:ChatSession={id:'owned',title:'owned',turns:[{turnId:'old',message:'old',state:'complete',parts:[],createdAt:1},{turnId:'live',message:'work',state:'pending',parts:[{kind:'markdownContent',text:'ab'}],createdAt:2},{turnId:'unknown',message:'uncertain',state:'unknown',parts:[],createdAt:3}]};
 const snapshot:ChatSession={id:'owned',title:'owned',turns:[{turnId:'live',message:'work',state:'complete',parts:[],createdAt:2}]};
 const merged=mergeSessionSnapshot(current,snapshot);
 expect(merged.turns.map(t=>t.turnId)).toEqual(['old','live','unknown']);
 expect(merged.turns[1]).toMatchObject({state:'pending',parts:[{kind:'markdownContent',text:'ab'}]});
 expect(merged.turns[2].state).toBe('unknown');
 expect(mergeSessionSnapshot(current,{id:'different',title:'different',turns:[]})).toEqual({id:'different',title:'different',turns:[]});
});
