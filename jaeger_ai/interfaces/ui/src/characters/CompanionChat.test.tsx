import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { CompanionChat } from "./CompanionChat";

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

it("sends the message and history to the companion route and shows the reply", async () => {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return Response.json({ reply: "Oh. It's you.", model: "qwen2.5:3b", recalled: [] });
  }));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<CompanionChat characterId="glados" name="GLaDOS" />); });
  const input = el.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "hello");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(calls[0]).toEqual({ url: "/v1/companion/glados/chat", body: { message: "hello", history: [] } });
  expect(el.textContent).toContain("Oh. It's you.");
});

it("shows an error when the local model is down", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: "local model unavailable" }, { status: 503 })));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<CompanionChat characterId="glados" name="GLaDOS" />); });
  const input = el.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "hi");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(el.querySelector("[role=alert]")).not.toBeNull();
});
