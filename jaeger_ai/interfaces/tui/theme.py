"""TUI theme — the Jaeger-OS accent colour.

hermes-agent's reference TUI is amber/gold; Jaeger-OS shifts the same
shade family to **blue** for its own identity. Every piece of brand
chrome — the banner, turn rules, the answer box, the ``❯`` prompt, the
status bar — draws in :data:`ACCENT`.

We use a 24-bit hex (``#3aa0ff``) rather than the 16-colour name
``bright_blue`` because the ANSI-name path renders DIFFERENTLY in
different terminals: VS Code's terminal shows a clean azure, but
Terminal.app's default profile maps ``bright_blue`` to a purple-ish
shade. Truecolor bypasses the per-terminal mapping and Rich/
prompt_toolkit both render the exact pixel value, so the brand looks
the same in every host.

Semantic colours are deliberately *not* themed: ``yellow`` stays
warning, ``red`` stays error, ``green`` stays success, ``cyan`` stays
the secondary highlight. Only the brand accent moves.
"""

from __future__ import annotations

# 24-bit hex for the brand accent — identical pixel value in every
# truecolor terminal.
_ACCENT_HEX = "#3aa0ff"

# Rich style strings for the brand accent.
ACCENT = _ACCENT_HEX
ACCENT_BOLD = f"bold {_ACCENT_HEX}"
ACCENT_DIM = f"dim {_ACCENT_HEX}"

# prompt_toolkit style token for the same accent (used in the prompt).
# prompt_toolkit accepts hex inline in the style string.
ACCENT_PTK = _ACCENT_HEX
