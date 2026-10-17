import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Timeline } from "./Timeline";

const tracks = [
  { id: "pan", label: "pan.rotation", keyframes: [{ timeS: 0 }, { timeS: 1 }, { timeS: 2 }] },
  { id: "tilt", label: "tilt.rotation", keyframes: [{ timeS: 0 }, { timeS: 2 }] },
];

function stubLanes(container: HTMLElement) {
  const lanes = container.querySelector(".aui-timeline-lanes") as HTMLElement;
  lanes.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 200, height: 60, right: 200, bottom: 60 }) as DOMRect;
  return lanes;
}

test("renders a label and diamonds per track", () => {
  const { container } = render(
    <Timeline tracks={tracks} durationS={2} timeS={0} onSeek={() => {}} />
  );
  expect(screen.getByText("pan.rotation")).not.toBeNull();
  expect(screen.getByText("tilt.rotation")).not.toBeNull();
  expect(container.querySelectorAll(".aui-timeline-key").length).toBe(5);
});

test("pointer on the lanes seeks proportionally and clamps", () => {
  const onSeek = vi.fn();
  const { container } = render(
    <Timeline tracks={tracks} durationS={2} timeS={0} onSeek={onSeek} />
  );
  const lanes = stubLanes(container);
  // jsdom has no PointerEvent; a MouseEvent named pointerdown carries clientX.
  fireEvent(lanes, new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
  expect(onSeek).toHaveBeenLastCalledWith(1);
  fireEvent(lanes, new MouseEvent("pointerdown", { bubbles: true, clientX: 500 }));
  expect(onSeek).toHaveBeenLastCalledWith(2); // clamped to duration
});

test("keyframe click selects without seeking", () => {
  const onSeek = vi.fn();
  const onSelectKeyframe = vi.fn();
  render(
    <Timeline
      tracks={tracks}
      durationS={2}
      timeS={0}
      onSeek={onSeek}
      onSelectKeyframe={onSelectKeyframe}
    />
  );
  fireEvent.pointerDown(
    screen.getByLabelText("tilt.rotation keyframe at 2.00s")
  );
  expect(onSelectKeyframe).toHaveBeenCalledWith("tilt", 1);
  expect(onSeek).not.toHaveBeenCalled();
});

test("transport toggles play and empty state renders", () => {
  const onTogglePlay = vi.fn();
  const { rerender } = render(
    <Timeline
      tracks={tracks}
      durationS={2}
      timeS={0.5}
      onSeek={() => {}}
      playing={false}
      onTogglePlay={onTogglePlay}
    />
  );
  fireEvent.click(screen.getByLabelText("Play"));
  expect(onTogglePlay).toHaveBeenCalledTimes(1);
  rerender(
    <Timeline tracks={[]} durationS={2} timeS={0} onSeek={() => {}} emptyState="no clip" />
  );
  expect(screen.getByText("no clip")).not.toBeNull();
});
