import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JaegerAvatar } from "./JaegerAvatar";

const handle = { setState: vi.fn(), setPointer: vi.fn(), setPaused: vi.fn(), dispose: vi.fn() };
vi.mock("./jaegerStage", () => ({ mountJaegerStage: vi.fn(() => handle) }));

afterEach(() => { vi.unstubAllGlobals(); Object.values(handle).forEach(mock => mock.mockClear()); });

describe("live Jaeger avatar", () => {
  it("keeps the encoded avatar fallback when WebGL is unavailable", () => {
    const { container } = render(<JaegerAvatar state="idle" />);
    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("video")).toBeTruthy();
  });
  it("mounts the rig, sends state and pointer updates, and disposes it", async () => {
    vi.stubGlobal("WebGLRenderingContext", class {});
    const { container, rerender, unmount } = render(<JaegerAvatar state="idle" />);
    await waitFor(() => expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-live-status", "ready"));
    expect(container.querySelector("video")).toBeNull();
    rerender(<JaegerAvatar state="working" />);
    expect(handle.setState).toHaveBeenLastCalledWith("working");
    const canvas = container.querySelector("canvas")!;
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, toJSON: () => ({}) });
    const move = new Event("pointermove", { bubbles: true });
    Object.defineProperties(move, { clientX: { value: 75 }, clientY: { value: 25 } });
    fireEvent(canvas, move);
    expect(handle.setPointer).toHaveBeenLastCalledWith(0.5, -0.5);
    unmount();
    expect(handle.dispose).toHaveBeenCalledOnce();
  });
});
