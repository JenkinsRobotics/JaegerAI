"""The REAL boot-path registration test.

0.9.3 shipped with send_email implemented, unit-tested — and never imported
by `jaeger_ai.agent.tools`, so production boots registered no email tool
while the evals (which import modules directly) passed. This test closes
that class: it imports EXACTLY what the app boot imports and asserts every
user-facing tool is live in the registry. If you add a tool module, its
name belongs in EXPECTED — and the import belongs in agent/tools/__init__.
"""
import jaeger_ai.agent.tools  # the production boot import — nothing else
from jaeger_os.core.tools.tool_registry import get_tools

EXPECTED = {
    # 0.9.3 everyday-agency additions (the class that regressed)
    "send_email", "move_file", "copy_file",
    "run_shortcut", "list_shortcuts", "spotlight_search",
    "get_events", "create_event", "lookup_contact",
    "clipboard_read", "clipboard_write", "notify",
    "system_control", "media_control", "now_playing", "ocr_file",
    # long-standing core spot-checks
    "open_on_host", "web_search", "send_message", "read_file",
}


def test_every_expected_tool_registers_via_the_real_boot_import():
    live = {t.name for t in get_tools()}
    missing = EXPECTED - live
    assert not missing, f"implemented but NOT registered at boot: {sorted(missing)}"
