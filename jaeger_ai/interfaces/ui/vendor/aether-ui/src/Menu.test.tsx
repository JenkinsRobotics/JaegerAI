import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Menu, MenuButton, type MenuItem } from "./Menu";

const items: MenuItem[] = [
  { id: "open", label: "Open", shortcut: "⌘O" },
  { id: "locked", label: "Delete", disabled: true, disabledReason: "Locked" },
  { id: "edges", label: "Show edges", kind: "checkbox", checked: true },
  { id: "solid", label: "Solid", kind: "radio", checked: true },
  { id: "purge", label: "Purge", danger: true },
  {
    id: "export",
    label: "Export",
    separatorBefore: true,
    children: [
      { id: "step", label: "STEP" },
      { id: "mesh", label: "Mesh", danger: true },
    ],
  },
];

function renderMenu(onSelect = vi.fn()) {
  render(
    <MenuButton label="Actions" items={items} onSelect={onSelect}>
      •••
    </MenuButton>,
  );
  fireEvent.click(screen.getByLabelText("Actions"));
  return onSelect;
}

test("selects a command and closes", () => {
  const onSelect = renderMenu();
  fireEvent.click(screen.getByRole("menuitem", { name: /Open/ }));
  expect(onSelect).toHaveBeenCalledWith("open");
  expect(screen.queryByRole("menu")).toBeNull();
});

test("disabled items expose their reason and cannot execute", () => {
  const onSelect = renderMenu();
  const item = screen.getByRole("menuitem", { name: "Delete" });
  expect(item.getAttribute("title")).toBe("Locked");
  fireEvent.click(item);
  expect(onSelect).not.toHaveBeenCalled();
});

test("checkbox state and separators use menu semantics", () => {
  renderMenu();
  expect(
    screen
      .getByRole("menuitemcheckbox", { name: "Show edges" })
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(
    screen.getByRole("menuitemradio", { name: "Solid" }).getAttribute("aria-checked"),
  ).toBe("true");
  expect(screen.getByRole("menuitem", { name: "Purge" }).className).toContain(
    "aui-menu-item--danger",
  );
  expect(screen.getByRole("separator")).not.toBeNull();
});

test("keyboard navigation skips disabled items and Escape returns focus", () => {
  renderMenu();
  const opener = screen.getByRole("button", { name: "Actions" });
  const open = screen.getByRole("menuitem", { name: /Open/ });
  expect(document.activeElement).toBe(open);
  fireEvent.keyDown(open, { key: "ArrowDown" });
  expect(document.activeElement).toBe(
    screen.getByRole("menuitemcheckbox", { name: "Show edges" }),
  );
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(opener);
});

test("submenus open from keyboard and execute nested commands", async () => {
  const onSelect = renderMenu();
  const exportItem = screen.getByRole("menuitem", { name: "Export" });
  exportItem.focus();
  fireEvent.keyDown(exportItem, { key: "ArrowRight" });
  await Promise.resolve();
  expect(screen.getByRole("menuitem", { name: "STEP" })).not.toBeNull();
  fireEvent.click(screen.getByRole("menuitem", { name: "STEP" }));
  expect(onSelect).toHaveBeenCalledWith("step");
});

test("outside pointer press closes without executing", () => {
  const onSelect = renderMenu();
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("menu")).toBeNull();
  expect(onSelect).not.toHaveBeenCalled();
});

test("an all-disabled menu can still close with Escape", () => {
  render(
    <MenuButton
      label="Unavailable actions"
      items={[{ id: "locked", label: "Locked", disabled: true }]}
      onSelect={vi.fn()}
    >
      •••
    </MenuButton>,
  );
  const opener = screen.getByRole("button", { name: "Unavailable actions" });
  fireEvent.click(opener);
  expect(screen.getByRole("menu")).not.toBeNull();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(opener);
});

test("supports a pointer-position anchor for context menus", () => {
  render(
    <Menu
      open
      anchor={{ x: 24, y: 36 }}
      items={[{ id: "inspect", label: "Inspect" }]}
      onSelect={vi.fn()}
      onClose={vi.fn()}
      ariaLabel="Context actions"
    />,
  );
  const menu = screen.getByRole("menu", { name: "Context actions" });
  expect(menu.style.left).toBe("24px");
  expect(menu.style.top).toBe("36px");
});
