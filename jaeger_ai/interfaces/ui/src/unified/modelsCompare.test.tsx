import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { inventory, isDefault, parseNdjson, type Catalog, type LocalModel } from "./models";
import { matches, ModelsPage } from "./ModelsPage";
import { ComparePage, pickDefaults, toResult } from "./ComparePage";
import { ToastProvider } from "./ui";

const local: LocalModel[] = [
  { name: "qwen3:4b", size: 2.5e9, family: "qwen3", parameters: "4.0B", quantization: "Q4_K_M", context: 262144, loaded: true, vram: 3e9 },
  { name: "gemma4:12b", size: 8e9, family: "gemma4", parameters: "11.9B", quantization: "Q4_K_M", context: 131072, loaded: false },
  { name: "nomic-embed-text:latest", size: 2.7e8, family: "nomic-bert", loaded: false },
  { name: "glm-5.3:cloud", size: 290, loaded: false },
];
const catalog: Catalog = { active_provider: "ollama-cloud", default_model: "glm-5.3:cloud", default_model_full_id: "@ollama-cloud:glm-5.3:cloud", groups: [
  { provider: "Ollama Cloud", provider_id: "ollama-cloud", status: "online", endpoint: "https://ollama.com", models: [{ id: "@ollama-cloud:glm-5.3:cloud", name: "glm-5.3:cloud" }] },
  { provider: "Ollama Local", provider_id: "ollama-local", status: "online", endpoint: "http://127.0.0.1:11434", models: [{ id: "a", name: "qwen3:4b", capabilities: ["completion", "tools"] }, { id: "b", name: "gemma4:12b" }] },
] };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("model inventory", () => {
  it("groups by provider, local first, enriched with Ollama details, embeddings kept", () => {
    const g = inventory(catalog, local);
    expect(g.map((x) => x.id)).toEqual(["ollama-local", "ollama-cloud"]);
    expect(g[0].rows.map((r) => r.name)).toEqual(["qwen3:4b", "gemma4:12b", "nomic-embed-text:latest"]);
    expect(g[0].rows[0].local?.quantization).toBe("Q4_K_M");
  });
  it("still lists local Ollama models when the catalog is unavailable", () => {
    const g = inventory(null, local);
    expect(g.find((x) => x.id === "ollama-local")?.rows).toHaveLength(3);
    expect(g.find((x) => x.id === "ollama-cloud")?.rows.map((r) => r.name)).toEqual(["glm-5.3:cloud"]);
  });
  it("knows the default and filters by search and kind", () => {
    expect(isDefault(catalog, "ollama-cloud", "glm-5.3:cloud")).toBe(true);
    expect(isDefault(catalog, "ollama-local", "qwen3:4b")).toBe(false);
    const rows = inventory(catalog, local).flatMap((g) => g.rows);
    expect(rows.filter((r) => matches(r, "", "loaded")).map((r) => r.name)).toEqual(["qwen3:4b"]);
    expect(rows.filter((r) => matches(r, "", "embedding")).map((r) => r.name)).toEqual(["nomic-embed-text:latest"]);
    expect(rows.filter((r) => matches(r, "", "cloud")).map((r) => r.name)).toEqual(["glm-5.3:cloud"]);
    expect(rows.filter((r) => matches(r, "gemma q4", "all")).map((r) => r.name)).toEqual(["gemma4:12b"]);
  });
});

describe("compare helpers", () => {
  it("parses NDJSON across chunk boundaries", () => {
    const a = parseNdjson('{"type":"delta","text":"He"}\n{"type":"del');
    expect(a.events).toEqual([{ type: "delta", text: "He" }]);
    expect(parseNdjson(a.rest + 'ta","text":"y"}\n').events).toEqual([{ type: "delta", text: "y" }]);
  });
  it("defaults to the smallest local models and records results", () => {
    expect(pickDefaults(local.filter((m) => !m.name.includes("embed")))).toEqual(["qwen3:4b", "gemma4:12b"]);
    expect(toResult({ model: "m:1", text: "x", thinking: "", state: "done", metrics: { elapsed_s: 1, ttft_s: 0.2, tokens_per_s: 9 } })).toMatchObject({ model: "m:1", response: "x", tokens_per_s: 9 });
  });
});

