"""Cross-dialect parsing primitives.

These helpers are format-agnostic — they coerce JSON-ish payloads, repair
malformed argument blobs, and canonicalise tool names. Every per-dialect
module (:mod:`chatml`, :mod:`mistral`, :mod:`llama3`, :mod:`harmony`,
:mod:`gemma`) composes the primitives it needs from here, so the tuned
parsing chain lives in exactly one place even though five dialects lean
on it.

The logic is moved verbatim from the pre-refactor ``parsing/drift_parser``
so the benchmark suite compares apples to apples across the split.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any


_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_GEMMA_QUOTE = '<|"|>'
_GEMMA_KEY = re.compile(r"[^:,{}\[\]]+")
_GEMMA_BARE = re.compile(r"[^,{}\[\]]+")

# Paren-kwarg parser regexes — Gemma's Python-style ``key='value', n=3``.
_NEXT_KWARG = re.compile(r"\s*,?\s*([a-zA-Z_]\w*)\s*=\s*")
_KWARG_BOUNDARY = re.compile(r"\s*,\s*[a-zA-Z_]\w*\s*=")


def new_id(prefix: str = "drift") -> str:
    """Synthetic tool-call IDs for drift-recovered calls. The wire
    response had no real ID — we mint one so the loop's tool_call_id
    bookkeeping stays consistent across iterations."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def degemma_quotes(raw: str) -> str:
    """Normalize Gemma's special-token quotes (``<|"|>``, ``<|'|>``)
    into plain JSON double-quotes. Left as-is they break ``json.loads``
    and silently drop the whole tool call."""
    return raw.replace('<|"|>', '"').replace("<|\'|>", '"')


def coerce_scalar(val: str) -> Any:
    """Coerce a bare (unquoted) kwarg value to int / float / bool /
    None, else return it as a stripped string."""
    if val and val.lstrip("+-").replace(".", "", 1).isdigit():
        return float(val) if "." in val else int(val)
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    return val.strip("'\"")


def parse_paren_args(raw: str) -> dict[str, Any]:
    """Parse Python-style ``key='value', count=3`` kwargs into a dict.

    Quote-aware. A string value may itself contain the quote character
    (Gemma routinely emits ``content='print(\\'hi\\')'``) — naive
    ``'([^']*)'`` truncates at the first inner quote. A closing quote is
    honoured only when followed by end-of-input or ``, <identifier>=``.
    """
    out: dict[str, Any] = {}
    s = raw
    n = len(s)
    i = 0
    while i < n:
        m = _NEXT_KWARG.match(s, i)
        if not m:
            break
        key = m.group(1)
        i = m.end()
        if i < n and s[i] in ("'", '"'):
            quote = s[i]
            i += 1
            buf: list[str] = []
            while i < n:
                c = s[i]
                if c == "\\" and i + 1 < n:
                    buf.append(s[i + 1])
                    i += 2
                    continue
                if c == quote:
                    rest = s[i + 1:]
                    if rest.strip() == "" or _KWARG_BOUNDARY.match(rest):
                        i += 1
                        break  # real closing quote
                    buf.append(c)  # literal quote inside the value
                    i += 1
                    continue
                buf.append(c)
                i += 1
            out[key] = "".join(buf)
        else:
            j = s.find(",", i)
            if j == -1:
                j = n
            out[key] = coerce_scalar(s[i:j].strip())
            i = j
    return out


