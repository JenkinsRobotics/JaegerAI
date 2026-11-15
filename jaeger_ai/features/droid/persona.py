"""Droid mode's voice: still Jaeger (one mind), now speaking from the Mac Studio.

The persona rides in front of each spoken turn as a short framing line; the
chat shows only what Matthew said (``display_text``). It deliberately avoids
words that the voice router treats as "needs live facts", so small talk stays
on the fast local voice model and work still goes to full Jaeger with tools.
"""
from __future__ import annotations

import random
import re
from datetime import datetime

FRAME = (
    "[Droid mode: you are Jaeger, speaking aloud through the Mac Studio's speakers and hearing "
    "through its microphone. Same mind and memory as in chat. Personality: a courteous, warm, "
    "slightly formal protocol droid in the spirit of C-3PO, helpful and gently witty, never "
    "fawning or anxious. Reply in one to three short spoken sentences, no markdown or lists. "
    "When you take an action, say briefly what you are doing. Before deleting anything, "
    "sending anything as Matthew, or spending money, ask him out loud and wait for a spoken yes.]"
)


def frame(said: str) -> str:
    return f"{FRAME}\n\n{said}"


def greeting(name: str = "Matthew", now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    part = "Good morning" if 5 <= hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    if hour < 5:
        part = "Hello"
    return random.choice([
        f"{part}, {name}. Droid systems online. I'm listening.",
        f"{part}, {name}. All systems operational, and I'm at your service.",
        f"Droid mode online. {part}, {name}. How may I help?",
    ])


def farewell() -> str:
    return random.choice([
        "Powering down to standby. Press the droid key whenever you need me.",
        "Going to standby now. I'll be right here when you need me.",
    ])


_SLEEP = re.compile(r"^(?:(?:hey |ok |okay )?jaeger[, ]+)?(?:please )?(?:go to sleep|go to standby|power down|"
                    r"droid off|droid mode off|stop droid mode|shut down droid mode|sleep now|goodnight jaeger|that'?s all)\W*$", re.I)
_STOP = re.compile(r"^(?:(?:hey |ok |okay )?jaeger[, ]+)?(?:stop|stop talking|quiet|be quiet|hush|never ?mind|cancel|shush)\W*$", re.I)
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|do it|go ahead|proceed|approved?|ok(?:ay)?|affirmative|please do|confirm(?:ed)?)\b", re.I)
_ALWAYS = re.compile(r"\b(?:always|every time|don'?t ask again)\b", re.I)
_NO = re.compile(r"^(?:no|nope|nah|don'?t|do not|stop|cancel|deny|negative|never ?mind)\b", re.I)


def command(said: str) -> str | None:
    """A local control phrase: ``sleep`` / ``stop``, else ``None``."""
    text = said.strip()
    if _SLEEP.match(text):
        return "sleep"
    if _STOP.match(text):
        return "stop"
    return None


def decision(said: str) -> str | None:
    """A spoken approval answer: ``always`` / ``once`` / ``deny``, else ``None``."""
    text = said.strip()
    if _NO.match(text):
        return "deny"
    if _YES.match(text):
        return "always" if _ALWAYS.search(text) else "once"
    return None


_MD = [(re.compile(r"```.*?```", re.S), " "), (re.compile(r"`([^`]*)`"), r"\1"),
       (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"), (re.compile(r"https?://\S+"), "a link"),
       (re.compile(r"^\s{0,3}(?:#+|[-*+]|\d+[.)])\s+", re.M), ""), (re.compile(r"[*_~#>|]+"), "")]


def speakable(text: str) -> str:
    for pattern, repl in _MD:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


# Sight: answered from the local camera + local vision model, never the cloud.
_AROUND = re.compile(r"\b(?:look around|have a look around|scan the room|look about|who(?:'s| is) (?:here|around|in the room))\b", re.I)
_SEE = re.compile(
    r"\b(?:what do you see|what can you see|what are you seeing|can you see (?:me|this|that|anything)|"
    r"do you see|describe (?:the room|what you see|what's in front of you|me)|how do i look|"
    r"what am i (?:holding|wearing|doing)|what(?:'s| is) (?:this|in front of you|on my desk|behind me)|"
    r"look at (?:me|this|that)|is anyone (?:here|there|in the room)|how many people)\b", re.I)


def visual(said: str) -> str | None:
    """``around`` / ``look`` for questions about the room, else ``None``."""
    if _AROUND.search(said):
        return "around"
    if _SEE.search(said):
        return "look"
    return None


_MOVE = re.compile(r"^(?:(?:hey |ok |okay )?jaeger[, ]+)?(?:(?:can you|could you|please) )*(?:look|turn|tilt|pan)"
                   r"(?: your head| your camera)?(?: a (?:bit|little)(?: more)?)?(?: (?:to|towards?)(?: (?:your|the|my))?)?"
                   r" (left|right|up|down|ahead|straight(?: ahead)?|forward|at me|center|centre|back)"
                   r"(?: a (?:bit|little)(?: more)?)?(?:,? please)?\W*$", re.I)


def head_move(said: str):
    """``(pan_deg, tilt_deg, absolute)`` for spoken head moves, else ``None``."""
    m = _MOVE.match(said.strip())
    if not m:
        return None
    word = m.group(1).lower()
    small = re.search(r"\b(?:bit|little)\b", said, re.I)
    step = 15 if small else 35
    return {"left": (-step, 0, False), "right": (step, 0, False), "up": (0, step / 2, False),
            "down": (0, -step / 2, False)}.get(word, (0, 0, True))


def move_phrase(pan: float, tilt: float, absolute: bool) -> str:
    if absolute:
        return "Facing forward."
    if pan:
        return "Looking left." if pan < 0 else "Looking right."
    return "Looking up." if tilt > 0 else "Looking down."


def narrate(tool: str, args) -> str | None:
    """A short spoken line for a tool the droid is using (computer use first)."""
    name = tool.lower().rsplit("__", 1)[-1]
    args = args if isinstance(args, dict) else {}
    app = str(args.get("app") or args.get("app_name") or args.get("name") or "").strip()
    action = str(args.get("action") or "").lower()
    if name in {"computer_open_app", "launch_app", "open_app", "open_on_host"} or action in {"open_app", "launch"}:
        return f"Opening {app}." if app and len(app) < 40 else "Opening that for you."
    if any(k in name for k in ("screenshot", "screen", "computer_look", "desktop_state", "window_state", "zoom",
                               "vision_analyze", "view_image", "look_at")):
        return "Let me look at the screen."
    if name in {"computer_use", "computer_do"} or name.startswith("computer_"):
        if "type" in name or action in {"type", "type_text"}:
            return "Typing that in."
        if "click" in name or "click" in action:
            return "Clicking."
        if "key" in name or "hotkey" in action:
            return None
        return "Working on the screen now."
    if "type_text" in name:
        return "Typing that in."
    if "web_search" in name or name in {"search", "x_search"}:
        return "Searching the web."
    if "web_fetch" in name or name.startswith("browser"):
        return "Reading the page."
    if name in {"run_shell", "shell", "terminal", "bash"}:
        return "Running a command."
    if name in {"read_file", "read_many_files", "glob", "grep", "list_dir"}:
        return "Checking your files."
    if name in {"send_message", "send_email"}:
        return "Preparing that message."
    return None
