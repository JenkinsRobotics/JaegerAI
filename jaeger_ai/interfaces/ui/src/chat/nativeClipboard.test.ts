import{it,expect,vi}from'vitest';import{NativeHost}from'./nativeHost';import type{JaegerSource}from'../api/source';
it('requires real native clipboard acknowledgement and never retries/falls back after unknown write',async()=>{
 const post=vi.fn().mockResolvedValueOnce({copied:true}).mockRejectedValueOnce(Error('Lost native reply')).mockResolvedValueOnce({copied:false,recorded:true}).mockResolvedValueOnce({copied:4});
 const previous=window.jaegerNative;window.jaegerNative={post};const host=new NativeHost({}as JaegerSource);
 try{
  await expect(host.copy('owned')).resolves.toBeUndefined();await expect(host.copy('unknown')).rejects.toThrow('Lost native reply');
  await expect(host.copy('recorded only')).rejects.toThrow('unconfirmed');await expect(host.copy('old ambiguous receipt')).rejects.toThrow('unconfirmed');expect(post).toHaveBeenCalledTimes(4);
 }finally{window.jaegerNative=previous;}
});
it('rejects oversized/malformed native previews and leaves unavailable access distinct from empty text',async()=>{
 const {readNativeClipboard}=await import('../platform/nativeClipboard');const previous=window.jaegerNative;
 const post=vi.fn().mockResolvedValueOnce({state:'over_limit',max_bytes:100000}).mockResolvedValueOnce({state:'no_text_or_access_unavailable',max_bytes:100000}).mockResolvedValueOnce({state:'text_available',text:'🌻',max_bytes:3}).mockResolvedValueOnce({state:'text_available',text:'owned',max_bytes:9000000});window.jaegerNative={post};
 try{
  expect((await readNativeClipboard()).state).toBe('over_limit');expect((await readNativeClipboard()).state).toBe('no_text_or_access_unavailable');await expect(readNativeClipboard()).rejects.toThrow('bounds');await expect(readNativeClipboard()).rejects.toThrow('limit');expect(post).toHaveBeenCalledTimes(4);
 }finally{window.jaegerNative=previous;}
});
