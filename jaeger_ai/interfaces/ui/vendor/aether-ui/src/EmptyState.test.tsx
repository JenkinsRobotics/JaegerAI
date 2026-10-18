import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { EmptyState } from "./EmptyState";

test("renders compact empty guidance and working actions", () => {
  const onCreate = vi.fn();
  render(
    <EmptyState
      compact
      title="No components"
      description="Insert a component to begin."
      icon="◇"
      primaryAction={<button onClick={onCreate}>Insert</button>}
    />,
  );
  expect(screen.getByLabelText("No components").className).toContain("aui-state--compact");
  fireEvent.click(screen.getByRole("button", { name: "Insert" }));
  expect(onCreate).toHaveBeenCalledTimes(1);
});
