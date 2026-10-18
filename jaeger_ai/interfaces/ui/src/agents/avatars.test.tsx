import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ChatPart } from "../chat/host";
import { AgentAvatar } from "./AgentAvatar";
import { AVATAR_SHAPES, avatarShape } from "./avatarColor";
import { HandoffMarker } from "./HandoffMarker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("avatar silhouettes", () => {
  it("picks a stable shape per id, spread over the set, supervisor round", () => {
    expect(avatarShape("agent:swe")).toBe(avatarShape("agent:swe"));
    expect(avatarShape("native:jaeger")).toBe("circle");
    const seen = new Set(Array.from({ length: 40 }, (_, i) => avatarShape(`agent:a${i}`)));
    expect(seen.size).toBeGreaterThanOrEqual(4);
    for (const s of seen) expect(AVATAR_SHAPES).toContain(s);
  });

  it("draws the silhouette with the two-eye face, or a round image", () => {
    const html = renderToStaticMarkup(<AgentAvatar id="agent:swe" name="SWE" size={18} />);
    expect(html).toContain('class="jg-avatar__shape"');
    expect(html).toContain(`data-shape="${avatarShape("agent:swe")}"`);
    expect(html.match(/<i><\/i>/g)).toHaveLength(2);
    expect(html).toContain("width:18px");
    const img = renderToStaticMarkup(<AgentAvatar id="a" name="A" src="/a.png" />);
    expect(img).toContain("jg-avatar--image");
    expect(img).not.toContain("jg-avatar__shape");
  });
});

describe("handoff with 3+ recipients", () => {
  const part: Extract<ChatPart, { kind: "handoff" }> = {
    kind: "handoff", handoffId: "h1", agentId: "a", agentName: "A", count: 1, direction: "to",
    agents: [{ id: "a", name: "A" }, { id: "b", name: "B" }, { id: "c", name: "C" }, { id: "d", name: "D" }],
  };

  it("stacks three 18px avatars and a count chip; two recipients keep the sentence", () => {
    const html = renderToStaticMarkup(<HandoffMarker part={part} />);
    expect(html.match(/class="jg-handoff__stack"/g)).toHaveLength(1);
    expect(html.match(/width:18px/g)).toHaveLength(3);
    expect(html).toContain('aria-label="4 agents in this exchange"');
    expect(html).toContain(">4</button>");
    const two = renderToStaticMarkup(<HandoffMarker part={{ ...part, agents: part.agents!.slice(0, 2) }} />);
    expect(two).not.toContain("jg-handoff__stack");
    expect(two).toContain('aria-label="Messaged A and B"');
  });

  it("opens and closes the 'Agents in this exchange' menu", async () => {
    const el = document.createElement("div");
    document.body.append(el);
    const root = createRoot(el);
    const onOpen = vi.fn();
    await act(async () => { root.render(<HandoffMarker part={part} onOpen={onOpen} />); });
    const chip = el.querySelector<HTMLButtonElement>(".jg-handoff__count")!;
    await act(async () => { chip.click(); });
    const menu = el.querySelector('[role="dialog"][aria-label="Agents in this exchange"]')!;
    expect(menu.querySelectorAll("li")).toHaveLength(4);
    expect(onOpen).not.toHaveBeenCalled();
    await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(el.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => { el.querySelector<HTMLButtonElement>(".jg-handoff__open")!.click(); });
    expect(onOpen).toHaveBeenCalledWith("h1");
    act(() => root.unmount());
    el.remove();
  });
});
