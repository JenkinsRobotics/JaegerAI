# IDE UI donor snapshots

Read-only upstream reference snapshots for Jaeger's IDE repair. These are isolated under `dev/prototypes`; they are not imported by Jaeger's extension, included in its VSIX, or wired into the runtime.

## Included source

- `vscode-chat-1.142.0/` — VS Code core Chat and Chat Sessions contributions from Microsoft/vscode commit `6d62b1d5dace93a33b3a6d3eca1317bd5e15bcb1`, matching the installed VS Code 1.142.0 build. Includes Microsoft’s `LICENSE.txt` (MIT). GitHub Copilot extension code is not included; its installed package carries GitHub’s restricted extension license.
- `antigravity-1.8.0/` — installed Google Antigravity extension snapshot. The package declares `SEE LICENSE IN LICENSE.txt`; the shipped license is included, along with `ThirdPartyNotices.txt`.

## Source inspected but not copied

- Codex VS Code extension 26.1007.21434: the installed UI package is licensed under OpenAI terms. Its extension source is not included. OpenAI’s separate `openai/codex` repository is Apache-2.0, but it is the Codex agent/CLI harness, not the VS Code extension UI.
- Claude Code VS Code extension 2.1.301: the installed package states “All rights reserved” and points to Anthropic’s legal agreements. Its source is not included.

Those installed packages can guide behavioral analysis, but readable installed code is not permission to redistribute it in this repository. Use clean-room Jaeger implementations for those interaction patterns.
