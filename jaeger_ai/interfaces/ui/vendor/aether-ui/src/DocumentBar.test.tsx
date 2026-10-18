import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { DocumentBar } from "./DocumentBar";

test("provides shared window-centered chrome and a native drag region", () => {
  const { container } = render(
    <DocumentBar
      className="product-header"
      leading={<button type="button">Home</button>}
      center={<span>Stages</span>}
      trailing={<button type="button">Help</button>}
    />,
  );

  const bar = container.querySelector("header");
  expect(bar?.classList.contains("product-header")).toBe(true);
  expect(bar?.getAttribute("data-aether-window-drag-region")).toBe("true");
  expect(screen.getByText("Stages").parentElement?.classList.contains("aui-document-bar-center")).toBe(true);
});
