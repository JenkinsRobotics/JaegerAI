import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { BottomPanel } from "./BottomPanel";

const tabs = [
  { id: "problems", label: "Problems", badge: 3, content: "Three issues" },
  { id: "history", label: "History", content: "Rebuild history" },
  { id: "console", label: "Console", badge: "•", content: "Kernel ready" },
];

test("renders active content, badges, and header actions", () => {
  render(<BottomPanel tabs={tabs} activeID="problems" onSelect={() => {}} actions={<button>Clear</button>} />);
  expect(screen.getByRole("tabpanel").textContent).toContain("Three issues");
  expect(screen.getByText("3")).not.toBeNull();
  expect(screen.getByText("Clear")).not.toBeNull();
});

test("tab click selects and expands a collapsed panel", () => {
  const onSelect = vi.fn();
  const onCollapsedChange = vi.fn();
  render(<BottomPanel tabs={tabs} activeID="problems" onSelect={onSelect} collapsed onCollapsedChange={onCollapsedChange} />);
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  expect(onSelect).toHaveBeenCalledWith("history");
  expect(onCollapsedChange).toHaveBeenCalledWith(false);
});

test("keyboard tabs wrap and follow selection", () => {
  const onSelect = vi.fn();
  render(<BottomPanel tabs={tabs} activeID="console" onSelect={onSelect} />);
  fireEvent.keyDown(screen.getByRole("tab", { name: /Console/ }), { key: "ArrowRight" });
  expect(onSelect).toHaveBeenCalledWith("problems");
});

test("collapse control delegates state", () => {
  const onCollapsedChange = vi.fn();
  render(<BottomPanel tabs={tabs} activeID="problems" onSelect={() => {}} onCollapsedChange={onCollapsedChange} />);
  fireEvent.click(screen.getByLabelText("Collapse bottom panel"));
  expect(onCollapsedChange).toHaveBeenCalledWith(true);
});