const ndjson = (lines: unknown[]) => new Response(new ReadableStream({ start(c) { for (const l of lines) c.enqueue(new TextEncoder().encode(JSON.stringify(l) + "\n")); c.close(); } }), { headers: { "Content-Type": "application/x-ndjson" } });

describe("Compare page", () => {
  it("streams each model's answer with real metrics, saves the run and votes", async () => {
    const calls: { url: string; body?: unknown; method?: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined; calls.push({ url, body, method: init?.method });
      if (url === "/v1/models/local") return Response.json({ models: local, pulls: [] });
      if (url === "/v1/compare/history" && !init?.method) return Response.json({ runs: [] });
      if (url === "/v1/compare/stream") return ndjson([{ type: "start", model: body.model, local: true }, { type: "delta", text: `Answer from ${body.model}` }, { type: "done", model: body.model, elapsed_s: 1.5, ttft_s: 0.3, eval_count: 30, prompt_eval_count: 9, tokens_per_s: body.model === "qwen3:4b" ? 40 : 12, load_s: 0.1, cost_usd: 0 }]);
      if (url === "/v1/compare/history") return Response.json({ id: "abcdefabcdef", created_at: 1, prompt: body.prompt, results: body.results, winner: null }, { status: 201 });
      if (url.startsWith("/v1/compare/history/")) return Response.json({ id: "abcdefabcdef", created_at: 1, prompt: "p", results: [], winner: body.winner });
      return new Response("{}", { status: 404 });
    }));
    render(<ToastProvider><ComparePage /></ToastProvider>);
    await waitFor(() => expect((screen.getAllByRole("combobox")[0] as HTMLSelectElement).value).toBe("qwen3:4b"));
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "hi" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Run 2" })); });
    await waitFor(() => expect(screen.getByText("Answer from gemma4:12b")).toBeTruthy());
    expect(screen.getByText("Answer from qwen3:4b")).toBeTruthy();
    expect(screen.getAllByText("40 tok/s").length).toBe(1);
    expect(screen.getByText("Fastest")).toBeTruthy();
    expect(screen.getAllByText("$0 (local)")).toHaveLength(2);
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/compare/history" && c.method === "POST")).toBe(true));
    const saved = calls.find((c) => c.url === "/v1/compare/history" && c.method === "POST")!.body as { results: { model: string; eval_count: number }[] };
    expect(saved.results.map((r) => r.model)).toEqual(["qwen3:4b", "gemma4:12b"]);
    expect(saved.results[0].eval_count).toBe(30);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "gemma4:12b" })); });
    expect(calls.at(-1)).toMatchObject({ url: "/v1/compare/history/abcdefabcdef", method: "PUT", body: { winner: "gemma4:12b" } });
  });
});

describe("Models page", () => {
  it("shows grouped inventory and confirms before removing or changing the default", async () => {
    const calls: { url: string; method?: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url === "/v1/models/local") return Response.json({ models: local, pulls: [] });
      if (url === "/api/models") return Response.json(catalog);
      if (url === "/v1/models/hardware") return Response.json({ chip: "Apple M1 Max", memory: 32 * 2 ** 30, cpu_cores: 10, perf_cores: 8, gpu_cores: 24, note: "" });
      if (url === "/api/providers") return Response.json({ providers: [] });
      return Response.json({ ok: true });
    }));
    render(<ToastProvider><ModelsPage /></ToastProvider>);
    await waitFor(() => expect(screen.getByRole("region", { name: "Ollama Local" })).toBeTruthy());
    expect(screen.getByRole("region", { name: "Ollama Cloud" })).toBeTruthy();
    expect(screen.getByText("Default")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove qwen3:4b" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Remove" })); });
    expect(calls.find((c) => c.method === "DELETE")?.url).toBe("/v1/models/local/qwen3%3A4b");
    fireEvent.click(screen.getByRole("button", { name: "Make gemma4:12b the default" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Make default" })); });
    expect(calls.find((c) => c.url === "/api/default-model")).toMatchObject({ method: "POST", body: { model: "gemma4:12b", provider: "ollama-local" } });
    expect(screen.queryByRole("button", { name: "Remove glm-5.3:cloud" })).toBeNull();
  });
});
