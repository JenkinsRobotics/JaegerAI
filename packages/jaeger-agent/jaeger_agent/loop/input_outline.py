"""Content-free observations of the formatted adapter input, never prompt logging."""
from __future__ import annotations


def input_outline(payload):
    """Known payload shapes only. Counts are not token usage or provider acceptance.

    Never stringify arbitrary objects or persist model names, tool schemas, text,
    attachment bytes, thinking, headers, keys or hashes of private content.
    """
    result = {"shape": "unsupported", "messages": [], "system_chars": 0,
              "tool_count": 0, "truncated": False}
    if not isinstance(payload, dict):
        return result
    tools = payload.get("tools")
    if isinstance(tools, list):
        result["tool_count"] = len(tools)
    system = payload.get("system")
    if isinstance(system, str):
        result["system_chars"] = len(system)
    elif isinstance(system, list):
        result["system_chars"] = sum(len(p["text"]) for p in system[:2048]
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str))
        result["truncated"] = len(system) > 2048
    messages = payload.get("messages")
    if isinstance(messages, list):
        result["shape"] = "messages"
        result["truncated"] |= len(messages) > 2048
        for message in messages[:2048]:
            if not isinstance(message, dict):
                result["truncated"] = True
                continue
            role = message.get("role")
            role = role if role in ("system", "developer", "user", "assistant", "tool", "function") else "other"
            content = message.get("content")
            images = message.get("images")
            chars, omitted = 0, len(images) if isinstance(images, list) else 0
            if isinstance(content, str):
                chars = len(content)
            elif isinstance(content, list):
                result["truncated"] |= len(content) > 2048
                for part in content[:2048]:
                    if isinstance(part, dict) and part.get("type") in ("text", "input_text", "output_text") and isinstance(part.get("text"), str):
                        chars += len(part["text"])
                    else:
                        omitted += 1
            result["messages"].append({"role": role, "text_chars": chars, "omitted_blocks": omitted})
    elif isinstance(payload.get("prompt"), str):
        result["shape"] = "prompt"
        result["messages"] = [{"role": "other", "text_chars": len(payload["prompt"]), "omitted_blocks": 0}]
    return result
