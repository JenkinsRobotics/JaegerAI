import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { JaegerMark } from "./JaegerMark";
import { applyLogo, chooseLogo, LOGOS, storedLogo, syncLogoFromGateway } from "./logo";

describe("Jaeger logo (J-085)", () => {
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); applyLogo({ id: "shield-j" }); document.body.innerHTML = ""; });
  it("renders every built-in as a vector and follows the choice live", async () => {
    const el = document.createElement("div"); document.body.appendChild(el);
    await act(async () => createRoot(el).render(<JaegerMark />));
    for (const l of LOGOS) {
      await act(async () => applyLogo({ id: l.id }));
      expect(el.querySelector(".jg-mark")?.getAttribute("data-logo")).toBe(l.id);
      expect(el.querySelector(".jg-mark svg")).not.toBeNull();
    }
    expect(storedLogo().id).toBe("classic");
  });
  it("saves the choice through the Gateway and keeps it locally when offline", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    expect(await chooseLogo("j")).toBe(false);
    expect(storedLogo().id).toBe("j");
    expect(f).toHaveBeenCalled();
  });
  it("adopts the Gateway's custom logo", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ logo: "custom", custom: { data_url: "data:image/png;base64,AAAA" } }), { headers: { "content-type": "application/json" } }));
    const s = await syncLogoFromGateway();
    expect(s).toEqual({ id: "custom", custom: "data:image/png;base64,AAAA" });
  });
});
