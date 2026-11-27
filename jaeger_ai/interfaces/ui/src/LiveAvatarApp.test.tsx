import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveAvatarApp, avatarAppUrl } from "@jaeger/ui-avatar";

describe("LiveAvatarApp", () => {
  it("embeds the JaegerAvatar stage in stream mode with the chosen face", () => {
    const { container } = render(<LiveAvatarApp face="vita" compact />);
    const frame = container.querySelector("iframe.jg-av-live") as HTMLIFrameElement;
    expect(frame).toBeTruthy();
    expect(frame.src).toBe(`${avatarAppUrl()}/?face=vita&stream`);
    expect(frame.dataset.compact).toBe("true");
  });
});
