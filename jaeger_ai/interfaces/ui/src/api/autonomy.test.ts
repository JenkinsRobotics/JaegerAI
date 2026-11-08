import { expect, it, vi } from "vitest";
import { GatewayClient } from "./gateway";

it("posts the selected autonomy mode to the Gateway", async () => {
  const client = new GatewayClient();
  const json = vi.spyOn(client, "json").mockResolvedValue({ autonomy: "auto", options: ["ask", "scoped", "auto"] });
  await client.setRuntimeAutonomy("auto");
  expect(json).toHaveBeenCalledExactlyOnceWith("/v1/runtime/autonomy", { autonomy: "auto" });
});

it('reads and changes the existing Gateway interaction tier', async () => {
 const client=new GatewayClient();
 const json=vi.spyOn(client,'json').mockResolvedValue({tier:'chat',options:['chat','agent','jaeger']});
 await client.runtimeTier();await client.setRuntimeTier('chat');
 expect(json.mock.calls).toEqual([['/v1/runtime/tier'],['/v1/runtime/tier',{tier:'chat'}]]);
});
