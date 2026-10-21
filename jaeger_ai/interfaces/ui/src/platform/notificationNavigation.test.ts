import {it,expect,vi}from'vitest';
import{notificationNavigation,notificationConversation,localConversationLink}from'./notificationNavigation';
import type{Agent}from'../api/types';
it('accepts only navigation and resolves the actual session bot through the authenticated owner',async()=>{
 expect(notificationNavigation({target:'notifications'})).toEqual({target:'notifications'});
 for(const row of [{target:'conversation',session_id:'https://example.com'},{target:'conversation',session_id:'home',approve:true},{target:'notifications',run:'tool'}])expect(notificationNavigation(row)).toBeNull();
 const read=vi.fn(async(id:string)=>({session_id:id,agent_id:'specialist-beta'}));
 const agents=[{id:'specialist-alpha'},{id:'specialist-beta'}]as Agent[];
 expect(await notificationConversation(read,agents,'owned-beta-home')).toEqual({type:'agent',agentId:'specialist-beta',sessionId:'owned-beta-home'});
 await expect(notificationConversation(async()=>({session_id:'other',agent_id:'specialist-beta'}),agents,'owned-beta-home')).rejects.toThrow('unavailable');
 await expect(notificationConversation(read,[{id:'specialist-alpha'}]as Agent[],'owned-beta-home')).rejects.toThrow('exposed bot identity');
 await expect(notificationConversation(read,agents,'../escape')).rejects.toThrow('Invalid');
 expect(read).toHaveBeenCalledTimes(2);
});

it('builds links from actual selected/home session IDs, never bot display names or execution authority',async()=>{
 const {conversationIdForAgent}=await import('../api/agentActions');const home=vi.fn(async()=> 'owned-beta:home');
 expect(localConversationLink(await conversationIdForAgent('beta',home,{agentId:'beta',sessionId:'owned-beta:existing'}))).toBe('jaeger://conversation/owned-beta%3Aexisting');expect(home).not.toHaveBeenCalled();
 expect(localConversationLink(await conversationIdForAgent('beta',home,{agentId:'alpha',sessionId:'other'}))).toBe('jaeger://conversation/owned-beta%3Ahome');expect(home).toHaveBeenCalledWith('beta');
 for(const bad of ['../escape','https://remote','..'])expect(()=>localConversationLink(bad)).toThrow();
});
