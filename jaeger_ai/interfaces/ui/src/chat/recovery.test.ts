import { beforeEach } from "vitest";
beforeEach(() => localStorage.clear());
import { describe, it, expect, vi } from "vitest";
import { WebHost } from "./webHost";
import { mapEvent } from "./eventMap";
import { messagesToTurns } from "./webHost";
import type { JaegerSource } from "../api/source";
import type { ChatPart } from "./host";

describe("request outcome truth", () => {
  it("retains unknown execution and tool failure distinctly", () => {
    expect(mapEvent({ event: "turn.unknown" })?.state).toBe("unknown");
    expect(mapEvent({ event: "tool.failed", payload: { call_id: "c", error: "denied" } })?.parts[0]).toMatchObject({ state: "failed" });
    expect(messagesToTurns([{ role: "assistant", parts: [{ type: "tool", status: "error" }] }])[0].parts[0]).toMatchObject({ state: "failed" });
  });
  it("looks up the original request after a lost POST response and never resends", async () => {
    const send = vi.fn(async () => { throw new TypeError("response lost"); });
    const requestStatus = vi.fn(async () => ({ request_id: "owned-r", session_id: "owned-s", status: "completed", result: { output: "REAL-RECEIPT" } }));
    const source = { kind: "live", send, requestStatus, stream: async () => {} } as unknown as JaegerSource;
    const parts: ChatPart[] = [];
    const outcome = await new WebHost(source, []).startTurn({ sessionId: "owned-s", turnId: "owned-r", message: "owned fixture" }, p => parts.push(p)).done;
    expect(outcome.state).toBe("complete");
    expect(requestStatus).toHaveBeenCalledWith("owned-s", "owned-r");
    expect(send).toHaveBeenCalledTimes(1);
    expect(parts).toContainEqual({ kind: "markdownContent", text: "REAL-RECEIPT" });
  });
  it("lookup transport failure remains unknown, never a safe retry", async () => {
    const source = { kind: "live", send: async () => { throw new TypeError("offline"); }, requestStatus: async () => { throw new TypeError("offline"); } } as unknown as JaegerSource;
    expect((await new WebHost(source, []).startTurn({ sessionId: "s", turnId: "r", message: "fixture" }, () => {}).done).state).toBe("unknown");
  });
});

it("Stop during attachment preparation does not dispatch a new turn", async () => {
 let finish!: (value:{attachment_id:string})=>void;
 const send=vi.fn();
 const source={kind:"live",addAttachment:()=>new Promise(resolve=>{finish=resolve as typeof finish;}),send} as unknown as JaegerSource;
 const handle=new WebHost(source).startTurn({sessionId:"s",turnId:"preparing-r",message:"fixture",attachments:[{name:"fixture",mimeType:"text/plain",path:"/owned"} as never]},()=>{});
 handle.cancel();finish({attachment_id:"owned-attachment"});
 expect((await handle.done).state).toBe("cancelled");expect(send).not.toHaveBeenCalled();
});

it("discovers existing unknown work without a local journal and never grants it draft ownership", async () => {
 const source={kind:"live",sessionControl:async()=>({latest_request:{request_id:"other-device-r",status:"execution_unknown"}}),requestStatus:async()=>({request_id:"other-device-r",session_id:"owned-home",status:"execution_unknown",input_text:"prior request"})} as unknown as JaegerSource;
 const host=new WebHost(source);const intent=await host.findPendingIntent("owned-home");
 expect(intent).toMatchObject({requestId:"other-device-r",deviceDraft:false});
 const parts:ChatPart[]=[];
 expect((await host.recoverTurn(intent!,p=>parts.push(p)).done).state).toBe("unknown");
 expect(parts.at(-1)).toMatchObject({kind:"warning"});
});
it('Stop during bytes staging aborts transfer and never dispatches or invokes execution Stop',async()=>{
 let entered!:(signal:AbortSignal)=>void;const ready=new Promise<AbortSignal>(resolve=>{entered=resolve;});
 const send=vi.fn(),cancel=vi.fn();const source={kind:'live',send,cancel,uploadAttachment:vi.fn(async(_sid,_body,_key,options)=>{
  entered(options.signal);return await new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Upload paused','AbortError')),{once:true}));
 })} as unknown as JaegerSource;
 const handle=new WebHost(source).startTurn({sessionId:'owned-stage',turnId:'owned-stage-stop',message:'fixture',attachments:[{name:'fixture.bin',mimeType:'application/octet-stream',data:btoa('fixture')}]},()=>{});
 const signal=await ready;handle.cancel();expect(signal.aborted).toBe(true);expect((await handle.done).state).toBe('cancelled');expect(send).not.toHaveBeenCalled();expect(cancel).not.toHaveBeenCalled();
});
