import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import { getJson } from "../unified/webui";
import { SystemStatusButton } from "./SystemStatusButton";

vi.mock("../unified/webui", () => ({ getJson: vi.fn() }));
const source = {} as JaegerSource;
afterEach(() => vi.clearAllMocks());

it("opens status on demand and closes it before navigating to Machine settings", async () => {
  vi.mocked(getJson).mockResolvedValue({ gateway: { ok: true, latency_ms: 4 }, tailscale: { available: true, online: true } });
  const navigate = vi.fn();
  render(<SystemStatusButton source={source} ready host="Local Studio" onNavigate={navigate} />);
  const button = screen.getByRole("button", { name: "System status: Connected" });
  expect(button.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("Local Studio")).toBeNull();
  expect(getJson).not.toHaveBeenCalled();
  const dialog = document.querySelector("dialog")!;
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; dialog.dispatchEvent(new Event("close")); };
  fireEvent.click(button);
  const popup = screen.getByRole("dialog", { name: "System status" });
  expect(within(popup).getByText("Local Studio")).toBeTruthy();
  expect(await within(popup).findByText("Healthy · 4 ms")).toBeTruthy();
  expect(within(popup).getByText("Online")).toBeTruthy();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(within(popup).getByRole("button", { name: "Machine settings" }));
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/settings/machine");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(button.getAttribute("aria-expanded")).toBe("false");
});

it("labels an error even with a previously ready connection and the sidebar collapsed", () => {
  render(<SystemStatusButton source={source} ready error="offline" compact onNavigate={vi.fn()} />);
  expect(screen.getByRole("button", { name: "System status: Connection error" }).querySelector("[data-state=error]")).toBeTruthy();
});
