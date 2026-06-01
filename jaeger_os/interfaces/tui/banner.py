"""ASCII banner for the Jaeger-OS TUI.

Hand-rolled — figlet would add a dep + a render at boot; baking the
art in the source is faster and gives us per-instance customizability
(e.g. dimmer banner for a sub-instance, brighter for production).

Banner is rendered via Rich in :mod:`.app` so the colors mesh with
the rest of the TUI.
"""

from __future__ import annotations


# Block letters for "JAEGER-OS" — 7 rows. Designed to fit in
# ≤80 columns so it doesn't wrap on a default terminal.
JAEGER_ASCII = r"""
     ██╗ █████╗ ███████╗ ██████╗ ███████╗██████╗       ██████╗ ███████╗
     ██║██╔══██╗██╔════╝██╔════╝ ██╔════╝██╔══██╗     ██╔═══██╗██╔════╝
     ██║███████║█████╗  ██║  ███╗█████╗  ██████╔╝     ██║   ██║███████╗
██   ██║██╔══██║██╔══╝  ██║   ██║██╔══╝  ██╔══██╗     ██║   ██║╚════██║
╚█████╔╝██║  ██║███████╗╚██████╔╝███████╗██║  ██║ ██╗ ╚██████╔╝███████║
 ╚════╝ ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝ ╚═╝  ╚═════╝ ╚══════╝
""".strip("\n")


# POLISH-1: dropped "pydantic-ai core" — the agent loop has been
# framework-free since Phase 9 (see core/loop/jaeger_agent.py). The
# tagline is the user-facing label, not the architecture, so it now
# names the loop generation instead of the framework.
TAGLINE = "✦  real-world local agentic agent framework  ·  framework-free Phase-9 loop  ✦"
