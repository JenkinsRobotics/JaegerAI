import { expect, test } from "vitest";
import { parseNumberExpression } from "./number-expression";

test("parses precedence, parentheses, unary signs, decimals, and exponents", () => {
  expect(parseNumberExpression("2 + 3 * 4")).toBe(14);
  expect(parseNumberExpression("(2 + 3) * -4")).toBe(-20);
  expect(parseNumberExpression(".5 + 1e2")).toBe(100.5);
});

test("rejects incomplete, nonnumeric, and nonfinite expressions", () => {
  expect(parseNumberExpression("2 +")).toBeNull();
  expect(parseNumberExpression("12 mm")).toBeNull();
  expect(parseNumberExpression("1 / 0")).toBeNull();
  expect(parseNumberExpression("")).toBeNull();
});
