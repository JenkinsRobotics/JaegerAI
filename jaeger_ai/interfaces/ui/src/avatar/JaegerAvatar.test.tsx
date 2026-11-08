import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ACTIVITY_POSE, APPROVED_POSES, JaegerAvatar } from "./JaegerAvatar";
import { AVATAR_STATES } from "./avatar";

afterEach(() => vi.useRealTimers());

describe("Jaeger cutout avatar", () => {
  it("includes only the ten approved poses, never rejected 4 or 9", () => {
    expect(APPROVED_POSES.map(pose => pose.number)).toEqual([1, 2, 3, 5, 6, 7, 8, 10, 11, 12]);
    const { getByLabelText } = render(<JaegerAvatar />);
    expect(getByLabelText("Avatar pose").querySelectorAll("option")).toHaveLength(11);
  });

  it.each(AVATAR_STATES)("uses approved automatic activity for %s", state => {
    const { container } = render(<JaegerAvatar state={state} />);
    const pose = APPROVED_POSES[ACTIVITY_POSE[state]];
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-pose", String(pose?.number ?? "signature"));
    expect([4, 8, 9, 10, 11, 12]).not.toContain(pose?.number);
  });

  it("previews the chosen pose then restores the unchanged signature icon", () => {
    vi.useFakeTimers();
    const { container, getByLabelText } = render(<JaegerAvatar />);
    fireEvent.change(getByLabelText("Avatar pose"), { target: { value: "9" } });
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-pose", "12");
    expect(container.querySelector<HTMLElement>(".jg-jaeger-pose")!.style.backgroundPosition).toBe("100% 100%");
    act(() => vi.advanceTimersByTime(8000));
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-pose", "signature");
    expect(container.querySelector("img")!.src).toContain("jaeger-signature-grin.png");
  });

  it("clears a playful preview when activity changes and supports still mode", () => {
    const { container, getByLabelText, rerender } = render(<JaegerAvatar />);
    fireEvent.change(getByLabelText("Avatar pose"), { target: { value: "7" } });
    rerender(<JaegerAvatar state="connecting" still />);
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-pose", "7");
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-motion", "still");
  });
  it("uses the canonical artwork for the body, smile, and both arm layers", () => {
    const { container } = render(<JaegerAvatar state="idle" />);
    const rig = container.querySelector(".jg-jaeger-avatar")!;
    const images = Array.from(container.querySelectorAll<HTMLImageElement>(".jg-jaeger-cutout img"));
    expect(rig).toHaveAttribute("data-motion", "rigged");
    expect(images).toHaveLength(4);
    expect(new Set(images.map(image => image.src)).size).toBe(1);
    expect(images[0].src).toContain("jaeger-signature-grin.png");
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("tracks the pointer with the smile without replacing the artwork", () => {
    const { container } = render(<JaegerAvatar state="working" />);
    const rig = container.querySelector<HTMLElement>(".jg-jaeger-avatar")!;
    Object.defineProperty(rig, "getBoundingClientRect", { value: () => ({ left: 0, top: 0, width: 100, height: 100 }) });
    const move = new Event("pointermove", { bubbles: true });
    Object.defineProperties(move, { clientX: { value: 75 }, clientY: { value: 25 } });
    fireEvent(rig, move);
    expect(rig.style.getPropertyValue("--jg-look-x")).toBe("0.60px");
    expect(rig.style.getPropertyValue("--jg-look-y")).toBe("-0.35px");
    fireEvent.pointerLeave(rig);
    expect(rig.style.getPropertyValue("--jg-look-x")).toBe("0px");
  });

  it("keeps custom portraits on the existing fallback path", () => {
    const { container } = render(<JaegerAvatar portraitOverride="/custom.png" />);
    expect(container.querySelector(".jg-jaeger-cutout")).toBeNull();
    expect(container.querySelector("img")).toHaveAttribute("src", "/custom.png");
  });
});
