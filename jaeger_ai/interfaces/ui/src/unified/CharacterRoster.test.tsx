import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CharacterRoster, characterRoster, rosterGroups } from "./CharacterRoster";

const NAMES = ["Jarvis", "Lilith", "Kamina", "Simon", "Bender", "GLaDOS", "HAL 9000", "TARS", "Mochi", "Clanker"];

describe("character roster", () => {
  it("keeps the full 20-character list with cards", () => {
    const all = characterRoster();
    expect(all).toHaveLength(20);
    expect(new Set(all.map((c) => c.id)).size).toBe(20);
    for (const c of all) { expect(c.name && c.role && c.description).toBeTruthy(); expect(c.cardUrl).toBeTruthy(); }
  });
  it("splits Characters (art) from Bots by the category field", () => {
    const { characters, bots } = rosterGroups();
    expect(characters.length + bots.length).toBe(20);
    expect(characters.at(-1)!.name).toBe("Helldiver");
    expect(bots.map((b) => b.id)).toEqual(expect.arrayContaining(["assistant", "robotics_architect", "reliability_auditor", "research_strategist", "systems_principal"]));
    expect(bots.every((b) => b.category === "professional")).toBe(true);
  });
  it("renders Characters and Bots rows and both open the create-agent detail", () => {
    const go = vi.fn();
    render(<CharacterRoster onNavigate={go} />);
    const chars = screen.getByRole("region", { name: "Characters" });
    const bots = screen.getByRole("region", { name: "Bots" });
    expect(chars.querySelectorAll("li")).toHaveLength(15);
    expect(bots.querySelectorAll("li")).toHaveLength(5);
    expect(chars.textContent).not.toContain("Robotics Architect");
    for (const n of NAMES) expect(screen.getAllByText(n).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTitle(/^Jarvis/));
    expect(go).toHaveBeenCalledWith("/agents/characters?character=jarvis");
    fireEvent.click(bots.querySelector("button[title^=\"Robotics Architect\"]")!);
    expect(go).toHaveBeenCalledWith("/agents/characters?character=robotics_architect");
  });
});
