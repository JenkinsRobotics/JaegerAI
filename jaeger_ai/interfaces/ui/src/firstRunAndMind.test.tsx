import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AwakeningWizard, MindAutonomyPanel } from "@jaeger/ui-features";

describe("First-Run Awakening Wizard & Live Mind Autonomy Panel", () => {
  it("completes the 3-step Awakening Wizard and posts to /v1/onboarding/complete", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, completed: true, identity: { owner_name: "Sam", ai_name: "Nova" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const onComplete = vi.fn();
    render(
      <AwakeningWizard
        baseUrl=""
        open
        models={[{ id: "mistral-large-4:cloud" }, { id: "gemma4:12b" }]}
        droidAvailable
        onComplete={onComplete}
        onDismiss={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("Owner name"), { target: { value: "Sam" } });
    fireEvent.change(screen.getByLabelText("Assistant name"), { target: { value: "Nova" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    fireEvent.change(screen.getByLabelText("Primary model"), { target: { value: "mistral-large-4:cloud" } });
    fireEvent.change(screen.getByLabelText("Fallback model"), { target: { value: "gemma4:12b" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    fireEvent.click(screen.getByRole("button", { name: "Finish Setup" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/v1/onboarding/complete",
      expect.objectContaining({ method: "POST" }),
    );
    fetchSpy.mockRestore();
  });

  it("renders While You Were Out, drives, Initiative Journal, and Minecraft controls", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/v1/cognition/briefing")) {
        return new Response(JSON.stringify({ ok: true, summary: "Welcome back, Sam. Explored cold ocean.", pending_approvals_count: 1 }));
      }
      if (url.includes("/v1/cognition/actions")) {
        return new Response(JSON.stringify({
          ok: true,
          status: {
            config: { enabled: true, max_actions_per_hour: 4 },
            drives: { curiosity: 0.72, goal_momentum: 0.65, social: 0.4, energy: 0.9 },
            actions_last_hour: 1,
          },
          actions: [{ action_id: "a1", kind: "minecraft_step", status: "done", summary: "Explored to (-138, 61, -30)" }],
        }));
      }
      if (url.includes("/v1/embodiment/status")) {
        return new Response(JSON.stringify({
          ok: true,
          minecraft: {
            state: { connected: true, biome: "cold_ocean", active_goal: "gather wood", position: { x: -138, y: 61, z: -30 } },
          },
        }));
      }
      return new Response(JSON.stringify({ ok: true }));
    });

    render(
      <MindAutonomyPanel
        baseUrl=""
        liveCogMode="observing"
        focusText="Exploring"
        tickCount={12}
        idleLifeStatus="ready"
        preemptionCount={0}
        estopActive={false}
        onOpenTasks={() => {}}
        onOpenGoals={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Welcome back, Sam/)).toBeTruthy();
      expect(screen.getByText(/Explored to \(-138, 61, -30\)/)).toBeTruthy();
      expect(screen.getByText(/cold_ocean/)).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: "Run Step Now" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeTruthy();
    fetchSpy.mockRestore();
  });
});
