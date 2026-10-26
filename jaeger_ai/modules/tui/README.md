# tui — monolith break-out module (split plan, NOT yet cut)

Original files: jaeger_ai/interfaces/tui/app.py (104,161 bytes) + slash_commands.py (104,769 bytes). The TUI folder is already a folder, but these two files are each a monolith inside it. Other TUI files are already small: voice_session.py (23,144), picker.py (14,830), status.py (11,390), board_view, ptk_input, completion, banner, theme, singleton.

Proposed split, lowest risk of the monoliths — good first actual cut when code-run is available:
- tui-app — app loop, views, status, board view.
- tui-commands — slash commands by group (session, workspace, voice, diagnostics), not one 104KB file.
- tui-input — ptk_input + completion, already small, leave alone.

Run: jaeger --tui / jaeger dev. Test: start TUI, run one slash command from each group, check voice session, picker, and status still work, after each split group.

Overlap with jaeger-agent: TUI is a JaegerAI client, like ide-client and menubar-shell. Do NOT copy jaeger-agent's loop into it, and do NOT edit jaeger-agent.
