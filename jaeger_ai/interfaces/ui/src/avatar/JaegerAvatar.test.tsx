import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JaegerAvatar } from "./JaegerAvatar";

describe("Jaeger cutout avatar", () => {
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
