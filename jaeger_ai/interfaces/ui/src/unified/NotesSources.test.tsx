import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { NotesSources } from "./NotesSources";

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

async function mount(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (url: string) => {
    const key = Object.keys(responses).find((k) => String(url).startsWith(k))!;
    return new Response(JSON.stringify(responses[key]), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<NotesSources />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  return { el, fetchMock };
}

it("says when notes sources are off and never searches", async () => {
  const { el, fetchMock } = await mount({ "/api/notes/sources": { enabled: false, sources: [] } });
  expect(el.textContent).toContain("Notes sources are off");
  expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/search"))).toBe(false);
});

it("lists sources and opens a recent Joplin note", async () => {
  const { el } = await mount({
    "/api/notes/sources": { enabled: true, sources: [{ name: "joplin", label: "Joplin", enabled: true, active: true, status: "running", tool_count: 3 }], recent_ai_notes: [{ id: "n1", title: "Plan" }] },
    "/api/notes/item": { note: { id: "n1", title: "Plan", body: "hello body" } },
  });
  expect(el.textContent).toContain("Joplin");
  const row = [...el.querySelectorAll("button")].find((b) => b.textContent === "Plan")!;
  await act(async () => { row.click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(el.textContent).toContain("hello body");
});
