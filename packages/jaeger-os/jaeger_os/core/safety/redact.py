"""Secret redaction for logs, the audit trail, and trajectory exports.

`core/trajectory.py` admits the gap in a comment — the caller "is
responsible for redacting anything that should not land in the
trajectory log" — and no caller does. `run_shell` writes the command
string straight into `logs/audit.log`; a command or skill that handles a
credential leaks it, permanently, into a tamper-evident log.

This module closes that gap (audit A3). `redact_text` masks API keys,
tokens, auth headers, private keys and credentialed URLs in a string;
`redact_obj` walks a dict / list and redacts every string inside.
Pattern set ported from hermes-agent's `agent/redact.py`.

Always on — the audit log is a safety artifact; plaintext secrets in it
are a liability, so there is deliberately no opt-out. Long tokens keep a
short head/tail for debuggability; short ones are fully masked.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["mask_secret", "redact_obj", "redact_text"]


# Known API-key / token prefixes — match the prefix + contiguous token.
_PREFIX_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{10,}",          # OpenAI / OpenRouter / Anthropic
    r"sk-ant-[A-Za-z0-9_-]{10,}",      # Anthropic (explicit)
    r"AIza[A-Za-z0-9_-]{30,}",         # Google / Gemini API keys
    r"ghp_[A-Za-z0-9]{10,}",           # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",   # GitHub PAT (fine-grained)
    r"gh[ousr]_[A-Za-z0-9]{10,}",      # GitHub OAuth / app tokens
    r"xox[baprs]-[A-Za-z0-9-]{10,}",   # Slack tokens
    r"AKIA[A-Z0-9]{16}",               # AWS Access Key ID
    r"hf_[A-Za-z0-9]{10,}",            # HuggingFace token
    r"r8_[A-Za-z0-9]{10,}",            # Replicate
    r"sk_live_[A-Za-z0-9]{10,}",       # Stripe live secret
    r"sk_test_[A-Za-z0-9]{10,}",       # Stripe test secret
    r"npm_[A-Za-z0-9]{10,}",           # npm token
    r"pypi-[A-Za-z0-9_-]{10,}",        # PyPI token
    r"gsk_[A-Za-z0-9]{10,}",           # Groq
    r"tvly-[A-Za-z0-9]{10,}",          # Tavily
    r"pplx-[A-Za-z0-9]{10,}",          # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",         # Fal.ai
]
_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(" + "|".join(_PREFIX_PATTERNS) + r")(?![A-Za-z0-9_-])"
)

# KEY=value where KEY looks secret-ish (OPENAI_API_KEY=…, DB_PASSWORD=…).
_ENV_ASSIGN_RE = re.compile(
    r"([A-Z0-9_]{0,50}(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL"
    r"|AUTH)[A-Z0-9_]{0,50})\s*=\s*(['\"]?)(\S+)\2"
)

# "apiKey": "value" / "token": "value" in JSON-ish text.
_JSON_FIELD_RE = re.compile(
    r'("(?:api_?key|token|secret|password|access_token|refresh_token'
    r'|auth_token|bearer|client_secret)")\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)

# Authorization: Bearer <token>
_AUTH_HEADER_RE = re.compile(r"(Authorization:\s*Bearer\s+)(\S+)", re.IGNORECASE)

# Telegram bot tokens — <digits>:<token>.
_TELEGRAM_RE = re.compile(r"(bot)?(\d{8,}):([-A-Za-z0-9_]{30,})")

# PEM private-key blocks.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"
)

# protocol://user:PASSWORD@host connection strings.
_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:/\s]+:)"
    r"([^@/\s]+)(@)",
    re.IGNORECASE,
)

# http(s)/ws/ftp URLs carrying user:password@.
_URL_USERINFO_RE = re.compile(
    r"(https?|wss?|ftp)://([^/\s:@]+):([^/\s@]+)@"
)

# JWTs — header.payload[.signature], header always starts with eyJ.
_JWT_RE = re.compile(
    r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}"
)


def mask_secret(value: str, *, head: int = 4, tail: int = 4,
                floor: int = 12, placeholder: str = "***") -> str:
    """Mask a secret for display, keeping ``head`` + ``tail`` chars.

    Values shorter than ``floor`` are fully masked. Use this anywhere a
    credential must be shown truncated (status panels, config dumps)."""
    if not value:
        return ""
    if len(value) < floor:
        return placeholder
    return f"{value[:head]}...{value[-tail:]}"


def _mask_token(token: str) -> str:
    """Mask a token found in free text — keeps 6 head / 4 tail above 18 chars."""
    if not token:
        return "***"
    return mask_secret(token, head=6, tail=4, floor=18)


def redact_text(text: Any) -> Any:
    """Mask API keys, tokens, auth headers, private keys and credentialed
    URLs in ``text``. Non-string input and non-matching text pass
    through unchanged."""
    if not isinstance(text, str) or not text:
        return text
    text = _PREFIX_RE.sub(lambda m: _mask_token(m.group(1)), text)
    text = _ENV_ASSIGN_RE.sub(
        lambda m: f"{m.group(1)}={m.group(2)}{_mask_token(m.group(3))}{m.group(2)}",
        text,
    )
    text = _JSON_FIELD_RE.sub(
        lambda m: f'{m.group(1)}: "{_mask_token(m.group(2))}"', text,
    )
    text = _AUTH_HEADER_RE.sub(
        lambda m: m.group(1) + _mask_token(m.group(2)), text,
    )
    text = _TELEGRAM_RE.sub(
        lambda m: f"{m.group(1) or ''}{m.group(2)}:***", text,
    )
    text = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    text = _DB_CONNSTR_RE.sub(lambda m: f"{m.group(1)}***{m.group(3)}", text)
    text = _URL_USERINFO_RE.sub(
        lambda m: f"{m.group(1)}://{m.group(2)}:***@", text,
    )
    text = _JWT_RE.sub(lambda m: _mask_token(m.group(0)), text)
    return text


def redact_obj(obj: Any) -> Any:
    """Recursively redact every string inside a dict / list / tuple.

    Returns a redacted copy; the input is not mutated. Use this on a
    structured payload (tool args, an audit entry) before it is written
    to disk."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact_obj(v) for v in obj)
    return obj
