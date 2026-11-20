import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { CompanionChat } from "./CompanionChat";

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

function sseResponse(events: Array<Record<string, unknown>>): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const ev of events) {
        const kind = String(ev.type || "message");
        controller.enqueue(encoder.encode(`event: ${kind}\ndata: ${JSON.stringify(ev)}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

it("streams deltas from /chat/stream and displays the final reply", async () => {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return sseResponse([
      { type: "delta", character_id: "glados", text: "Oh. " },
      { type: "delta", character_id: "glados", text: "It's you." },
      { type: "done", character_id: "glados", reply: "Oh. It's you.", model: "qwen3.5:9b", recalled: [], interrupted: false },
    ]);
  }));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<CompanionChat characterId="glados" name="GLaDOS" />); });
  const input = el.querySelector<HTMLInputElement>("input[aria-label=Message]")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "hello");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
  expect(calls[0]).toEqual({ url: "/v1/companion/glados/chat/stream", body: { message: "hello", history: [] } });
  expect(el.textContent).toContain("Oh. It's you.");
});

it("shows an error when the local model is down", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: "local model unavailable" }, { status: 503 })));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<CompanionChat characterId="glados" name="GLaDOS" />); });
  const input = el.querySelector<HTMLInputElement>("input[aria-label=Message]")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "hi");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
  expect(el.querySelector("[role=alert]")).not.toBeNull();
});

it("supports convening a Character Council with Truth epistemic synthesis", async () => {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return Response.json({
      mode: "council",
      topic: "Local vs cloud?",
      model: "qwen3.5:9b",
      turns: [
        { character_id: "glados", name: "GLaDOS", reply: "Local hardware obeys me." },
        { character_id: "jarvis", name: "J.A.R.V.I.S.", reply: "Hybrid balances latency and privacy." },
      ],
      truth_synthesis: {
        character_id: "truth",
        name: "Truth",
        reply: "Measure actual RAM headroom and latency before choosing.",
      },
    });
  }));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => {
    createRoot(el).render(
      <CompanionChat
        characterId="glados"
        name="GLaDOS"
        peers={[
          { id: "glados", name: "GLaDOS" },
          { id: "jarvis", name: "J.A.R.V.I.S." },
        ]}
      />,
    );
  });
  const councilTab = Array.from(el.querySelectorAll("button")).find((b) => b.textContent === "Council")!;
  await act(async () => { councilTab.click(); });
  const checkbox = el.querySelector<HTMLInputElement>(".companion-peer-option input[type=checkbox]")!;
  await act(async () => { checkbox.click(); });
  const input = el.querySelector<HTMLInputElement>("input[aria-label=Message]")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "Local vs cloud?");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
  expect(calls[0]).toEqual({
    url: "/v1/companion/council",
    body: {
      characters: ["glados", "jarvis"],
      topic: "Local vs cloud?",
      history: [],
      include_truth_synthesis: true,
    },
  });
  expect(el.textContent).toContain("Local hardware obeys me.");
  expect(el.textContent).toContain("Hybrid balances latency and privacy.");
  expect(el.querySelector("[aria-label='Truth synthesis']")?.textContent).toContain(
    "Measure actual RAM headroom and latency before choosing.",
  );
});
