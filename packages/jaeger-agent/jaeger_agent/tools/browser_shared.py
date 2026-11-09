"""Adapter to the owning conversation's visible browser. No second browser."""
import base64
from pathlib import Path
import tempfile
from urllib.parse import quote

from .call_agent import _request_json


def shared_browser(context, action, args):
    aliases = {"open": "navigate", "goto": "navigate", "read": "snapshot", "look": "snapshot",
               "elements": "snapshot", "capture": "screenshot", "extract_text": "content", "text": "content",
               "logs": "errors", "console": "errors", "fill": "type", "enter": "type", "key": "press",
               "quit": "stop", "shutdown": "stop", "close": "stop"}
    action = aliases.get(action, action)
    # Only the admitted task context supplies identity; ignore model-supplied session IDs.
    path = f"/v1/sessions/{quote(context['session_id'], safe='')}/browser/action"
    allowed = {k: v for k, v in args.items() if k in {"url", "element", "text", "direction", "key", "full_page"}}
    status, result = _request_json("POST", path, {"action": action, "snapshot": True, **allowed}, timeout=105)
    if status >= 400:
        return {"ok": False, **result}
    if action == "screenshot" and result.get("image_data"):
        data = base64.b64decode(result["image_data"])
        destination = args.get("path")
        if destination:
            output = Path(destination).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        else:
            with tempfile.NamedTemporaryFile(prefix="jaeger-browser-", suffix=".png", delete=False) as handle:
                handle.write(data)
                output = Path(handle.name)
        result.update(path=str(output), bytes=len(data))
    return {"ok": True, **result}
