"""Hygiene for background maintenance prompts that may go to a cloud model.

Does not change the privacy classifier. Owner and instance absolute paths
are replaced with short labels, and instructional trigger phrases in
injected recipes (for example "never upload" or "Never store secrets")
are reworded so skill reviews, cron jobs, memory nudges, and the nightly
pass can run without tripping the local-only gate on their own templates.
"""
from __future__ import annotations

import re
from pathlib import Path

# Keep labels short and path-like so the model can still talk about "the
# instance skills dir" without a concrete filesystem location.
_HOME_USERS = re.compile(r"(?i)(?:file://)?/Users/[^/\s\"']+")
_HOME_UNIX = re.compile(r"(?i)(?:file://)?/home/[^/\s\"']+")
_PRIVATE_TMP = re.compile(r"(?i)/private/tmp/")
_FILE_HOME = re.compile(r"(?i)file://(?=<home>|<state>|<instance>)")


def _add_root(roots: list[tuple[str, str]], path: Path | str | None, label: str) -> None:
    if not path:
        return
    raw = str(path).strip()
    if not raw:
        return
    candidates = [Path(raw)]
    try:
        candidates.append(Path(raw).expanduser())
    except Exception:
        pass
    try:
        candidates.append(Path(raw).expanduser().resolve())
    except Exception:
        pass
    skip = {"", "/", "/Users", "/home", "/private", "/private/tmp", "/tmp"}
    seen = {p for p, _ in roots}
    for cand in candidates:
        text = str(cand).rstrip("/")
        if not text or text in skip or text in seen:
            continue
        roots.append((text, label))
        seen.add(text)
        # macOS often exposes the same tree under /private.
        if text.startswith("/private/"):
            alt = text[len("/private"):]
            if alt not in skip and alt not in seen:
                roots.append((alt, label))
                seen.add(alt)
        elif text.startswith("/") and not text.startswith("/private/"):
            alt = "/private" + text
            if alt not in seen:
                roots.append((alt, label))
                seen.add(alt)


def local_path_roots() -> list[tuple[str, str]]:
    """Longest-first ``(absolute path, label)`` replacements for this machine."""
    roots: list[tuple[str, str]] = []
    home = Path.home()
    _add_root(roots, home, "<home>")
    try:
        from jaeger_ai.core.instance.instance import operator_state_root, resolve_instance_dir
        state = operator_state_root()
        instance = resolve_instance_dir()
        _add_root(roots, state, "<state>")
        _add_root(roots, instance, "<instance>")
    except Exception:  # noqa: BLE001 — still redact the usual state dir
        _add_root(roots, home / ".jaeger", "<state>")
        _add_root(roots, home / ".jaeger" / "instances" / "jaeger", "<instance>")
    roots.sort(key=lambda item: len(item[0]), reverse=True)
    return roots


def redact_local_paths(text: str) -> str:
    """Replace home, state, and instance absolute paths with short labels."""
    if not text:
        return text
    out = text
    for path, label in local_path_roots():
        if path in out:
            out = out.replace(path, label)
        # Common ~ writing of the same locations.
        home = str(Path.home()).rstrip("/")
        if path.startswith(home + "/"):
            tilde = "~/" + path[len(home) + 1:]
            if tilde in out:
                out = out.replace(tilde, label)
        elif path == home and "~" in out:
            # Only bare ~/ or a ~ path, not email-like tokens.
            out = re.sub(r"(?<![\w.])~(?=/|$)", "<home>", out)
    out = _HOME_USERS.sub("<home>", out)
    out = _HOME_UNIX.sub("<home>", out)
    out = _PRIVATE_TMP.sub("/tmp/", out)
    return out


def excerpt_for_maintenance(text: str, cap: int = 800) -> str:
    """Redacted, length-capped excerpt of an owner turn for a maintenance prompt."""
    body = " ".join(redact_local_paths(str(text or "")).split())
    if not body:
        return "(empty)"
    if len(body) > cap:
        return body[: cap - 1].rstrip() + "…"
    return body


# Instructional phrases that recipes use as safety advice, which the
# unchanged classifier treats as an explicit privacy request or a
# credential-supply pattern. Rewrites are only applied to injected
# playbooks and other framework text, never to the owner's own message.
_TRIGGER_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bnever store secrets\b", re.I), "Do not save credentials or personal data"),
    (re.compile(r"\bstore secrets\b", re.I), "save credentials"),
    (re.compile(r"credentials store and OS secret files", re.I), "credentials vault and OS credential files"),
    (re.compile(r"\bnever upload targets anywhere\b", re.I), "keep targets on this machine only"),
    (re.compile(r"\b(?:do not|don't|never) upload\b", re.I), "keep on this machine"),
    (re.compile(r"\b(?:do not|don't|never) send\b", re.I), "do not transmit"),
    (re.compile(r"\b(?:do not|don't|never) share\b", re.I), "do not circulate"),
    (re.compile(r"\b(?:do not|don't|never) reveal\b", re.I), "do not disclose"),
    (re.compile(r"~/.ssh"), "<ssh-dir>"),
    (re.compile(r"\bid_rsa\b"), "<ssh-key>"),
)

# Demo assignments in recipes ("export API_KEY=...", "password is ...")
# match the classifier's credential-supply pattern even when they are
# placeholders. Replace the whole clause so the instruction remains and
# the assignment form does not.
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?:(?:my|our)\s+)?(?:password|secret|api[ _]?key|token)\s*(?:is\s+|[=:])\s*\S+"
)


def sanitize_injected_text(text: str) -> str:
    """Redact local paths and reword instructional trigger phrases.

    Use this on auto-injected playbooks and other framework-owned text
    that will be classified as part of a cloud-bound user message. Do
    not run it on the owner's own request: a real privacy ask must
    still trip the local-only gate.
    """
    out = redact_local_paths(str(text or ""))
    for pattern, replacement in _TRIGGER_PHRASES:
        out = pattern.sub(replacement, out)
    out = _CREDENTIAL_ASSIGNMENT.sub("a credential from the environment", out)
    return out
