import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { AetherIcon } from "./AetherIcon";

test("renders shared chrome icons as presentation-only SVG", () => {
  const { container, rerender } = render(<AetherIcon name="home" />);
  expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  expect(container.querySelectorAll("path").length).toBeGreaterThan(0);

  rerender(<AetherIcon name="settings" className="suite-icon" />);
  expect(container.querySelector("svg")?.classList.contains("suite-icon")).toBe(true);
  expect(container.querySelector("circle")).not.toBeNull();
});


test("shared icon sources are scalable geometry without embedded raster or font glyphs", () => {
  const sources = import.meta.glob("../../assets/icons/*.svg", { query: "?raw", import: "default", eager: true });
  expect(Object.keys(sources).length).toBeGreaterThan(30);
  for (const [path, markup] of Object.entries(sources)) {
    expect(markup).toContain('viewBox="0 0 24 24"');
    // Monochrome UI icons follow the text colour; file-type tiles are
    // deliberately multi-colour (they identify a document kind).
    if (!/\/file-[a-z]+\.svg$/.test(path)) expect(markup).toContain('stroke="currentColor"');
    expect(markup).not.toMatch(/<(?:text|image|script|foreignObject)\b/i);
  }
});

test("an icon pack overrides artwork per name and falls back for the rest", async () => {
  const { AetherIcon, registerIconPack } = await import("./AetherIcon");
  const { render } = await import("@testing-library/react");
  registerIconPack({ home: '<svg><circle cx="12" cy="12" r="9"/></svg>' });
  const packed = render(<AetherIcon name="home" />).container.innerHTML;
  const fallback = render(<AetherIcon name="folder" />).container.innerHTML;
  registerIconPack(null);
  expect(packed).toContain("circle");
  expect(fallback).toContain("path");
});

test("registering a pack hot-swaps icons that are already mounted", async () => {
  const { AetherIcon, registerIconPack } = await import("./AetherIcon");
  const { render, act } = await import("@testing-library/react");
  const { container } = render(<AetherIcon name="home" />);
  const before = container.innerHTML;
  act(() => registerIconPack({ home: '<svg><ellipse rx="4" ry="2"/></svg>' }));
  expect(container.innerHTML).toContain("ellipse");
  act(() => registerIconPack(null));
  expect(container.innerHTML).toBe(before);
});
