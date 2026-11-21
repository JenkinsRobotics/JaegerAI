import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { ChatHome, HOME_CHIPS } from "./ChatHome";

describe("ChatHome", () => {
  afterEach(() => { history.replaceState(null, "", "/"); document.body.innerHTML = ""; });
  it("renders the greeting and suggestion chips that submit their prompts", async () => {
    const onSuggest = vi.fn();
    const el = document.createElement("div"); document.body.appendChild(el);
    await act(async () => createRoot(el).render(<ChatHome onSuggest={onSuggest} />));
    expect(el.querySelector(".jg-chat-home__hello")?.textContent).toBe("Hello");
    expect(el.querySelector(".jg-chat-home__title")?.textContent).toBe("What should we work on?");
    const chips = [...el.querySelectorAll<HTMLButtonElement>(".jg-chat-home__chip")];
    expect(chips.map((c) => c.textContent)).toEqual(HOME_CHIPS.map((c) => c.label));
    await act(async () => chips[0].click());
    expect(onSuggest).toHaveBeenCalledExactlyOnceWith(HOME_CHIPS[0].prompt);
  });
  it("supports custom quick-action chips", async () => {
    const run = vi.fn();
    const el = document.createElement("div"); document.body.appendChild(el);
    await act(async () => createRoot(el).render(<ChatHome chips={[{ id: "custom", label: "Custom action", run }]} />));
    const chip = el.querySelector<HTMLButtonElement>(".jg-chat-home__chip")!;
    expect(chip.textContent).toBe("Custom action");
    await act(async () => chip.click());
    expect(run).toHaveBeenCalledOnce();
  });
});
