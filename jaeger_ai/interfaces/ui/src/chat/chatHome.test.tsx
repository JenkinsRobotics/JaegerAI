import { afterEach, describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { ChatHome, HOME_CHIPS } from "./ChatHome";

describe("ChatHome", () => {
  afterEach(() => { history.replaceState(null, "", "/"); document.body.innerHTML = ""; });
  it("renders the mark and only real quick actions that navigate", async () => {
    const el = document.createElement("div"); document.body.appendChild(el);
    await act(async () => createRoot(el).render(<ChatHome />));
    expect(el.querySelector(".jg-chat-home__mark")?.getAttribute("data-logo")).toBe("shield-j");
    expect(el.querySelector(".jg-chat-home__mark svg path")).not.toBeNull();
    const chips = [...el.querySelectorAll<HTMLButtonElement>(".jg-chat-home__chip")];
    expect(chips.map((c) => c.textContent)).toEqual(HOME_CHIPS.map((c) => c.label));
    await act(async () => chips[0].click());
    expect(location.pathname).toBe("/work/backlog");
    let opened = false; addEventListener("jaeger:palette", () => { opened = true; }, { once: true });
    await act(async () => chips.at(-1)!.click());
    expect(opened).toBe(true);
  });
});
