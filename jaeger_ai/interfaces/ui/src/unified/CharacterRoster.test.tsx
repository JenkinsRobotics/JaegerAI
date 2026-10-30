import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CharacterRoster, characterRoster } from "./CharacterRoster";

const NAMES = ["Jarvis", "Lilith", "Kamina", "Simon", "Bender", "GLaDOS", "HAL 9000", "TARS", "Mochi", "Clanker"];

describe("character roster", () => {
  it("keeps the full 20-character list with cards", () => {
    const all = characterRoster();
    expect(all).toHaveLength(20);
    expect(new Set(all.map((c) => c.id)).size).toBe(20);
    for (const c of all) { expect(c.name && c.role && c.description).toBeTruthy(); expect(c.cardUrl).toBeTruthy(); }
  });
  it("renders every character on the Agents page and opens its detail", () => {
    const go = vi.fn();
    render(<CharacterRoster onNavigate={go} />);
    const list = screen.getByRole("region", { name: "Characters" });
    expect(list.querySelectorAll("li")).toHaveLength(20);
    for (const n of NAMES) expect(screen.getAllByText(n).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTitle(/^Jarvis/));
    expect(go).toHaveBeenCalledWith("/characters?character=jarvis");
  });
});
