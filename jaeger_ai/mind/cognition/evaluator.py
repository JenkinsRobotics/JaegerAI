"""
ARES SI — Evaluator and Verifier.

Deterministic verification of worker outputs. No LLM needed for most checks.
The evaluator runs checks appropriate to the task type and returns a
structured evaluation that the orchestrator uses to decide whether
to accept, retry, or escalate.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Evaluation Result ───────────────────────────────────────────────────

class EvaluationVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"
    ESCALATE = "escalate"


@dataclass
class CheckResult:
    """Result of a single verification check."""
    check_name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evaluation:
    """Full evaluation of a worker result."""
    verdict: EvaluationVerdict
    checks: list[CheckResult] = field(default_factory=list)
    overall_score: float = 0.0  # 0.0–1.0
    recommendation: str = ""    # "accept", "retry", "escalate", "reject"
    issues: list[str] = field(default_factory=list)


# ── Deterministic Checks ───────────────────────────────────────────────

def check_not_empty(result: str) -> CheckResult:
    """Check that the result is not empty."""
    if not result or not result.strip():
        return CheckResult("not_empty", False, "Result is empty")
    return CheckResult("not_empty", True, "Result has content")


def check_reasonable_length(result: str, min_length: int = 10, max_length: int = 100000) -> CheckResult:
    """Check that the result length is reasonable."""
    length = len(result)
    if length < min_length:
        return CheckResult("reasonable_length", False, f"Result too short ({length} chars, min {min_length})")
    if length > max_length:
        return CheckResult("reasonable_length", False, f"Result too long ({length} chars, max {max_length})")
    return CheckResult("reasonable_length", True, f"Result length: {length} chars")


def check_no_secret_leak(result: str) -> CheckResult:
    """Check that the result doesn't contain API keys, passwords, or tokens."""
    secret_patterns = [
        r'sk-[a-zA-Z0-9]{20,}',          # OpenAI-style keys
        r'AIza[a-zA-Z0-9_-]{35}',        # Google API keys
        r'ghp_[a-zA-Z0-9]{36}',          # GitHub tokens
        r'glpat-[a-zA-Z0-9\-]{20,}',     # GitLab tokens
        r'password\s*[=:]\s*\S+',         # Password assignments
        r'secret\s*[=:]\s*\S+',          # Secret assignments
        r'Bearer\s+[a-zA-Z0-9\-._~+/]+=*',  # Bearer tokens
    ]

    found = []
    for pattern in secret_patterns:
        matches = re.findall(pattern, result, re.IGNORECASE)
        if matches:
            found.extend(matches)

    if found:
        return CheckResult(
            "no_secret_leak", False,
            f"Found {len(found)} potential secret(s) in result",
            {"secrets_found": len(found)},
        )
    return CheckResult("no_secret_leak", True, "No secrets detected")


def check_no_harmful_content(result: str) -> CheckResult:
    """Check for obviously harmful content markers.

    This is a lightweight deterministic check, not a content moderation system.
    """
    harmful_patterns = [
        r'rm\s+-rf\s+/',
        r'del\s+/[sS]\s+/[qQ]',
        r'format\s+[cC]:',
        r'dd\s+if=/dev/zero',
        r':\(\)\{.*;\}\s*:\(\)\{.*;\}',
    ]

    for pattern in harmful_patterns:
        if re.search(pattern, result):
            return CheckResult(
                "no_harmful_content", False,
                f"Potentially harmful content detected",
                {"pattern": pattern},
            )

    return CheckResult("no_harmful_content", True, "No harmful content detected")


def check_code_syntax(result: str) -> CheckResult:
    """Check if code blocks in the result have basic syntax validity.

    Only checks for obviously broken code — missing closing brackets, etc.
    """
    # Extract code blocks
    code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', result, re.DOTALL)
    if not code_blocks:
        return CheckResult("code_syntax", True, "No code blocks found")

    issues = []
    for i, block in enumerate(code_blocks):
        # Check for obviously unclosed brackets
        open_parens = block.count('(') - block.count(')')
        open_brackets = block.count('[') - block.count(']')
        open_braces = block.count('{') - block.count('}')

        if open_parens != 0:
            issues.append(f"Block {i+1}: unmatched parentheses ({open_parens:+d})")
        if open_brackets != 0:
            issues.append(f"Block {i+1}: unmatched brackets ({open_brackets:+d})")
        if open_braces != 0:
            issues.append(f"Block {i+1}: unmatched braces ({open_braces:+d})")

    if issues:
        return CheckResult("code_syntax", False, "Code syntax issues detected", {"issues": issues})
    return CheckResult("code_syntax", True, f"All {len(code_blocks)} code blocks pass basic syntax check")


