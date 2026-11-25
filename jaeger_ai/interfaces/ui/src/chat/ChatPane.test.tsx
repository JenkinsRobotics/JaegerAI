import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ChatPane } from "./ChatPane";
import type { ChatHost, ChatPaneMount, ChatPaneOptions } from "./host";

it("keeps the focused composer and stream mount through shell refreshes", async () => {
  const host = {} as ChatHost;
  const dispose = vi.fn();
  let options: ChatPaneOptions | undefined;
  const mount = vi.fn<ChatPaneMount>((el, _host, nextOptions) => {
    options = nextOptions;
    el.append(document.createElement("textarea"));
    return dispose;
  });
  const oldRecovery = vi.fn();
  const newRecovery = vi.fn();
  const oldAvatar = vi.fn();
  const newAvatar = vi.fn();
  const view = render(<ChatPane host={host} mount={mount} sessionId="a" onSessionMissing={oldRecovery} onAvatarState={oldAvatar} />);
  const composer = view.getByRole("textbox") as HTMLTextAreaElement;
  composer.value = "Unsent draft";
  composer.focus();

  view.rerender(<ChatPane host={host} mount={mount} sessionId="a" agents={[]} onSessionMissing={newRecovery} onAvatarState={newAvatar} />);
  expect(mount).toHaveBeenCalledTimes(1);
  expect(dispose).not.toHaveBeenCalled();
  expect(view.getByRole("textbox")).toBe(composer);
  expect(composer).toHaveFocus();
  expect(composer).toHaveValue("Unsent draft");
  options?.onSessionMissing?.("a");
  const avatar = options?.onAvatarState;
  expect(avatar).toBeDefined();
  avatar?.("idle");
  expect(newRecovery).toHaveBeenCalledWith("a");
  expect(newAvatar).toHaveBeenCalledWith("idle");
  expect(oldRecovery).not.toHaveBeenCalled();
  expect(oldAvatar).not.toHaveBeenCalled();

  view.rerender(<ChatPane host={host} mount={mount} sessionId="b" onSessionMissing={newRecovery} onAvatarState={newAvatar} />);
  await Promise.resolve();
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(mount).toHaveBeenCalledTimes(2);
  expect(view.getByRole("textbox")).not.toBe(composer);
});
