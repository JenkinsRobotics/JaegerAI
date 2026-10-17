import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Button } from "./Button";
import { RibbonTool } from "./Ribbon";

test("button variants map to classes and clicks fire", () => {
  const onClick = vi.fn();
  render(
    <Button primary onClick={onClick}>
      Go
    </Button>
  );
  const button = screen.getByText("Go");
  expect(button.className).toContain("aui-button--primary");
  fireEvent.click(button);
  expect(onClick).toHaveBeenCalled();
});

test("disabled ribbon tool does not fire", () => {
  const onClick = vi.fn();
  render(<RibbonTool icon="✕" label="Remove" disabled onClick={onClick} />);
  fireEvent.click(screen.getByText("Remove"));
  expect(onClick).not.toHaveBeenCalled();
});
