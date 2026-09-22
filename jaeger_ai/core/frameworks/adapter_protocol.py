"""Adapter protocol utilities ported from hermes-paperclip-adapter.

Provides:
  1. Benign stderr / log reclassification (prevents harmless MCP/log noise from tripping failure states)
  2. Structured transcript line parsing and kaomoji / noise stripping
  3. Session codec for structured validation and session parameter migration across runs
"""

from __future__ import annotations

import re
from typing import Any


# ── ANSI & Decoration Stripping ──────────────────────────────────────────

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
# Strip parenthesized kawaii/kaomoji faces: (｡◕‿◕｡), (★ω★), (^_^), (╯°□°)╯︵ ┻━┻, etc.
_KAOMOJI_PATTERN = re.compile(r"[(][^()]{1,20}[)](?:[^\w\s]{1,10})?\s*", re.UNICODE)
_ASCII_TABLE_BORDER = re.compile(r"\+[-+=]{2,}\+")
_BOX_DRAWING = re.compile(r"[┌┬┐├┼┤└┴┘│─║═]+")


def strip_kaomoji(text: str) -> str:
    """Strip decorative kaomoji (e.g. (｡◕‿◕｡), (★ω★), (^_^)) from tool summary lines.

    Preserves standard semantic emoji (e.g. 💻, 🔍, 📁) and standard parenthetical notes intact.
    """
    if not text:
        return ""
    # Remove table flip artifacts if present
    cleaned = re.sub(r"[(]╯[^()]+[)]╯[^\s]*\s*┻━┻\s*", "", text)
    # Remove kaomoji faces containing decorative symbols
    def _replace_kaomoji(match: re.Match) -> str:
        s = match.group(0)
        # If it looks like normal text like (parenthetical), preserve it
        inner = s.strip().strip("()").strip()
        if re.match(r"^[a-zA-Z0-9_\-\s,.]+$", inner):
            return s
        return ""

    cleaned = _KAOMOJI_PATTERN.sub(_replace_kaomoji, cleaned).strip()
    return cleaned


def clean_transcript_text(text: str) -> str:
    """Clean terminal ASCII banners, box borders, ANSI sequences, and raw escape noise into clean markdown."""
    if not text:
        return ""
    # Strip ANSI escape codes
    text = _ANSI_ESCAPE_PATTERN.sub("", text)
    lines = []
    for line in text.splitlines():
        # Strip table border patterns
        line = _ASCII_TABLE_BORDER.sub("", line)
        trimmed = line.strip()
        if not trimmed or (_BOX_DRAWING.fullmatch(trimmed) and not re.search(r"\w", trimmed)):
            continue
        cleaned = strip_kaomoji(line)
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


# ── Benign log / stderr reclassification ──────────────────────────────────

_TIMESTAMP_PREFIX = re.compile(r"^\[?\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}")
_LOG_LEVEL_PREFIX = re.compile(r"^(?:[A-Z0-9_.-]+:\s*)?(?:INFO|DEBUG|WARN|WARNING)\b", re.IGNORECASE)
_WARNING_PREFIX = re.compile(r"^[a-zA-Z0-9_]*Warning:", re.IGNORECASE)
_HTTP_NOTICE = re.compile(r"^HTTP/\d\.\d\s+\d{3}\b")

_BENIGN_PATTERNS = [
    re.compile(r"Successfully registered all tools", re.IGNORECASE),
    re.compile(r"MCP [Ss]erver", re.IGNORECASE),
    re.compile(r"tool registered successfully", re.IGNORECASE),
    re.compile(r"Application initialized", re.IGNORECASE),
    re.compile(r"session initialized", re.IGNORECASE),
    re.compile(r"connection accepted", re.IGNORECASE),
    re.compile(r"Started server process", re.IGNORECASE),
    re.compile(r"Waiting for application startup", re.IGNORECASE),
    re.compile(r"Application startup complete", re.IGNORECASE),
    re.compile(r"Uvicorn running on", re.IGNORECASE),
]

_FATAL_ERROR_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\b(?:ZeroDivisionError|SyntaxError|NameError|AttributeError|TypeError|KeyError|IndexError|ImportError)\b:"),
    re.compile(r"^FATAL:\b", re.IGNORECASE),
    re.compile(r"^CRITICAL:\b", re.IGNORECASE),
    re.compile(r"\bRuntimeError:\b"),
]


def is_benign_stderr(line: str) -> bool:
    """Return True if a stderr log line is non-fatal operational telemetry.

    Ported from hermes-paperclip-adapter execute.ts.
    Many agent tools and MCP servers write structured logs or startup notices
    to stderr. Treating all stderr as errors causes false-positive run failures.
    """
    trimmed = line.strip()
    if not trimmed:
        return True
    # If explicitly matching fatal crash patterns, it is NOT benign
    if any(pat.search(trimmed) for pat in _FATAL_ERROR_PATTERNS):
        return False
    if _TIMESTAMP_PREFIX.search(trimmed):
        return True
    if _LOG_LEVEL_PREFIX.search(trimmed):
        return True
    if _WARNING_PREFIX.search(trimmed):
        return True
    if _HTTP_NOTICE.search(trimmed):
        return True
    return any(pattern.search(trimmed) for pattern in _BENIGN_PATTERNS)


