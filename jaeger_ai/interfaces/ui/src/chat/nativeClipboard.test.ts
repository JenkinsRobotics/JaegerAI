import{it,expect,vi}from'vitest';import{NativeHost}from'./nativeHost';import type{JaegerSource}from'../api/source';
it('requires real native clipboard acknowledgement and never retries/falls back after unknown write',async()=>{
 const post=vi.fn().mockResolvedValueOnce({copied:true}).mockRejectedValueOnce(Error('Lost native reply')).mockResolvedValueOnce({copied:false,recorded:true}).mockResolvedValueOnce({copied:4});
 const previous=window.jaegerNative;window.jaegerNative={post};const host=new NativeHost({}as JaegerSource);
 try{
  await expect(host.copy('owned')).resolves.toBeUndefined();await expect(host.copy('unknown')).rejects.toThrow('Lost native reply');
  await expect(host.copy('recorded only')).rejects.toThrow('unconfirmed');await expect(host.copy('old ambiguous receipt')).rejects.toThrow('unconfirmed');expect(post).toHaveBeenCalledTimes(4);
 }finally{window.jaegerNative=previous;}
});
