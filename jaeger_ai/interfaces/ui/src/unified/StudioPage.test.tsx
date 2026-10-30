import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { StudioPage } from "./StudioPage";
import { ToastProvider } from "./ui";
import type { JaegerSource } from "../api/source";

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

it("shows an unavailable provider disabled with its setup note and never generates", async () => {
  const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("providers")
    ? { providers: [{ id: "local-sdxl-turbo", name: "SDXL-Turbo", kind: "local", available: false, cost: "free", note: "weights not downloaded" }] }
    : { assets: [] }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<ToastProvider><StudioPage source={{} as JaegerSource} agents={[]} onNavigate={() => {}} /></ToastProvider>); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const radio = el.querySelector<HTMLInputElement>('input[name="provider"]')!;
  expect(radio.disabled).toBe(true);
  expect(el.textContent).toContain("weights not downloaded");
  expect(el.querySelector<HTMLButtonElement>(".jg-u-btn--primary")!.disabled).toBe(true);
  expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/generate"))).toBe(false);
});
