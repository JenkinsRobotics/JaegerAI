"""``python -m jaeger_ai.interfaces.hermes_webui_adapter`` — the runner's entry point.

This is not a re-export left behind by a move. It is the module path the
installed launchd agent invokes:

    ~/Library/LaunchAgents/com.jenkinsrobotics.jaeger-hermes-webui-adapter.plist
    ProgramArguments: python -m jaeger_ai.interfaces.hermes_webui_adapter
                      --host 127.0.0.1 --port 8791

so deleting it stops the Chat Runner on :8791 on every machine whose agent was
installed before the adapter moved under ``features/webui/adapter/``. The
argument parsing lives with the server (``prog="jaeger hermes-webui-adapter"``);
this file only names the entry point, which is what ``interfaces/`` is for.

``jaeger hermes-webui-adapter`` is the equivalent CLI verb. A regenerated plist
should prefer it; until every installed agent has been regenerated, this path
has to keep working.
"""
from jaeger_ai.features.webui.adapter.server import main

if __name__ == "__main__":
    raise SystemExit(main())
