import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { StatusBar, StatusDot } from "./StatusBar";

test("plain children render without region wrappers", () => {
  const { container } = render(<StatusBar><StatusDot kind="ok" />Engine ready</StatusBar>);
  expect(screen.getByLabelText("Workspace status").textContent).toContain("Engine ready");
  expect(container.querySelector(".aui-status-bar__center")).toBeNull();
});

test("leading, center, and trailing regions render in order", () => {
  const { container } = render(
    <StatusBar leading={<span>Aether CAD</span>} center={<span>Imported 3 bodies</span>} trailing={<span>26 parts</span>} />
  );
  const regions = Array.from(container.querySelectorAll(".aui-status-bar > *")).map((el) => el.textContent);
  expect(regions).toEqual(["Aether CAD", "Imported 3 bodies", "26 parts"]);
  expect(container.querySelector(".aui-status-bar__leading")?.textContent).toBe("Aether CAD");
  expect(container.querySelector(".aui-status-bar__center")?.textContent).toBe("Imported 3 bodies");
  expect(container.querySelector(".aui-status-bar__trailing")?.textContent).toBe("26 parts");
});
