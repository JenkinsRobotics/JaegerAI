import { describe, expect, it } from "vitest";
import { actionLabel, groupApps, statusTone, type AgentApp } from "./agentApps";

const app = (id: string, running = false, installed = true): AgentApp => ({ id, name: id, kind: "macapp", installed, running, actions: [], surfaces: [], notes: "", configs: [] });

describe("agent apps", () => {
  it("groups installed apps, running first, services separate", () => {
    const g = groupApps([app("b"), app("a", true), app("jaeger-gateway", true), app("z", false, false)]);
    expect(g.map((x) => x.title)).toEqual(["Agent apps", "Jaeger services"]);
    expect(g[0].apps.map((a) => a.id)).toEqual(["a", "b"]);
  });
  it("labels and tones", () => {
    expect(actionLabel("invoke:exec")).toBe("Run exec");
    expect(actionLabel("restart")).toBe("Restart");
    expect(statusTone("done")).toBe("ok");
    expect(statusTone("failed")).toBe("bad");
  });
});
