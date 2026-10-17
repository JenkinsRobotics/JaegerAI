import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileField } from "./FileField";

describe("FileField", () => {
  it("accepts browser-selected multiple files, lists them, and clears", () => {
    const onFilesChange = vi.fn();
    const first = new File(["step"], "bracket.step", { type: "model/step" });
    const second = new File(["drawing"], "layout.dxf", { type: "image/vnd.dxf" });
    render(<FileField label="Import sources" multiple accept=".step,.dxf" onFilesChange={onFilesChange} />);
    fireEvent.change(screen.getByLabelText("Import sources"), { target: { files: [first, second] } });
    expect(onFilesChange).toHaveBeenLastCalledWith([first, second]);
    expect(screen.getByText("bracket.step")).not.toBeNull();
    expect(screen.getByText("layout.dxf")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear files" }));
    expect(onFilesChange).toHaveBeenLastCalledWith([]);
  });

  it("accepts drops and bounds a single-file field", () => {
    const onFilesChange = vi.fn();
    const first = new File(["a"], "first.step");
    const second = new File(["b"], "second.step");
    const { container } = render(<FileField label="Part source" onFilesChange={onFilesChange} />);
    fireEvent.drop(container.querySelector(".aui-file-drop")!, { dataTransfer: { files: [first, second] } });
    expect(onFilesChange).toHaveBeenCalledWith([first]);
  });

  it("exposes help, error, and disabled behavior", () => {
    render(<FileField label="Reference" help="Files stay local." error="Source is missing." disabled />);
    expect((screen.getByLabelText("Reference") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Source is missing.");
    expect(screen.queryByText("Files stay local.")).toBeNull();
  });
});
