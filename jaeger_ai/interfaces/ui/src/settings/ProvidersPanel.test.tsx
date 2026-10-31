import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProvidersPanel } from "./ProvidersPanel";
import { modelLabel, runnableCli, type CliProvider } from "../unified/models";

const codex: CliProvider = { id: "codex", label: "OpenAI Codex", installed: true, path: "/opt/homebrew/bin/codex", version: "codex-cli 0.156.1", signed_in: true, status_note: "Logged in using ChatGPT", login_command: "codex login", streams: "messages", models: [{ id: "gpt-6-luna", label: "GPT-6-Luna", context: 272000 }, { id: "gpt-6-sol", label: "GPT-6-Sol" }], enabled: true, selected_models: ["gpt-6-luna"], state: "ready" };
const claude: CliProvider = { ...codex, id: "claude", label: "Claude Code", signed_in: false, status_note: "Run `claude` then /login in Terminal", login_command: "claude, then /login", streams: "tokens", models: [], enabled: false, selected_models: [], state: "needs-sign-in" };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("CLI provider helpers", () => {
  it("offers only enabled, signed-in, selected models and labels them", () => {
    expect(runnableCli([codex, claude]).map((x) => [x.provider.id, x.models.map((m) => m.id)])).toEqual([["codex", ["gpt-6-luna"]]]);
    expect(modelLabel("cli:codex:gpt-6-luna", [codex])).toBe("OpenAI Codex · GPT-6-Luna");
    expect(modelLabel("qwen3:4b")).toBe("qwen3:4b");
  });
});

describe("Settings → Providers", () => {
  it("shows detection, sign-in guidance, and saves enable and model picks", async () => {
    const puts: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith("/v1/providers/cli/")) { const body = JSON.parse(String(init!.body)); puts.push({ url, body }); return Response.json({ ...codex, ...body, selected_models: body.models ?? codex.selected_models, enabled: body.enabled ?? true }); }
      if (url.startsWith("/v1/providers/cli")) return Response.json({ providers: [codex, claude] });
      if (url === "/v1/models/local") return Response.json({ models: [{ name: "qwen3:4b", size: 2.5e9, loaded: false }, { name: "glm-5.3:cloud", size: 290, loaded: false }], pulls: [] });
      return new Response("{}", { status: 404 });
    }));
    render(<ProvidersPanel />);
    await waitFor(() => expect(screen.getByRole("article", { name: "OpenAI Codex" })).toBeTruthy());
    expect(screen.getByText("Logged in using ChatGPT")).toBeTruthy();
    expect(screen.getByText("Needs sign-in")).toBeTruthy();
    expect(screen.getByText("claude, then /login")).toBeTruthy();
    expect(screen.getByText("ollama signin")).toBeTruthy();
    expect(screen.getByText("1 local models")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByLabelText("GPT-6-Sol")); });
    expect(puts.at(-1)).toEqual({ url: "/v1/providers/cli/codex", body: { models: ["gpt-6-luna", "gpt-6-sol"] } });
    await act(async () => { fireEvent.click(screen.getByRole("switch", { name: "Use OpenAI Codex" })); });
    expect(puts.at(-1)).toEqual({ url: "/v1/providers/cli/codex", body: { enabled: false } });
    expect(document.body.textContent).not.toMatch(/secret|oauth_creds/i);
  });
});
