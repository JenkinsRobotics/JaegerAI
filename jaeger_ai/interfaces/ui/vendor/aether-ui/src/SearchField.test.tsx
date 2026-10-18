import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SearchField } from "./SearchField";

afterEach(() => vi.useRealTimers());

describe("SearchField", () => {
  it("emits immediate query state and a delayed search intent", () => {
    vi.useFakeTimers();
    const onQueryChange = vi.fn();
    const onSearch = vi.fn();
    render(<SearchField ariaLabel="Find features" onQueryChange={onQueryChange} onSearch={onSearch} delayMilliseconds={200} />);
    fireEvent.change(screen.getByLabelText("Find features"), { target: { value: "fillet" } });
    expect(onQueryChange).toHaveBeenCalledWith("fillet");
    expect(onSearch).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(199));
    expect(onSearch).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onSearch).toHaveBeenCalledWith("fillet");
  });

  it("flushes on Enter and clears immediately with Escape or the clear button", () => {
    vi.useFakeTimers();
    const onSearch = vi.fn();
    const onQueryChange = vi.fn();
    render(<SearchField defaultValue="hole" ariaLabel="Search model" onQueryChange={onQueryChange} onSearch={onSearch} />);
    const input = screen.getByLabelText("Search model") as HTMLInputElement;
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSearch).toHaveBeenLastCalledWith("hole");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    expect(onQueryChange).toHaveBeenLastCalledWith("");
    expect(onSearch).toHaveBeenLastCalledWith("");
    fireEvent.change(input, { target: { value: "boss" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear search model" }));
    expect(input.value).toBe("");
  });

  it("exposes scope, accessible result count, disabled state, and an input ref", () => {
    const onScopeChange = vi.fn();
    const inputRef = { current: null as HTMLInputElement | null };
    const { rerender } = render(<SearchField
      value="arm"
      ariaLabel="Search assembly"
      resultCount={1}
      scopes={[{ id: "all", label: "All" }, { id: "mates", label: "Mates" }]}
      scopeID="all"
      onScopeChange={onScopeChange}
      inputRef={inputRef}
    />);
    expect(screen.getByText("1 result")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("Search assembly scope"), { target: { value: "mates" } });
    expect(onScopeChange).toHaveBeenCalledWith("mates");
    expect(inputRef.current).toBe(screen.getByLabelText("Search assembly"));
    rerender(<SearchField value="arm" ariaLabel="Search assembly" resultCount={2} disabled />);
    expect(screen.getByText("2 results")).not.toBeNull();
    expect((screen.getByLabelText("Search assembly") as HTMLInputElement).disabled).toBe(true);
  });
});
