/** Small arithmetic parser for authoring fields. It intentionally supports
 * only numeric literals, parentheses, and + - * /; unit conversion remains a
 * Core responsibility. */
export function parseNumberExpression(source: string): number | null {
  let index = 0;

  const skipWhitespace = () => {
    while (/\s/.test(source[index] ?? "")) index += 1;
  };

  const parsePrimary = (): number | null => {
    skipWhitespace();
    if (source[index] === "(") {
      index += 1;
      const value = parseExpression();
      skipWhitespace();
      if (value === null || source[index] !== ")") return null;
      index += 1;
      return value;
    }

    const match = source
      .slice(index)
      .match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?/i);
    if (!match) return null;
    index += match[0].length;
    const value = Number(match[0]);
    return Number.isFinite(value) ? value : null;
  };

  const parseUnary = (): number | null => {
    skipWhitespace();
    if (source[index] === "+" || source[index] === "-") {
      const negative = source[index] === "-";
      index += 1;
      const value = parseUnary();
      return value === null ? null : negative ? -value : value;
    }
    return parsePrimary();
  };

  const parseTerm = (): number | null => {
    let value = parseUnary();
    if (value === null) return null;
    while (true) {
      skipWhitespace();
      const operator = source[index];
      if (operator !== "*" && operator !== "/") return value;
      index += 1;
      const right = parseUnary();
      if (right === null) return null;
      value = operator === "*" ? value * right : value / right;
      if (!Number.isFinite(value)) return null;
    }
  };

  const parseExpression = (): number | null => {
    let value = parseTerm();
    if (value === null) return null;
    while (true) {
      skipWhitespace();
      const operator = source[index];
      if (operator !== "+" && operator !== "-") return value;
      index += 1;
      const right = parseTerm();
      if (right === null) return null;
      value = operator === "+" ? value + right : value - right;
    }
  };

  const value = parseExpression();
  skipWhitespace();
  return value !== null && index === source.length && Number.isFinite(value)
    ? value
    : null;
}
