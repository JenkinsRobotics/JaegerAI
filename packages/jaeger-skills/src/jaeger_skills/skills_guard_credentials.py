"""Skill-only credential rules for ``jaeger_skills.skills_guard``.

Adapted from NousResearch/hermes-agent (MIT License) with zero external
config-module coupling and extended to cover both Jaeger (.jaeger) and
Hermes (.hermes) secret stores.
"""

from __future__ import annotations

import io
import re
import tokenize


def _closed(depth: int) -> str:
    return r"\([^()\n]*\)" if depth == 1 else rf"\((?:[^()\n]|{_closed(depth - 1)})*\)"


def _open_prefix(depth: int) -> str:
    return r"[^()\n]*" if depth == 1 else rf"(?:[^()\n]|{_closed(depth - 1)})*(?:\({_open_prefix(depth - 1)})?"


SKILL_ONLY_PATTERNS = [
    (
        re.compile(
            rf"\b(?:load_dotenv|dotenv_values)\s*\({_open_prefix(4)}"
            r"(?:JAEGER_STATE_DIR|HERMES_HOME|get_hermes_home|[~/\\\"']\.(?:jaeger|hermes)(?:[/\\\"']|$))"
        ),
        "jaeger_env_dotenv",
        "high",
        "exfiltration",
        "loads the Jaeger/Hermes .env (every key of the profile) into the script",
    ),
]

_ENV_READ_IDS = frozenset({"python_getenv_secret", "python_environ_get_secret"})
_ENV_READ_NAME_RE = re.compile(r'(?:getenv|environ\s*\.\s*get|environ\s*\[)\s*\(?\s*["\']([A-Za-z_]\w*)["\']')
_TEXT_TOKENS = {tokenize.COMMENT, tokenize.STRING} | {
    getattr(tokenize, name) for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE") if hasattr(tokenize, name)
}
_FSTRING_PREFIX = re.compile(r"(?i)[rbu]*f")

DEFAULT_PROVIDER_KEY_ENV_VARS: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "XAI_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "COHERE_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "PERPLEXITY_API_KEY",
        "HUGGINGFACE_API_KEY",
        "HF_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "JAEGER_GATEWAY_TOKEN",
    }
)


def code_views(lines: list[str]) -> tuple[list[str], list[bytearray]] | None:
    view, in_text = [list(ln) for ln in lines], [bytearray(len(ln)) for ln in lines]
    try:
        for tok in tokenize.generate_tokens(io.StringIO("\n".join(lines)).readline):
            if tok.type not in _TEXT_TOKENS or tok.type == tokenize.STRING and _FSTRING_PREFIX.match(tok.string):
                continue
            (r0, c0), (r1, c1) = tok.start, tok.end
            for r in range(r0 - 1, min(r1, len(lines))):
                row = view[r]
                b = min(c1 if r == r1 - 1 else len(row), len(row))
                a = min(c0 if r == r0 - 1 else 0, b)
                in_text[r][a:b] = b"\x01" * (b - a)
                row[a:b] = [" " if tok.type == tokenize.COMMENT or ch in "()" else ch for ch in row[a:b]]
    except (tokenize.TokenError, SyntaxError):
        return None
    return ["".join(v) for v in view], in_text


def model_provider_key_names() -> frozenset[str]:
    return DEFAULT_PROVIDER_KEY_ENV_VARS


def raise_provider_key_reads(findings: list, lines: list[str], in_text: list[bytearray] | None = None) -> None:
    reads = [f for f in findings if f.pattern_id in _ENV_READ_IDS]
    if not reads:
        return
    provider_keys = model_provider_key_names()
    for f in reads:
        line = lines[f.line - 1]
        named = [
            m[1]
            for m in _ENV_READ_NAME_RE.finditer(line)
            if m[1].upper() in provider_keys and (in_text is None or not in_text[f.line - 1][m.start()])
        ]
        if named:
            f.pattern_id, f.severity = "provider_key_env_read", "high"
            f.description = (
                f"reads model-provider key {named[0]}; skill scripts never receive it, "
                "and the skill must not fetch it another way"
            )
