"""Jaeger's built-in input/output guardrails (see ``jaeger_agent.guardrails``).

* output ``secret_leak`` (on by default): the final answer must not carry a
  credential-shaped token (GitHub / OpenAI-style / Slack / HF / Google keys,
  the same patterns :mod:`jaeger_ai.core.redaction` masks in durable logs).
  Opt out with ``guardrails.output.secret_leak: false`` in config.yaml.
* input ``blocked_pattern`` (off until configured): any regex listed under
  ``guardrails.input.block_patterns`` trips on the owner's message.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from jaeger_agent import guardrails
from jaeger_agent.guardrails import GuardrailResult

logger = logging.getLogger(__name__)


def _config(config_path: Path | str | None) -> dict[str, Any]:
    try:
        import yaml
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) if config_path else {}
        section = (raw or {}).get("guardrails") if isinstance(raw, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception:  # noqa: BLE001 — unreadable config keeps the defaults
        return {}


def secret_leak(text: str) -> GuardrailResult | None:
    from jaeger_ai.core.redaction import _PREFIXED_SECRET
    match = _PREFIXED_SECRET.search(text or "")
    if match:
        kind = match.group(0)[:4].rstrip("_-")
        return GuardrailResult(True, f"the reply contained a credential-shaped token ({kind}…)", "secret_leak")
    return None


def install(config_path: Path | str | None) -> list[str]:
    """Register the configured guardrails; returns their names."""
    cfg = _config(config_path)
    names: list[str] = []
    out_cfg = cfg.get("output") if isinstance(cfg.get("output"), dict) else {}
    if out_cfg.get("secret_leak", True) is not False:
        guardrails.register_output(secret_leak, name="secret_leak")
        names.append("output:secret_leak")
    in_cfg = cfg.get("input") if isinstance(cfg.get("input"), dict) else {}
    patterns = []
    for raw in in_cfg.get("block_patterns") or []:
        try:
            patterns.append(re.compile(str(raw), re.IGNORECASE))
        except re.error:
            logger.warning("guardrails.input.block_patterns: invalid regex skipped")
    if patterns:
        def blocked_pattern(text: str) -> GuardrailResult | None:
            for pattern in patterns:
                if pattern.search(text or ""):
                    return GuardrailResult(True, "the message matches a blocked pattern in config.yaml",
                                           "blocked_pattern")
            return None
        guardrails.register_input(blocked_pattern, name="blocked_pattern")
        names.append("input:blocked_pattern")
    return names
