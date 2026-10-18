import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Tabs } from "./Tabs";

const tabs = [
  { id: "a", label: "Assets" },
  { id: "m", label: "Modeling" },
  { id: "n", label: "Animate" },
];

test("click selects; active tab is the only tab-stop", () => {
  const onSelect = vi.fn();
  render(<Tabs tabs={tabs} activeID="a" onSelect={onSelect} />);
  fireEvent.click(screen.getByText("Modeling"));
  expect(onSelect).toHaveBeenCalledWith("m");
  expect(screen.getByText("Assets").closest("button")?.tabIndex).toBe(0);
  expect(screen.getByText("Modeling").closest("button")?.tabIndex).toBe(-1);
});

test("arrows move+select with wrap, Home/End jump, focus follows", () => {
  const onSelect = vi.fn();
  render(<Tabs tabs={tabs} activeID="a" onSelect={onSelect} />);
  const first = screen.getByText("Assets").closest("button")!;
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowRight" });
  expect(onSelect).toHaveBeenLastCalledWith("m");
  expect(document.activeElement).toBe(screen.getByText("Modeling").closest("button"));
  fireEvent.keyDown(first, { key: "ArrowLeft" });
  expect(onSelect).toHaveBeenLastCalledWith("n"); // wraps
  fireEvent.keyDown(first, { key: "End" });
  expect(onSelect).toHaveBeenLastCalledWith("n");
  fireEvent.keyDown(first, { key: "Home" });
  expect(onSelect).toHaveBeenLastCalledWith("a");
});

test("disabled stages are explained and skipped by keyboard navigation", () => {
  const onSelect = vi.fn();
  render(
    <Tabs
      tabs={[
        { id: "a", label: "Design" },
        { id: "m", label: "Animate", disabled: true, title: "Not connected" },
        { id: "s", label: "Show" },
      ]}
      activeID="a"
      onSelect={onSelect}
    />,
  );
  const design = screen.getByText("Design").closest("button")!;
  expect(screen.getByText("Animate").closest("button")?.disabled).toBe(true);
  expect(screen.getByText("Animate").closest("button")?.getAttribute("title")).toBe("Not connected");
  design.focus();
  fireEvent.keyDown(design, { key: "ArrowRight" });
  expect(onSelect).toHaveBeenCalledWith("s");
  expect(document.activeElement).toBe(screen.getByText("Show").closest("button"));
});
