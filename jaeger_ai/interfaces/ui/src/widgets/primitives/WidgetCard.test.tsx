import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { WidgetCard } from "./WidgetCard";

const host = document.createElement("div");
document.body.append(host);
const root = createRoot(host);
afterEach(async () => { await act(async () => root.render(null)); });

it("renders value, status, trace and an actionable control", async () => {
  const action = vi.fn();
  await act(async () => root.render(<WidgetCard title="Queue" value={12} status="Healthy" trace={<svg aria-label="Queue history" />} actions={<button onClick={action}>Open</button>} />));
  expect(host.querySelector('section[aria-label="Queue"]')?.getAttribute("data-state")).toBe("ready");
  expect(host.textContent).toContain("12");
  expect(host.textContent).toContain("Healthy");
  expect(host.querySelector('[aria-label="Queue trace"] svg')).not.toBeNull();
  await act(async () => host.querySelector("button")!.click());
  expect(action).toHaveBeenCalledOnce();
});

it.each(["loading", "empty", "error"] as const)("shows %s state without stale data or actions", async state => {
  await act(async () => root.render(<WidgetCard title="Queue" state={state} value={12} actions={<button>Open</button>} />));
  expect(host.querySelector(".jg-widget-card__value")).toBeNull();
  expect(host.querySelector("button")).toBeNull();
  expect(host.querySelector(".jg-widget-card__message")?.textContent).toBeTruthy();
  expect(host.querySelector("section")?.getAttribute("aria-busy")).toBe(String(state === "loading"));
  expect(host.querySelector(".jg-widget-card__message")?.getAttribute("role")).toBe(state === "error" ? "alert" : "status");
});

it("uses preset tokens for card, value, trace and controls", async () => {
  await act(async () => root.render(<WidgetCard title="Queue" value={12} trace={<span>trend</span>} actions={<button>Open</button>} />));
  const css = readFileSync("src/widgets/primitives/widget-card.css", "utf8");
  for (const token of ["--jg-card-bg", "--jg-card-border", "--jg-card-radius", "--jg-stat-size", "--jg-chart-color", "--jg-ctl-bg"]) {
    expect(css).toContain(`var(${token})`);
  }
});
