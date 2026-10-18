import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { PropertyGrid } from "./PropertyGrid";

const resetPositionX = vi.fn();
const sections = [
  {
    id: "transform",
    label: "Transform",
    properties: [
      { id: "x", label: "Position X", editor: <input aria-label="Position X value" />, modified: true, onReset: resetPositionX },
      { id: "y", label: "Position Y", editor: <input aria-label="Position Y value" />, mixed: true },
    ],
  },
  {
    id: "appearance",
    label: "Appearance",
    properties: [
      { id: "material", label: "Material", editor: "Aluminum", help: "Inherited from body", readOnly: true },
      { id: "opacity", label: "Opacity", editor: "120%", error: "Must be 0–100%" },
    ],
  },
];

test("renders schema sections, mixed/read-only/help/error states", () => {
  render(<PropertyGrid ariaLabel="Inspector" sections={sections} />);
  expect(screen.getByText("Mixed")).not.toBeNull();
  expect(screen.getByText("Inherited from body")).not.toBeNull();
  expect(screen.getByText("Must be 0–100%")).not.toBeNull();
  expect(screen.getByText("Aluminum").getAttribute("aria-readonly")).toBe("true");
});

test("uncontrolled section headings collapse and expand", () => {
  render(<PropertyGrid ariaLabel="Inspector" sections={sections} />);
  fireEvent.click(screen.getByText("Transform"));
  expect(screen.queryByLabelText("Position X value")).toBeNull();
  fireEvent.click(screen.getByText("Transform"));
  expect(screen.getByLabelText("Position X value")).not.toBeNull();
});

test("controlled collapse reports requested expansion", () => {
  const onToggleSection = vi.fn();
  render(
    <PropertyGrid
      ariaLabel="Inspector"
      sections={sections}
      collapsedIDs={new Set(["transform"])}
      onToggleSection={onToggleSection}
    />
  );
  fireEvent.click(screen.getByText("Transform"));
  expect(onToggleSection).toHaveBeenCalledWith("transform", true);
});

test("filter and modified-only project the schema", () => {
  const { rerender } = render(
    <PropertyGrid ariaLabel="Inspector" sections={sections} filter="material" />
  );
  expect(screen.getByText("Material")).not.toBeNull();
  expect(screen.queryByText("Position X")).toBeNull();
  rerender(<PropertyGrid ariaLabel="Inspector" sections={sections} modifiedOnly />);
  expect(screen.getByText("Position X")).not.toBeNull();
  expect(screen.queryByText("Position Y")).toBeNull();
});

test("reset is delegated and empty projections use the slot", () => {
  const { rerender } = render(<PropertyGrid ariaLabel="Inspector" sections={sections} />);
  fireEvent.click(screen.getByText("Reset"));
  expect(resetPositionX).toHaveBeenCalled();
  rerender(<PropertyGrid ariaLabel="Inspector" sections={sections} filter="missing" emptyState="No matching properties" />);
  expect(screen.getByText("No matching properties")).not.toBeNull();
});
