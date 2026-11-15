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