def _gemma_skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def parse_gemma_value(s: str, i: int) -> tuple[Any, int]:
    """Recursive-descent parse of ONE Gemma-native value at ``s[i]``.
    Returns ``(value, index_after)``. Raises ``ValueError`` on malformed
    input."""
    i = _gemma_skip_ws(s, i)
    if i >= len(s):
        raise ValueError("unexpected end of input")
    if s.startswith(_GEMMA_QUOTE, i):
        start = i + len(_GEMMA_QUOTE)
        end = s.find(_GEMMA_QUOTE, start)
        if end == -1:
            raise ValueError("unterminated string")
        return s[start:end], end + len(_GEMMA_QUOTE)
    if s[i] == "{":
        obj: dict[str, Any] = {}
        i = _gemma_skip_ws(s, i + 1)
        if i < len(s) and s[i] == "}":
            return obj, i + 1
        while True:
            i = _gemma_skip_ws(s, i)
            if s.startswith(_GEMMA_QUOTE, i):
                key, i = parse_gemma_value(s, i)
            else:
                km = _GEMMA_KEY.match(s, i)
                if not km:
                    raise ValueError("expected key")
                key, i = km.group(0).strip(), km.end()
            i = _gemma_skip_ws(s, i)
            if i >= len(s) or s[i] != ":":
                raise ValueError("expected ':'")
            val, i = parse_gemma_value(s, i + 1)
            obj[str(key)] = val
            i = _gemma_skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "}":
                return obj, i + 1
            raise ValueError("expected ',' or '}'")
    if s[i] == "[":
        arr: list[Any] = []
        i = _gemma_skip_ws(s, i + 1)
        if i < len(s) and s[i] == "]":
            return arr, i + 1
        while True:
            val, i = parse_gemma_value(s, i)
            arr.append(val)
            i = _gemma_skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "]":
                return arr, i + 1
            raise ValueError("expected ',' or ']'")
    bm = _GEMMA_BARE.match(s, i)
    if not bm:
        raise ValueError("expected value")
    return coerce_scalar(bm.group(0).strip()), bm.end()


def parse_loose_args(raw: str) -> dict[str, Any]:
    """Lossy fallback for Gemma input the recursive parser rejects.

    Returns whatever ``key:value`` pairs we can pluck out — better to
    fire the call with some args than drop it entirely. Used only after
    :func:`parse_gemma_value` has failed.
    """
    cleaned = degemma_quotes(raw)
    try:
        result = (
            json.loads("{" + cleaned + "}")
            if not cleaned.startswith("{")
            else json.loads(cleaned)
        )
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    pairs: dict[str, Any] = {}
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*\"([^\"]*)\"", cleaned):
        pairs[match.group(1)] = match.group(2)
    if pairs:
        return pairs
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*([^,}]+)", cleaned):
        pairs[match.group(1).strip()] = match.group(2).strip().strip('"').strip("'")
    return pairs


def parse_gemma_args(raw: str) -> dict[str, Any]:
    """Parse Gemma 4's native tool-call brace arguments into a dict.

    Handles arbitrary nesting via :func:`parse_gemma_value`; falls back
    to :func:`parse_loose_args` when the input is too malformed for
    the recursive parser rather than dropping the whole call."""
    s = (raw or "").strip()
    if not s:
        return {}
    body = s if s.startswith("{") else "{" + s + "}"
    try:
        val, _ = parse_gemma_value(body, 0)
        if isinstance(val, dict):
            return val
    except (ValueError, IndexError):
        pass
    return parse_loose_args(raw)


