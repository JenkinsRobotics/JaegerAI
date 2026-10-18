import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { PanelPlacementMenu } from "./PanelPlacementMenu";

test("marks the active placement and emits Dock, Float, or Hide intent", () => {
  const onChange = vi.fn();
  const { rerender } = render(
    <PanelPlacementMenu
      label="Inspector"
      placement="docked"
      onChange={onChange}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Inspector placement" }));
  expect(
    screen.getByRole("menuitemradio", { name: /Dock/ }).getAttribute("aria-checked"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("menuitemradio", { name: /Float/ }));
  expect(onChange).toHaveBeenCalledWith("floating");

  rerender(
    <PanelPlacementMenu
      label="Inspector"
      placement="floating"
      onChange={onChange}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Inspector placement" }));
  expect(
    screen.getByRole("menuitemradio", { name: /Float/ }).getAttribute("aria-checked"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("menuitemradio", { name: /Hide/ }));
  expect(onChange).toHaveBeenLastCalledWith("hidden");
});
