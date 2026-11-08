import {expect,it} from 'vitest';
import {conversationPath,conversationLink,validConversationId} from './conversationLocation';

it('shares one exact conversation without copying client flags or credentials',()=>{
 expect(conversationPath('agent-native:jaeger','?host=macos&mock=1&token=secret')).toBe('/chat?session=agent-native%3Ajaeger&host=macos&mock=1');
 expect(conversationLink('agent-native:jaeger','https://studio.test:8443')).toBe('https://studio.test:8443/chat?session=agent-native%3Ajaeger');
});
it('rejects empty or ambiguous conversation identities',()=>{
 for(const id of ['', 'other/chat','x?session=y',' x','x\n','a'.repeat(257)]){
  expect(validConversationId(id)).toBe(false);expect(()=>conversationPath(id)).toThrow('Invalid conversation ID');
 }
});