def reclassify_log_stream(stream: str, chunk: str) -> tuple[str, str]:
    """Reclassify stream name ('stdout' or 'stderr') based on content benignness.

    Returns (effective_stream, cleaned_chunk).
    """
    if stream == "stderr" and is_benign_stderr(chunk):
        return "stdout", chunk
    return stream, chunk


# ── Tool line parsing ─────────────────────────────────────────────────────

_TOOL_VERB_MAP: dict[str, str] = {
    "$": "shell",
    "bash": "bash",
    "exec": "shell",
    "terminal": "shell",
    "shell": "shell",
    "search": "web_search",
    "fetch": "web_extract",
    "crawl": "web_extract",
    "navigate": "browser",
    "snapshot": "browser",
    "click": "browser",
    "type": "browser",
    "read": "read_file",
    "write": "write_file",
    "patch": "patch",
    "grep": "search_files",
    "find": "search_files",
    "plan": "plan",
    "recall": "recall",
    "proc": "process",
    "delegate": "delegate_task",
    "todo": "todo",
    "memory": "memory",
    "clarify": "clarify",
    "code": "execute_code",
    "execute": "execute_code",
    "read_file": "read_file",
    "write_file": "write_file",
    "search_files": "search_files",
    "execute_code": "execute_code",
}

_DURATION_PATTERN = re.compile(r"([\d.]+s)\s*(?:\([\d.]+s\))?\s*$")
_ERROR_SUFFIX_PATTERN = re.compile(r"\[(?:exit \d+|error|failed)\]\s*$", re.IGNORECASE)


def parse_tool_line(line: str) -> dict[str, Any] | None:
    """Parse a single tool output line into a structured dictionary.

    Returns:
      { 'name': str, 'detail': str, 'duration': str, 'has_error': bool, 'phase': str } or None
    """
    cleaned = line.strip()
    if not cleaned:
        return None

    phase = "start"
    # Detect done markers
    if cleaned.startswith("[TOOL_DONE]") or "[done]" in cleaned.lower():
        phase = "done"

    # Strip prefixes like [TOOL], [TOOL_DONE], [done], [running], [error], ┊, etc.
    cleaned = re.sub(r"^\[(?:tool_done|tool|done|running|error)\]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[┊│\s*]+\s*", "", cleaned)
    cleaned = strip_kaomoji(cleaned)

    if not cleaned:
        return None

    duration_match = _DURATION_PATTERN.search(cleaned)
    duration = duration_match.group(1) if duration_match else ""
    if duration_match:
        cleaned = cleaned[: duration_match.start()].strip()
        phase = "done"

    has_error = bool(_ERROR_SUFFIX_PATTERN.search(cleaned))
    if has_error:
        cleaned = _ERROR_SUFFIX_PATTERN.sub("", cleaned).strip()
        phase = "error"

    # Handle syntax like bash(command='ls -la')
    call_match = re.match(r"^([a-zA-Z0-9_$-]+)\((.*)\)$", cleaned)
    if call_match:
        verb = call_match.group(1).strip().lower()
        detail = call_match.group(2).strip()
        canonical_name = _TOOL_VERB_MAP.get(verb, verb)
        return {
            "name": canonical_name,
            "detail": detail,
            "duration": duration,
            "has_error": has_error,
            "phase": phase,
        }

    # Split first token (verb/symbol) from remaining arguments
    parts = cleaned.split(None, 1)
    if not parts:
        return None
    verb = parts[0].strip().lower()
    detail = parts[1].strip() if len(parts) > 1 else ""

    if verb not in _TOOL_VERB_MAP and not line.strip().startswith(("[TOOL]", "[TOOL_DONE]", "┊", "[done]")):
        # If it doesn't have tool prefixes and isn't a known verb, it's regular prose
        return None

    canonical_name = _TOOL_VERB_MAP.get(verb, verb)
    return {
        "name": canonical_name,
        "detail": detail,
        "duration": duration,
        "has_error": has_error,
        "phase": phase,
    }


# ── Session Codec ─────────────────────────────────────────────────────────

class SessionCodec:
    """Validates, serializes, and deserializes session continuity parameters.

    Ported from hermes-paperclip-adapter sessionCodec.
    Ensures safe cross-heartbeat and cross-process resume without losing state.
    """

    @staticmethod
    def normalize_session_id(session_id: str) -> str:
        """Strip provider/member prefixes (e.g. 'roundtable-hermes:') to yield canonical ID."""
        if not session_id:
            return ""
        if ":" in session_id:
            return session_id.split(":", 1)[1]
        return session_id

    @staticmethod
    def deserialize(raw: Any) -> dict[str, str] | None:
        """Parse raw session dictionary into canonical session parameter shape."""
        if not isinstance(raw, dict):
            return None
        session_id = (
            raw.get("sessionId")
            or raw.get("session_id")
            or raw.get("native_session_id")
        )
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            return None
        return {"session_id": session_id.strip()}

    @staticmethod
    def serialize(params: dict[str, Any] | None) -> dict[str, str] | None:
        """Serialize session parameters for durable storage or wire transfer."""
        if not isinstance(params, dict):
            return None
        session_id = (
            params.get("session_id")
            or params.get("sessionId")
            or params.get("native_session_id")
        )
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            return None
        return {"session_id": session_id.strip()}

    @staticmethod
    def get_display_id(params: dict[str, Any] | None) -> str | None:
        """Extract displayable session ID from session parameters."""
        deserialized = SessionCodec.deserialize(params)
        return deserialized["session_id"] if deserialized else None
