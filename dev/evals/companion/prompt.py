"""promptfoo prompt function: the real companion system prompt for a character."""
import json

from jaeger_ai.features.personality.character import characters_root, load_character
from jaeger_ai.features.personality.companion import system_prompt


def build(context):
    v = context["vars"]
    char = load_character(characters_root() / v["character"])
    return json.dumps([{"role": "system", "content": system_prompt(char)},
                       {"role": "user", "content": v["message"]}])