def parse_drift_payload(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of the JSON-ish payload inside a
    ``<tool_call>…</tool_call>`` block.

    Walks an increasingly tolerant chain:

      1. Strict JSON after de-Gemma-quoting.
      2. Strict-off JSON (tolerates literal control characters in strings).
      3. Trailing-comma stripped, then strict-off JSON.
      4. Jaeger's loose Gemma parser — bare keys, Gemma quote tokens,
         missing key-quotes — with surrounding quote chars stripped from
         the keys / string values it leaves embedded.
    """
    text = (raw or "").strip()
    if not text:
        return None
    degemma = degemma_quotes(text)
    candidates = [degemma]
    stripped = _TRAILING_COMMA.sub(r"\1", degemma)
    if stripped != degemma:
        candidates.append(stripped)
    for candidate in candidates:
        for strict in (True, False):
            try:
                parsed = json.loads(candidate, strict=strict)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    loose = parse_gemma_args(text)
    if not loose:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in loose.items():
        if isinstance(key, str):
            key = key.strip().strip('"').strip("'")
        if isinstance(value, str):
            value = value.strip().strip('"').strip("'")
        cleaned[key] = value
    return cleaned or None


def payload_to_call(inner: str) -> dict[str, Any] | None:
    """Turn the captured body of a JSON-envelope tool call
    (``<tool_call>…</tool_call>`` or the legacy ``<|tool_call|>…``) into
    a ``{"name", "args"}`` dict, or ``None`` when no name is recoverable.

    Two emission styles for arguments:
      • Hermes-XML:  ``{"name": "X", "arguments": {...}}``
      • Gemma flat:  ``{"name": "X", "path": "...", ...}`` — every
        remaining top-level key IS an arg.
    """
    payload = parse_drift_payload(inner)
    if not payload:
        return None
    name = payload.pop("name", None) or payload.pop("tool", None) or ""
    if "arguments" in payload:
        args: Any = payload["arguments"] or {}
    elif "args" in payload:
        args = payload["args"] or {}
    else:
        args = payload
    if isinstance(args, str):
        nested = parse_drift_payload(args)
        args = nested if nested is not None else {}
    if not name:
        return None
    if not isinstance(args, dict):
        args = {"value": args}
    return {"name": str(name), "args": args}


def _coerce_args_dict(parsed: Any) -> dict[str, Any] | None:
    """Coerce a ``json.loads`` result into a plain args dict, or
    ``None`` when it cannot be one. Also unwraps the double-encoded
    ``'{"x": 1}'`` string local models occasionally emit."""
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        try:
            inner = json.loads(parsed, strict=False)
        except json.JSONDecodeError:
            return None
        if isinstance(inner, dict):
            return inner
    return None


def repair_arguments(raw: str) -> tuple[dict[str, Any], bool]:
    """Best-effort repair of a malformed tool-call ``arguments`` JSON
    string the *structured* tool-calling path handed us. Returns
    ``(args, recovered)``. ``recovered`` is ``False`` only when every
    pass failed and the caller is getting ``{}`` as a last resort — so
    it can record the parse failure instead of swallowing it silently.

    Conservative on purpose: fixes drift we've actually observed (Gemma
    special-token quotes, literal control chars, trailing commas, wholly
    single-quoted blobs, Python ``None``/``null``) then hands off to the
    tolerant Gemma parser rather than guessing further.
    """
    s = (raw or "").strip()
    if not s or s.lower() in ("none", "null"):
        return {}, True

    cleaned = degemma_quotes(s)
    for candidate in (cleaned, _TRAILING_COMMA.sub(r"\1", cleaned)):
        try:
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    if "'" in cleaned and '"' not in cleaned:
        try:
            parsed = json.loads(cleaned.replace("'", '"'), strict=False)
        except json.JSONDecodeError:
            parsed = None
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    # Hermes-adoption passes — truncated and control-char-laced JSON.
    # A length-cut tool call ends mid-structure (``{"path": "x", "con``);
    # balancing the brackets often recovers everything before the cut.
    # Some llama.cpp builds also emit literal control chars inside
    # string values ALONGSIDE other malformations, where the
    # strict=False pass above wasn't enough on its own.
    balanced = _balance_brackets(cleaned)
    for candidate in (
        balanced,
        _escape_ctrl_in_json_strings(balanced),
    ):
        if candidate == cleaned:
            continue
        try:
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    loose = parse_gemma_args(s)
    if loose:
        return loose, True

    return {}, False


def _balance_brackets(raw: str) -> str:
    """Close unterminated structures in a truncated JSON blob.

    Closes an unterminated string first (odd count of unescaped double
    quotes), strips a trailing comma left by the cut, then appends the
    missing ``}`` / ``]`` in nesting order. Returns the input unchanged
    when nothing is missing — the caller validates with ``json.loads``
    and discards on failure, so this never has to be perfect."""
    if not raw or (raw.count("{") == 0 and raw.count("[") == 0):
        return raw
    out = raw.rstrip()
    # Unterminated string: odd count of unescaped double quotes.
    unescaped = 0
    i = 0
    while i < len(out):
        ch = out[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            unescaped += 1
        i += 1
    if unescaped % 2 == 1:
        out += '"'
    out = out.rstrip()
    if out.endswith(","):
        out = out[:-1]
    # Close remaining open structures in proper nesting order.
    stack: list[str] = []
    in_str = False
    i = 0
    while i < len(out):
        ch = out[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch in "{[":
                stack.append(ch)
            elif ch in "}]" and stack:
                stack.pop()
        i += 1
    for opener in reversed(stack):
        out += "}" if opener == "{" else "]"
    return out


def _escape_ctrl_in_json_strings(raw: str) -> str:
    """Escape literal control characters (0x00–0x1F) inside JSON string
    values as ``\\uXXXX``. Pass-through outside strings and for
    already-escaped sequences."""
    out: list[str] = []
    in_string = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
        i += 1
    return "".join(out)


# Explicit alias map: pre-rename / pre-consolidation tool names →
# their current canonical name. Only added when the rename was
# documented and the older name had real bench / training data
# behind it. NOT a fuzzy match table — an alias here only fires
# if the canonical name is in the agent's registered ``valid`` set,
# so adding entries is safe.
#
# Keep this small and intentional. The point is to absorb known
# historical drift (``run_python`` → ``execute_code``); we do NOT
# want a model guessing a tool that doesn't exist and silently
# landing on something else.
_TOOL_ALIASES: dict[str, str] = {
    # Phase-9 rename.
    "run_python":   "execute_code",
    "run_shell":    "terminal",
    # Pre-umbrella memory verbs. The granular tools are still
    # registered (under the ``memory_granular`` toolset) so this
    # alias only fires when they're not currently visible AND the
    # umbrella is.
    # NB ordering matters — these are checked LAST, after the
    # exact-case lookup. A model that explicitly calls ``remember``
    # while the granular toolset is loaded still routes there.
    # Aliasing only kicks in when ``remember`` is NOT in ``valid``
    # but ``memory`` is.
    # Voice / file legacy spellings.
    "speak":        "text_to_speech",
    "file_write":   "write_file",
    "file_read":    "read_file",
    # Skill index — old names that may surface from training data.
    "list_tools":   "describe_tool",
}


def normalize_tool_name(name: str, valid: frozenset[str] | set[str]) -> str:
    """Map a drifted tool name onto a real one via exact alias / case /
    separator variants. No fuzzy matching — an unrecognised name is
    returned unchanged so dispatch surfaces a clean 'unknown tool'
    error and the model retries, rather than silently dispatching a
    guess.

    Resolution order (first match wins):
      1. exact match in ``valid``
      2. case / separator / trailing-``tool``-suffix variants
      3. the explicit :data:`_TOOL_ALIASES` table (only when the
         alias target is itself in ``valid``)
    """
    raw = (name or "").strip()
    if not raw or not valid or raw in valid:
        return raw
    candidates: list[str] = []

    def _add(candidate: str) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    lowered = raw.lower()
    _add(lowered)
    _add(lowered.replace("-", "_").replace(" ", "_").replace(".", "_"))
    _add(re.sub(r"(?<!^)(?=[A-Z])", "_", raw).lower())
    # A trailing ``tool`` / ``_tool`` the model sometimes tacks onto a
    # class-like emission (``ReadFileTool``, ``read_file_tool``).
    for base in list(candidates):
        for suffix in ("_tool", "-tool", "tool"):
            if base.endswith(suffix) and len(base) > len(suffix):
                _add(base[: -len(suffix)].rstrip("_-"))
    for candidate in candidates:
        if candidate in valid:
            return candidate
    # Explicit alias as last resort — only redirects when the alias's
    # target is a real registered tool.
    for candidate in candidates + [raw]:
        target = _TOOL_ALIASES.get(candidate)
        if target and target in valid:
            return target
    return raw


def tool_schemas_json(tools: list[Any]) -> str:
    """Render the OpenAI-shaped JSON schema block the per-dialect
    presentation prose embeds. Centralised so every dialect emits the
    same catalogue serialization."""
    schemas = [t.to_openai_schema() for t in tools]
    return json.dumps(schemas, ensure_ascii=False)


__all__ = [
    "new_id",
    "degemma_quotes",
    "coerce_scalar",
    "parse_paren_args",
    "parse_gemma_value",
    "parse_loose_args",
    "parse_gemma_args",
    "parse_drift_payload",
    "payload_to_call",
    "repair_arguments",
    "normalize_tool_name",
    "tool_schemas_json",
]
