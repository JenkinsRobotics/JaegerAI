import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Ribbon, RibbonGroup, RibbonTool } from "./Ribbon";

function renderRibbon(onClick = vi.fn()) {
  render(
    <Ribbon>
      <RibbonGroup label="Mate">
        <RibbonTool icon="▣" label="Fastened" onClick={onClick} />
        <RibbonTool icon="↻" label="Revolute" onClick={onClick} />
      </RibbonGroup>
      <RibbonGroup label="Edit">
        <RibbonTool icon="✕" label="Remove" disabled onClick={onClick} />
        <RibbonTool icon="⧉" label="Copy" onClick={onClick} />
      </RibbonGroup>
    </Ribbon>
  );
  return onClick;
}

test("arrows move focus across groups, skip disabled, wrap", () => {
  renderRibbon();
  const first = screen.getByText("Fastened");
  first.focus();
  fireEvent.keyDown(first.closest(".aui-ribbon")!, { key: "ArrowRight" });
  expect(document.activeElement).toBe(screen.getByText("Revolute"));
  // Next right skips disabled Remove, crossing the group boundary.
  fireEvent.keyDown(first.closest(".aui-ribbon")!, { key: "ArrowRight" });
  expect(document.activeElement).toBe(screen.getByText("Copy"));
  // Right from the last wraps to the first.
  fireEvent.keyDown(first.closest(".aui-ribbon")!, { key: "ArrowRight" });
  expect(document.activeElement).toBe(first);
});

test("disabled tools do not fire clicks", () => {
  const onClick = renderRibbon();
  fireEvent.click(screen.getByText("Remove"));
  expect(onClick).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Copy"));
  expect(onClick).toHaveBeenCalledTimes(1);
});