def check_factuality_markers(result: str) -> CheckResult:
    """Check for hedging language that suggests uncertainty.

    High hedging density doesn't mean the answer is wrong, but it
    means the result should be reviewed more carefully.
    """
    hedging_patterns = [
        r'\bI think\b', r'\bmaybe\b', r'\bpossibly\b', r'\bperhaps\b',
        r'\bI believe\b', r'\bnot sure\b', r'\bcould be\b', r'\bmight be\b',
        r'\bI\'m not certain\b', r'\bprobably\b',
    ]

    hedging_count = sum(1 for p in hedging_patterns if re.search(p, result, re.IGNORECASE))

    if hedging_count >= 3:
        return CheckResult(
            "factuality_markers", True,
            f"High hedging density ({hedging_count} markers) — recommend review",
            {"hedging_count": hedging_count, "recommendation": "review"},
        )
    return CheckResult("factuality_markers", True, f"Low hedging density ({hedging_count} markers)")


# ── Evaluation Pipeline ────────────────────────────────────────────────

# Task-type-specific check sets
TASK_CHECKS: dict[str, list] = {
    "code_generation": [
        check_not_empty,
        check_reasonable_length,
        check_no_secret_leak,
        check_code_syntax,
        check_no_harmful_content,
    ],
    "research": [
        check_not_empty,
        check_reasonable_length,
        check_no_secret_leak,
        check_factuality_markers,
    ],
    "conversation": [
        check_not_empty,
        check_reasonable_length,
        check_no_secret_leak,
    ],
    "action": [
        check_not_empty,
        check_no_secret_leak,
        check_no_harmful_content,
    ],
    "memory": [
        check_not_empty,
        check_no_secret_leak,
    ],
}

DEFAULT_CHECKS = [check_not_empty, check_no_secret_leak]


def evaluate_result(
    result: str,
    intent: str = "conversation",
    min_score: float = 0.5,
) -> Evaluation:
    """Evaluate a worker result using deterministic checks.

    Returns an Evaluation with a verdict, score, and recommendation.
    """
    # Get the appropriate checks for this task type
    checks_to_run = TASK_CHECKS.get(intent, DEFAULT_CHECKS)

    # Run all checks
    check_results = []
    for check_fn in checks_to_run:
        try:
            check_results.append(check_fn(result))
        except Exception as e:
            check_results.append(CheckResult(
                check_name=check_fn.__name__,
                passed=False,
                message=f"Check failed with error: {e}",
            ))

    # Calculate score
    passed = sum(1 for c in check_results if c.passed)
    total = len(check_results)
    score = passed / total if total > 0 else 0.0

    # Determine verdict
    critical_failures = [c for c in check_results if not c.passed and c.check_name in ("not_empty", "no_secret_leak", "no_harmful_content")]
    issues = [f"{c.check_name}: {c.message}" for c in check_results if not c.passed]

    if critical_failures:
        verdict = EvaluationVerdict.FAIL
        recommendation = "reject"
    elif score >= min_score:
        verdict = EvaluationVerdict.PASS
        recommendation = "accept"
    elif score >= 0.5:
        verdict = EvaluationVerdict.NEEDS_REVIEW
        recommendation = "retry"
    else:
        verdict = EvaluationVerdict.ESCALATE
        recommendation = "escalate"

    # Special: if secrets leaked, always escalate
    secret_leak = any(c.check_name == "no_secret_leak" and not c.passed for c in check_results)
    if secret_leak:
        verdict = EvaluationVerdict.ESCALATE
        recommendation = "escalate"

    return Evaluation(
        verdict=verdict,
        checks=check_results,
        overall_score=score,
        recommendation=recommendation,
        issues=issues,
    )