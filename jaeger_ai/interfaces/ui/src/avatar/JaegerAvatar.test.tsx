import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EXPRESSIONS, JaegerAvatar, STATE_EXPRESSION } from "./JaegerAvatar";
import { AVATAR_STATES } from "./avatar";

afterEach(() => vi.useRealTimers());
describe("Jaeger expressions", () => {
  it.each(AVATAR_STATES)("maps %s to a non-mischievous activity expression", state => {
    const { container } = render(<JaegerAvatar state={state} />);
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-expression", EXPRESSIONS[STATE_EXPRESSION[state]]);
    expect(STATE_EXPRESSION[state]).toBeLessThan(7);
  });
  it("offers all approved expressions and returns to automatic after eight seconds", () => {
    vi.useFakeTimers();
    const { container, getByLabelText } = render(<JaegerAvatar />);
    const picker = getByLabelText("Avatar expression");
    expect(picker.querySelectorAll("option")).toHaveLength(13);
    fireEvent.change(picker, { target: { value: "11" } });
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-expression", "Peekaboo");
    expect(container.querySelector<HTMLElement>(".jg-jaeger-emote")!.style.backgroundPosition).toBe("100% 100%");
    act(() => vi.advanceTimersByTime(8000));
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-expression", "Idle");
  });
  it("clears a playful preview when runtime activity changes", () => {
    const { container, getByLabelText, rerender } = render(<JaegerAvatar />);
    fireEvent.change(getByLabelText("Avatar expression"), { target: { value: "9" } });
    rerender(<JaegerAvatar state="connecting" />);
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-expression", "Resting");
  });
  it("supports still mode and custom portraits", () => {
    const { container, rerender } = render(<JaegerAvatar still />);
    expect(container.querySelector(".jg-jaeger-avatar")).toHaveAttribute("data-motion", "still");
    rerender(<JaegerAvatar portraitOverride="/custom.png" />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/custom.png");
    expect(container.querySelector("select")).toBeNull();
  });
});
