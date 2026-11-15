"""Hygiene for background maintenance prompts that may go to a cloud model.

Does not change the privacy classifier. Owner and instance absolute paths
are replaced with short labels so skill reviews, memory nudges, and the
nightly pass can run without sending a home-directory map off-device.
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
