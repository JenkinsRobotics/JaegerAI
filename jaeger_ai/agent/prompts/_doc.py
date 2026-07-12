"""Load a prompt document (``.md``) for inclusion in the system prompt.

Framework prompt text lives in versioned ``.md`` files next to this
module (``framework_agent.md``, ``three_laws.md``) rather than as Python
string constants, so the operator can read and edit them directly and
``jaeger prompt show`` can cite a real file path.

HTML comments (``<!-- … -->``) are maintainer notes — they are stripped
here so they never reach the model. A missing file returns ``""`` rather
than raising: a prompt doc that fails to load must never crash the boot.
"""

from __future__ import annotations

import re
from pathlib import Path

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def load_prompt_doc(path: Path | str) -> str:
    """Read ``path``, strip HTML comments, and return the trimmed body.

    Returns ``""`` if the file is missing or unreadable.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return _HTML_COMMENT.sub("", raw).strip()


__all__ = ["load_prompt_doc"]
