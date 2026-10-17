import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { CollapsibleSidebar, SidebarLabel, SidebarToggle } from "./CollapsibleSidebar";

afterEach(() => localStorage.clear());

test("toggle collapses to the rail, persists per sidebar id, and marks labels", () => {
  const { container } = render(
    <CollapsibleSidebar id="test-nav" ariaLabel="Test sidebar" footer={<SidebarLabel>Footer text</SidebarLabel>}>
      <button><SidebarLabel>Home</SidebarLabel></button>
    </CollapsibleSidebar>
  );
  const sidebar = container.querySelector("aside")!;
  expect(sidebar.className).not.toContain("aui-sidebar--collapsed");
  fireEvent.click(screen.getByLabelText("Collapse Test sidebar"));
  expect(sidebar.className).toContain("aui-sidebar--collapsed");
  expect(localStorage.getItem("aether-sidebar-test-nav")).toBe("collapsed");
  expect(screen.getByText("Home").className).toBe("aui-sidebar-label");
  fireEvent.click(screen.getByLabelText("Expand Test sidebar"));
  expect(localStorage.getItem("aether-sidebar-test-nav")).toBe("expanded");
});

test("remembers a collapsed preference on mount", () => {
  localStorage.setItem("aether-sidebar-remembered", "collapsed");
  const { container } = render(
    <CollapsibleSidebar id="remembered" ariaLabel="Remembered"><span /></CollapsibleSidebar>
  );
  expect(container.querySelector("aside")!.className).toContain("aui-sidebar--collapsed");
});

test("toggle=custom places the control inside app content only", () => {
  const { container } = render(
    <CollapsibleSidebar id="custom-toggle" ariaLabel="Custom" toggle="custom">
      <div className="row"><SidebarToggle /></div>
    </CollapsibleSidebar>
  );
  expect(container.querySelectorAll(".aui-sidebar-toggle")).toHaveLength(1);
  fireEvent.click(screen.getByLabelText("Collapse Custom"));
  expect(container.querySelector("aside")!.className).toContain("aui-sidebar--collapsed");
});
