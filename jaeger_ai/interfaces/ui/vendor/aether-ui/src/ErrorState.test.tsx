import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ErrorState } from "./ErrorState";

test("announces actionable errors and preserves diagnostics", () => {
  const retry = vi.fn();
  render(
    <ErrorState
      title="Rebuild failed"
      description="Fix the highlighted feature."
      detail="feature-12: missing profile"
      retryAction={<button onClick={retry}>Retry</button>}
    />,
  );
  expect(screen.getByRole("alert").textContent).toContain("missing profile");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(retry).toHaveBeenCalledTimes(1);
});
