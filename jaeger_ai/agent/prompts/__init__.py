"""System-prompt assembly — the Core bucket of the prompt split.

Public surface (prefer these imports in new code):

    from jaeger_os.agent.prompts import (
        assemble_prompt,        # single entry point, mode-dispatched
        build_system_prompt,    # back-compat shim ⇒ assemble_prompt(mode='agent')
        AUTO_BOARD_PROMPT,      # synthetic user message: idle board pickup
        deep_think_directive,   # synthetic user message: DT task framing
        cron_prompt,            # synthetic user message: scheduled prompts
    )

Layout:

    rules.py           — behavioural string constants
    context_blocks.py  — dynamic blocks reading live state
    assemble.py        — single assemble_prompt() entry
    synthetic.py       — mid-conversation user-role messages
    prompts.py         — back-compat shim for legacy imports

Safety lives in ``core/safety``; instance-specific text lives in
``instance/<name>/`` files (identity.yaml, soul.md, config.yaml).
"""

from .assemble import PromptMode, assemble_prompt
from .prompts import build_system_prompt
from .synthetic import AUTO_BOARD_PROMPT, cron_prompt, deep_think_directive

__all__ = [
    "AUTO_BOARD_PROMPT",
    "PromptMode",
    "assemble_prompt",
    "build_system_prompt",
    "cron_prompt",
    "deep_think_directive",
]
