import { describe, expect, it } from "vitest";
import { fit, isCloud } from "./models";

describe("model fit", () => {
  const ram = 32 * 2 ** 30;
  it("classifies by unified memory", () => {
    expect(fit(8e9, ram)).toBe("good");
    expect(fit(18.6e9, ram)).toBe("tight");
    expect(fit(30e9, ram)).toBe("too-big");
    expect(fit(320, ram)).toBe("cloud");
    expect(fit(8e9, null)).toBe("unknown");
  });
  it("detects cloud models", () => {
    expect(isCloud({ name: "glm-5.3:cloud", size: 290 })).toBe(true);
    expect(isCloud({ name: "deepseek-v4-flash:0731-cloud", size: 326 })).toBe(true);
    expect(isCloud({ name: "gemma4:12b", size: 8e9 })).toBe(false);
  });
});
