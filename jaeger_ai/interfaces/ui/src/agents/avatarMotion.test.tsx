import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentStatus } from "../api/types";
import { AgentAvatar, SupervisorArt } from "./AgentAvatar";
import { ONE_SHOT_MS, steadyState, transitionState, turnAvatarState, useAvatarState, type AvatarState } from "./avatarMotion";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.useRealTimers());

describe("avatar states", () => {
  it("maps gateway status to a steady state", () => {
    expect(steadyState("working")).toBe("working");
    expect(steadyState("waiting_approval")).toBe("waiting");
    expect(steadyState("blocked")).toBe("blocked");
    expect(steadyState("idle")).toBe("idle");
    expect(steadyState("error")).toBe("idle");
    expect(steadyState(undefined)).toBe("idle");
  });

  it("plays finished, failed and notifying on the right transitions", () => {
    expect(transitionState({ status: "working", unread: false }, { status: "idle", unread: false })).toBe("finished");
    expect(transitionState({ status: "working", unread: false }, { status: "error", unread: false })).toBe("failed");
    expect(transitionState({ status: "idle", unread: false }, { status: "idle", unread: true })).toBe("notifying");
    expect(transitionState({ status: "working", unread: false }, { status: "working", unread: true })).toBeUndefined();
    expect(transitionState({ status: "idle", unread: true }, { status: "idle", unread: true })).toBeUndefined();
  });

  it("layers a one-shot over the steady state, then settles", async () => {
    vi.useFakeTimers();
    let seen: AvatarState[] = [];
    function Probe({ status, unread }: { status?: AgentStatus; unread: boolean }) { seen.push(useAvatarState(status, unread)); return null; }
    const el = document.createElement("div");
    const root = createRoot(el);
    await act(async () => root.render(<Probe status="working" unread={false} />));
    expect(seen.at(-1)).toBe("working");
    await act(async () => root.render(<Probe status="idle" unread={false} />));
    expect(seen.at(-1)).toBe("finished");
    await act(async () => { vi.advanceTimersByTime(ONE_SHOT_MS.finished! + 1); });
    expect(seen.at(-1)).toBe("idle");
    seen = [];
    await act(async () => root.render(<Probe status="error" unread={false} />));
    expect(seen.at(-1)).toBe("failed");
    await act(async () => { vi.advanceTimersByTime(ONE_SHOT_MS.failed! + 1); });
    expect(seen.at(-1)).toBe("idle");
    await act(async () => root.unmount());
  });

  it("derives the in-chat avatar state from the turn", () => {
    expect(turnAvatarState({ parts: [] })).toBe("thinking");
    expect(turnAvatarState({ parts: [{ kind: "thinking", text: "" } as never] })).toBe("thinking");
    expect(turnAvatarState({ parts: [{ kind: "markdownContent", text: "Hi" } as never] })).toBe("streaming");
    expect(turnAvatarState({ parts: [{ kind: "toolInvocation", toolName: "read", state: "running" } as never] })).toBe("working");
    expect(turnAvatarState({ parts: [{ kind: "toolInvocation", toolName: "shell", state: "waitingForConfirmation" } as never] })).toBe("waiting");
  });

  it("renders the state and its activity mark", () => {
    const thinking = renderToStaticMarkup(<AgentAvatar id="native:jaeger" name="Jaeger" state="thinking" />);
    expect(thinking).toContain('data-state="thinking"');
    expect(thinking).toContain("jg-avatar__fx--dots");
    expect(renderToStaticMarkup(<AgentAvatar id="a" name="A" state="waiting" />)).toContain("jg-avatar__fx--orbit");
    expect(renderToStaticMarkup(<AgentAvatar id="a" name="A" state="spawning" />)).toContain("jg-avatar__fx--gather");
    const idle = renderToStaticMarkup(<AgentAvatar id="a" name="A" state="idle" />);
    expect(idle).not.toContain("data-state");
    expect(idle).not.toContain("jg-avatar__fx");
    expect(renderToStaticMarkup(<SupervisorArt id="a" name="A" state="finished" />)).toContain('data-state="finished"');
  });
});
