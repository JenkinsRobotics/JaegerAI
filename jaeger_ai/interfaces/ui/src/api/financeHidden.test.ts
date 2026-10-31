import {expect,it} from 'vitest';import {GatewayClient} from './gateway';
it('exposes no finance controls while Finance is deprecated, so Settings hides Spending limits',()=>{
 expect(new GatewayClient().finance).toBeUndefined();
});
