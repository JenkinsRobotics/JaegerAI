import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AppearanceToggle, StudioModeButton, WorkspaceWindowMenu } from "./StudioChrome";

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("aether-light-theme");
});

test("studio mode button cycles on click and resets from its menu", () => {
  const onChange = vi.fn();
  render(<StudioModeButton preset="docked" onChange={onChange} />);
  const button = screen.getByLabelText("Studio mode: Docked");
  expect(button.className).toContain("aui-studio-mode--docked");
  fireEvent.click(button);
  expect(onChange).toHaveBeenLastCalledWith("canvas");
  fireEvent.contextMenu(button, { clientX: 40, clientY: 40 });
  fireEvent.click(screen.getByText("Reset Studio Layout"));
  expect(onChange).toHaveBeenLastCalledWith("floating");
});

test("appearance toggle cycles System → Light → Dark and applies the light class", () => {
  render(<AppearanceToggle />);
  fireEvent.click(screen.getByLabelText("Appearance System"));
  expect(screen.getByLabelText("Appearance Light")).toBeTruthy();
  expect(document.documentElement.classList.contains("aether-light-theme")).toBe(true);
  expect(localStorage.getItem("aether-appearance")).toBe("light");
  fireEvent.click(screen.getByLabelText("Appearance Light"));
  expect(screen.getByLabelText("Appearance Dark")).toBeTruthy();
  expect(document.documentElement.classList.contains("aether-light-theme")).toBe(false);
});

test("workspace windows menu keeps native entries, disabling browser-managed ones", () => {
  render(<WorkspaceWindowMenu />);
  fireEvent.click(screen.getByLabelText("Workspace windows and tabs"));
  expect(screen.getByText("New Workspace Tab")).toBeTruthy();
  const detach = screen.getByText("Detach Current Tab").closest('[role="menuitem"],[role="menuitemradio"],button');
  expect(detach?.getAttribute("aria-disabled") ?? String((detach as HTMLButtonElement)?.disabled)).toMatch(/true/);
});

test("installed-theme selection applies and clears the scoped class", async () => {
  const { setAetherTheme, activeAetherTheme } = await import("./StudioChrome");
  setAetherTheme("community-neon");
  expect(activeAetherTheme()).toBe("community-neon");
  expect(document.documentElement.classList.contains("aether-theme-community-neon")).toBe(true);
  setAetherTheme("aether-default");
  expect(document.documentElement.classList.contains("aether-theme-community-neon")).toBe(false);
});

test("installAetherTheme injects scoped CSS at runtime and replaces on reinstall", async () => {
  const { installAetherTheme } = await import("./StudioChrome");
  const manifest = { id: "neon", name: "Neon", modes: { dark: { "color-accent": "#f0f" }, light: { "color-accent": "#f0f" } } };
  installAetherTheme(manifest);
  const style = document.head.querySelector('style[data-aether-theme="neon"]');
  expect(style?.textContent).toContain(".aether-theme-neon {");
  expect(style?.textContent).toContain("--aether-color-accent: #f0f;");
  installAetherTheme({ ...manifest, modes: { dark: { "color-accent": "#0ff" }, light: {} } });
  expect(document.head.querySelectorAll('style[data-aether-theme="neon"]')).toHaveLength(1);
  expect(document.head.querySelector('style[data-aether-theme="neon"]')?.textContent).toContain("#0ff");
});
