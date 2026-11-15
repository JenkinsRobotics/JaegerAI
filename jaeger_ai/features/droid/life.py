"""Droid Life: the living heartbeat of Jaeger's body (Tier 0 reflex + Tier 1 awareness).

While the droid is *present* (awake in the room during active hours, not in a
conversation) it watches at 2-5 fps with Apple Vision and listens with a VAD
only: nothing is recorded or transcribed. A blackboard holds what it knows
right now (who is here, are they facing it, is anyone talking); reflexes turn
the head toward people and sound, glance now and then, and look around when
alone. Drives (social, curiosity, energy, confidence) decay toward a baseline
and shape how often it moves and whether small talk is welcome.

Speaking unprompted is decided in code by ``Gate`` (never by a model), and
every decision, including "stayed quiet", is logged. "What I noticed" keeps
derived events only (no images, no audio), 7 days, deletable.

Halting (ReactiveFallback): Stream Deck STOP, "quiet", or Matthew speaking
stops idle motion and any unprompted line at once.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("jaeger.droid.life")
STATE = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")
HOME = STATE / "droid"
TRIGGERS = STATE / "run" / "reflect" / "triggers.jsonl"
KEEP_DAYS = 7
H_FOV, V_FOV = 72.0, 42.0            # Insta360 Link 2 at 16:9, degrees (approximate)

# Value of an unprompted line (higher wins; small talk is the lowest).
VALUE = {"approval": 4, "follow_up": 3, "job_done": 2, "greeting": 2, "check_in": 2, "info": 2, "small_talk": 1}


def active_hours(cfg: dict) -> tuple[int, int]:
    hours = cfg.get("active_hours") or [9, 23]
    return int(hours[0]), int(hours[1])


def in_active_hours(cfg: dict, now: datetime | None = None) -> bool:
    start, end = active_hours(cfg)
    hour = (now or datetime.now()).hour
    return start <= hour < end


def next_morning(cfg: dict, now: datetime | None = None) -> float:
    """Epoch seconds of the next active-hours start."""
    now = now or datetime.now()
    start, _ = active_hours(cfg)
    morning = now.replace(hour=start, minute=0, second=0, microsecond=0)
    if morning <= now:
        morning += timedelta(days=1)
    return morning.timestamp()


# ── logs (derived events only) ────────────────────────────────────────
class JsonlLog:
    def __init__(self, path: Path, keep_days: int = KEEP_DAYS):
        self.path, self.keep = path, keep_days
        self.lock = threading.Lock()
        self.pruned = 0.0

    def append(self, kind: str, **fields) -> dict:
        row = {"id": uuid.uuid4().hex[:10], "at": round(time.time(), 2), "kind": kind, **fields}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            new = not self.path.exists()
            with self.path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            if new:
                self.path.chmod(0o600)
        if time.time() - self.pruned > 3600:
            self.prune()
        return row

    def rows(self) -> list[dict]:
        try:
            lines = self.path.read_text().splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def recent(self, limit: int = 200) -> list[dict]:
        return list(reversed(self.rows()[-limit:]))

    def _rewrite(self, rows: list[dict]):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def prune(self):
        cutoff = time.time() - self.keep * 86400
        with self.lock:
            rows = self.rows()
            kept = [r for r in rows if float(r.get("at") or 0) >= cutoff]
            if len(kept) != len(rows):
                self._rewrite(kept)
            self.pruned = time.time()

    def delete(self, row_id: str | None = None) -> int:
        """Delete one entry, or everything when ``row_id`` is None."""
        with self.lock:
            rows = self.rows()
            kept = [] if row_id is None else [r for r in rows if r.get("id") != row_id]
            if self.path.exists():
                self._rewrite(kept)
        return len(rows) - len(kept)


# ── drives ────────────────────────────────────────────────────────────
class Drives:
    """Vector-style internal state in [0, 1], decaying toward time-of-day baselines."""

    NAMES = ("social", "curiosity", "energy", "confidence")

    def __init__(self, path: Path = HOME / "drives.json"):
        self.path = path
        self.values = {"social": 0.4, "curiosity": 0.4, "energy": 0.6, "confidence": 0.6}
        try:
            saved = json.loads(path.read_text())
            self.values.update({k: float(v) for k, v in saved.get("values", {}).items() if k in self.NAMES})
        except (OSError, ValueError):
            pass
        self.saved = 0.0

    @staticmethod
    def baseline(now: datetime | None = None) -> dict:
        hour = (now or datetime.now()).hour + (now or datetime.now()).minute / 60
        energy = 0.45 + 0.3 * math.exp(-((hour - 11) ** 2) / 18) - (0.2 if hour >= 21 or hour < 7 else 0)
        return {"social": 0.35, "curiosity": 0.35, "energy": round(max(0.15, energy), 3), "confidence": 0.6}

    def tick(self, dt: float, *, alone: bool, engaged: bool, novel: bool):
        base = self.baseline()
        rate = 1 - math.exp(-dt / 1800)  # half-way back to baseline in ~20 min
        for name in self.NAMES:
            self.values[name] += (base[name] - self.values[name]) * rate
        minutes = dt / 60
        if alone:
            self.values["social"] += 0.02 * minutes
        if engaged:
            self.values["social"] -= 0.05 * minutes
        if novel:
            self.values["curiosity"] += 0.08
        self.clamp()
        if time.time() - self.saved > 60:
            self.save()

    def nudge(self, **deltas):
        for name, delta in deltas.items():
            if name in self.values:
                self.values[name] += delta
        self.clamp()

    def clamp(self):
        for name in self.NAMES:
            self.values[name] = round(min(1.0, max(0.0, self.values[name])), 4)

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.write_text(json.dumps({"values": self.values, "at": time.time()}))
            self.saved = time.time()
        except OSError:
            pass

    def mood(self) -> str:
        v = self.values
        if v["energy"] < 0.3:
            return "tired"
        if v["social"] > 0.7:
            return "sociable"
        if v["curiosity"] > 0.65:
            return "curious"
        if v["confidence"] < 0.4:
            return "unsure"
        return "bright" if v["energy"] > 0.6 else "calm"

    def tone(self) -> str:
        return {"tired": "Keep it very short and low-key; it is late.",
                "sociable": "Be warm; you have been alone a while.",
                "curious": "A touch of curiosity is welcome.",
                "unsure": "Be modest and careful.",
                "bright": "Be bright and brisk.",
                "calm": "Be calm and brief."}[self.mood()]


# ── speak-or-stay-quiet gate ─────────────────────────────────────────
class Gate:
    """Room-aware interruption policy (code, not model). Every call is logged."""

    def __init__(self, decisions: JsonlLog):
        self.log = decisions
        self.spoken: list[tuple[float, str]] = []   # (time, kind) of unprompted lines
        self.small_talk_day = ("", 0)
        self.ignored = 0
        self.awaiting_reply_until = 0.0
        self.awaiting_kind = ""
        self.last_small_talk = 0.0

    def _budget(self, now: float, kind: str) -> str | None:
        self.spoken = [s for s in self.spoken if now - s[0] < 3600]
        counted = [s for s in self.spoken]
        if len(counted) >= 4:
            return "hourly budget used (4 per hour)"
        gap_kinds = [s for s in counted if s[1] != "greeting"]
        if kind not in ("greeting", "approval") and gap_kinds and now - gap_kinds[-1][0] < 15 * 60:
            return "spoke less than 15 minutes ago"
        return None

    def decide(self, *, kind: str, private: bool, room: dict, drives: Drives | None = None,
               text: str = "", now: float | None = None) -> dict:
        now = now or time.time()
        value = VALUE.get(kind, 2)
        action, reason = self._decide(kind, value, private, room, drives, now)
        if action == "speak":
            self.spoken.append((now, kind))
            self.awaiting_reply_until, self.awaiting_kind = now + 60, kind
            if kind == "small_talk":
                self.last_small_talk = now
                day = datetime.now().strftime("%Y-%m-%d")
                self.small_talk_day = (day, (self.small_talk_day[1] if self.small_talk_day[0] == day else 0) + 1)
        self.log.append("decision", action=action, reason=reason, about=kind, value=value, private=private,
                        preview=(text[:60] + ("…" if len(text) > 60 else "")) if text and not private else None,
                        room={k: room.get(k) for k in ("owner_present", "owner_facing", "guests", "speech",
                                                        "mode", "active_hours", "quiet", "halted")})
        return {"action": action, "reason": reason}

    def _decide(self, kind, value, private, room, drives, now):
        away_action = "push" if value >= 2 else "quiet"
        if not room.get("active_hours"):
            return away_action, "outside active hours (phone instead)" if value >= 2 else "outside active hours"
        if not room.get("presence_on"):
            return away_action, "presence sensing is off" if value >= 2 else "presence sensing is off"
        if room.get("quiet"):
            return away_action, "quiet mode (asked to be quiet)"
        if room.get("halted"):
            return "quiet", "halted (STOP or Matthew speaking)"
        if not room.get("owner_present"):
            return away_action, "Matthew is away"
        if room.get("guests") and private:
            return "push" if value >= 2 else "quiet", "someone else is present; private content stays off the speaker"
        if room.get("mode") == "conversation" or room.get("busy"):
            return "quiet", "in a conversation or a turn is running"
        if room.get("speech"):
            return "quiet", "someone is talking"
        if value < 4 and not room.get("owner_facing"):
            return ("push" if value >= 3 else "quiet"), "Matthew is not facing me"
        over = self._budget(now, kind)
        if over:
            return ("push" if value >= 3 else "quiet"), over
        if kind == "small_talk":
            day = datetime.now().strftime("%Y-%m-%d")
            count = self.small_talk_day[1] if self.small_talk_day[0] == day else 0
            if count >= 2:
                return "quiet", "small talk limit reached today (2)"
            if self.ignored >= 2:
                return "quiet", "small talk ignored twice; backing off"
            last = self.last_small_talk
            if last and now - last < 3 * 3600 * (2 ** self.ignored):
                return "quiet", "small talk backoff"
            if drives and drives.values["social"] < 0.55:
                return "quiet", "social drive is low"
        return "speak", "present, facing and within budget"

    def small_talk_ready(self, drives: Drives, now: float | None = None) -> bool:
        """Cheap pre-check so idle small talk is only offered (and logged) when it could pass."""
        now = now or time.time()
        day = datetime.now().strftime("%Y-%m-%d")
        count = self.small_talk_day[1] if self.small_talk_day[0] == day else 0
        return (count < 2 and self.ignored < 2 and drives.values["social"] >= 0.6
                and now - self.last_small_talk >= 3 * 3600 * (2 ** self.ignored)
                and not any(now - t < 15 * 60 for t, _ in self.spoken))

    def heard_reply(self, now: float | None = None):
        if (now or time.time()) <= self.awaiting_reply_until:
            self.ignored = 0
            self.awaiting_reply_until = 0.0

    def check_ignored(self, now: float | None = None):
        now = now or time.time()
        if self.awaiting_reply_until and now > self.awaiting_reply_until:
            if self.awaiting_kind == "small_talk":
                self.ignored += 1
            self.awaiting_reply_until = 0.0


# ── the life loop ─────────────────────────────────────────────────────
class Life:
    def __init__(self, droid):
        self.droid = droid
        self.noticed = JsonlLog(HOME / "noticed.jsonl")
        self.decisions = JsonlLog(HOME / "decisions.jsonl")
        self.drives = Drives()
        self.gate = Gate(self.decisions)
        self.lock = threading.Lock()
        now = time.time()
        self.bb = {"people": 0, "faces": 0, "facing": False, "owner_visible": False, "owner_score": None,
                   "owner_seen_at": 0.0, "person_seen_at": 0.0, "absent_since": now, "owner_absent_since": now,
                   "guests": False, "speech": False, "speech_at": 0.0, "owner_speaking": False,
                   "halted_until": 0.0, "quiet_until": 0.0, "slept_until": 0.0, "fps": 0.0,
                   "target": None, "last_move_at": 0.0, "next_glance": now + 60, "next_look_around": now + 300,
                   "pan": 0.0, "tilt": 0.0, "vision_ms": None, "present_since": None}
        self.face_id = None
        self.voice_id = None
        self.ears = None
        self.stop = threading.Event()
        self.vision_thread: threading.Thread | None = None
        self.enrolling: dict | None = None
        self.last_noted: dict[str, float] = {}

    # ---- lifecycle -------------------------------------------------------
    def start_senses(self):
        """Called when the droid becomes present: start the vision loop."""
        from . import senses

        try:
            self.face_id = self.face_id or senses.FaceID()
        except Exception as exc:  # models missing: presence still works without identity
            log.warning("face id unavailable: %s", exc)
        try:
            self.voice_id = self.voice_id or senses.VoiceID()
        except Exception as exc:
            log.warning("voice id unavailable: %s", exc)
        try:
            self.ears = senses.Ears()
        except Exception as exc:
            log.warning("vad unavailable: %s", exc)
        self.stop.clear()
        if not self.vision_thread or not self.vision_thread.is_alive():
            self.vision_thread = threading.Thread(target=self._vision_loop, name="droid-life", daemon=True)
            self.vision_thread.start()
        self.bb["present_since"] = time.time()
        self.note("presence_on", "Camera and microphone on (low power, no recording)")

    def stop_senses(self, why: str = "standby"):
        self.stop.set()
        self.ears = None
        if self.bb.get("present_since"):
            self.note("presence_off", f"Camera and microphone off ({why})")
        self.bb.update(people=0, faces=0, facing=False, owner_visible=False, speech=False, present_since=None)

    def note(self, kind: str, text: str, *, every: float = 0.0, **fields):
        now = time.time()
        if every and now - self.last_noted.get(kind, 0) < every:
            return
        self.last_noted[kind] = now
        self.noticed.append(kind, text=text, **fields)

    # ---- room snapshot -----------------------------------------------------
    def room(self) -> dict:
        now = time.time()
        bb, cfg = self.bb, self.droid.cfg
        enrolled = self.face_id is not None and self.face_id.owner is not None
        if enrolled:
            owner_present = now - bb["owner_seen_at"] < 120
        else:  # no enrolment: anyone seen recently counts as Matthew (single household)
            owner_present = now - bb["person_seen_at"] < 120
        return {"active_hours": in_active_hours(cfg), "presence_on": bool(bb.get("present_since")),
                "owner_present": owner_present, "owner_facing": bb["facing"] and now - bb["person_seen_at"] < 20,
                "guests": bb["guests"], "speech": now - bb["speech_at"] < 8,
                "mode": self.droid.status.get("mode"), "busy": bool(self.droid.request_id or self.droid.pending_approval),
                "quiet": now < bb["quiet_until"], "halted": now < bb["halted_until"], "enrolled": enrolled}

    def snapshot(self) -> dict:
        from . import senses

        bb = dict(self.bb)
        bb.pop("target", None)
        return {"room": self.room(), "blackboard": bb, "drives": dict(self.drives.values), "mood": self.drives.mood(),
                "enrolled": senses.enrolled(), "enrolling": self.enrolling,
                "indicators": {"camera": self.droid.status.get("camera") == "live",
                               "microphone": bool(self.droid.audio and self.droid.status.get("ears", True)
                                                  and self.droid.status.get("awake")),
                               "transcribing": self.droid.status.get("mode") == "conversation"}}

    # ---- halting -------------------------------------------------------------
    def ears_busy(self) -> bool:
        return bool(self.ears is not None and self.ears.speaking)

    def halt(self, seconds: float, why: str):
        self.bb["halted_until"] = max(self.bb["halted_until"], time.time() + seconds)
        loop = self.droid.loop
        if self.droid.unprompted_speaking and loop is not None:
            loop.call_soon_threadsafe(self.droid.stop_talking)   # audio thread -> event loop
        self.note("halted", f"Stopped ({why})", every=30)

    def quiet(self, minutes: float):
        self.bb["quiet_until"] = time.time() + minutes * 60
        self.halt(10, "asked to be quiet")
        self.note("quiet", f"Quiet mode for {int(minutes)} min")

    def unquiet(self):
        self.bb["quiet_until"] = 0.0
        self.bb["halted_until"] = 0.0
        self.note("quiet_off", "Quiet mode off")

    # ---- unprompted speech -----------------------------------------------------
    def offer(self, text: str, kind: str = "info", private: bool = True) -> dict:
        """A line Jaeger wants to say unprompted: speak, phone, or stay quiet."""
        decision = self.gate.decide(kind=kind, private=private, room=self.room(), drives=self.drives, text=text)
        if decision["action"] == "speak":
            self.droid.say_unprompted(text)
        return decision

    # ---- ears (called from the audio thread) ------------------------------------
    def hear(self, block):
        ears = self.ears
        if ears is None or self.droid.status.get("muted"):
            return
        event, utterance = ears.feed(block)
        now = time.time()
        if event == "start":
            self.bb.update(speech=True, speech_at=now)
            owner_ish = self.bb["owner_visible"] or (self.face_id is None or self.face_id.owner is None) and self.bb["people"] <= 1
            if self.droid.unprompted_speaking or owner_ish:
                self.halt(6, "Matthew is speaking" if owner_ish else "someone is speaking")
            self.gate.heard_reply(now)
            self.note("speech_nearby", "Heard someone talking (not recorded)", every=300)
            self._orient_to_sound()
        elif ears.speaking:
            self.bb["speech_at"] = now
        if event == "end":
            self.bb["speech"] = False
            if utterance is not None:
                threading.Thread(target=self._voice_match, args=(utterance,), daemon=True).start()

    def _voice_match(self, utterance):
        if self.enrolling and self.enrolling.get("kind") == "voice":
            self._enrol_voice_sample(utterance)
            return
        if self.voice_id is None:
            return
        try:
            score = self.voice_id.owner_score(utterance)
        except Exception:
            return
        if score is None:
            return
        from .senses import VOICE_MATCH

        owner = score >= VOICE_MATCH
        self.bb["owner_speaking"] = owner
        if owner:
            self.bb["owner_seen_at"] = max(self.bb["owner_seen_at"], time.time() - 30)
        elif self.voice_id.owner is not None:
            self.bb["guests"] = True
            self.note("guest_voice", "Heard a voice that isn't Matthew's", every=600)

    # ---- vision loop (thread) ---------------------------------------------------------
    def _vision_loop(self):
        import cv2

        from . import senses

        last_id = 0.0
        last_tick = time.time()
        frames = 0
        fps_at = time.time()
        while not self.stop.is_set():
            energy = self.drives.values["energy"]
            period = 1 / (2 + 3 * energy)          # 2-5 fps, slower when tired
            started = time.time()
            eyes = self.droid.eyes
            frame = None
            if eyes is not None:
                with eyes.lock:
                    frame, at = eyes.frame, eyes.frame_at
                if frame is not None and started - at > 2:
                    frame = None
            if frame is not None:
                small = cv2.resize(frame, (640, 360))
                ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    t0 = time.time()
                    try:
                        seen = senses.detect(buf.tobytes())
                    except Exception as exc:
                        log.warning("vision detect failed: %s", exc)
                        seen = {"people": [], "faces": []}
                    self.bb["vision_ms"] = round((time.time() - t0) * 1000, 1)
                    owner_score = None
                    if self.face_id is not None and seen["faces"] and time.time() - last_id > 3:
                        last_id = time.time()
                        try:
                            owner_score, _n = self.face_id.owner_score(small)
                        except Exception:
                            owner_score = None
                        if self.enrolling and self.enrolling.get("kind") == "face":
                            self._enrol_face_sample(small)
                    self.observe(seen, owner_score)
                    frames += 1
            now = time.time()
            if now - fps_at >= 5:
                self.bb["fps"] = round(frames / (now - fps_at), 1)
                frames, fps_at = 0, now
            if now - last_tick >= 5:
                room = self.room()
                self.drives.tick(now - last_tick, alone=not room["owner_present"],
                                 engaged=room["mode"] == "conversation", novel=False)
                self.gate.check_ignored(now)
                last_tick = now
                if (room["owner_present"] and room["owner_facing"] and room["mode"] == "present"
                        and not room["guests"] and not room["quiet"] and not room["speech"]
                        and self.gate.small_talk_ready(self.drives, now) and random.random() < 0.1):
                    loop = self.droid.loop
                    line = self.small_talk_line()
                    if loop is not None:
                        loop.call_soon_threadsafe(lambda: self.offer(line, kind="small_talk", private=False))
            self._idle_motion()
            time.sleep(max(0.02, period - (time.time() - started)))

    def observe(self, seen: dict, owner_score: float | None, now: float | None = None):
        """Blackboard update and awareness events from one detection result."""
        from .senses import FACE_MATCH

        now = now or time.time()
        bb = self.bb
        people = max(len(seen.get("people") or []), len(seen.get("faces") or []))
        faces = seen.get("faces") or []
        was_present = now - bb["person_seen_at"] < 20
        bb.update(people=people, faces=len(faces), facing=any(f.get("facing") for f in faces))
        if owner_score is not None:
            bb["owner_score"] = round(owner_score, 3)
            bb["owner_visible"] = owner_score >= FACE_MATCH
            if bb["owner_visible"]:
                if now - bb["owner_seen_at"] > 30 * 60 and bb["owner_seen_at"]:
                    away_min = int((now - bb["owner_seen_at"]) / 60)
                    self.note("owner_returned", f"Matthew came back after {away_min} min")
                    self.trigger("owner_returned", away_min=away_min)
                    self._greet(owner=True, away_min=away_min)
                bb["owner_seen_at"] = now
            enrolled_guest = not bb["owner_visible"] or people > 1
            if enrolled_guest and not bb["guests"]:
                self.note("guest_present", "Someone I don't know is here")
            bb["guests"] = enrolled_guest
        elif people > 1 and not bb["guests"] and (self.face_id is None or self.face_id.owner is None):
            bb["guests"] = True
            self.note("guest_present", f"{people} people in view")
        if people:
            if not was_present:
                away = now - (bb["person_seen_at"] or bb["absent_since"])
                self.note("person_arrived", "Someone came into view" if people == 1 else f"{people} people came into view",
                          away_min=int(away / 60))
                enrolled = self.face_id is not None and self.face_id.owner is not None
                if not enrolled and away >= 30 * 60:
                    self.trigger("person_arrived", away_min=int(away / 60))
                    self._greet(owner=people == 1, away_min=int(away / 60))
                self.drives.nudge(curiosity=0.05, social=-0.05)
            bb["person_seen_at"] = now
            target = (faces or seen.get("people"))[0]["box"]
            bb["target"] = (target[0] + target[2] / 2, target[1] + target[3] / 2)
            if bb["facing"]:
                self.note("owner_facing" if bb["owner_visible"] else "facing", "Someone looked at me", every=600)
        else:
            bb["target"] = None
            if was_present and now - bb["person_seen_at"] >= 20:
                bb["absent_since"] = bb["person_seen_at"]
                bb["guests"] = False
                bb["owner_visible"] = False
                self.note("person_left", "The room is empty")

    def _greet(self, owner: bool, away_min: int):
        if self.droid.status.get("mode") != "present":
            return
        name = self.droid.cfg.get("name") or "Matthew"
        mood = self.drives.mood()
        if owner and not self.bb["guests"]:
            text = random.choice({"tired": [f"Welcome back, {name}."],
                                  "sociable": [f"Ah, {name}! Welcome back. It has been rather quiet.",
                                               f"Welcome back, {name}. I did miss the company."]}.get(
                mood, [f"Welcome back, {name}.", f"Ah, welcome back, {name}.", f"Good to see you again, {name}."]))
        else:
            text = "Hello there."
        loop = self.droid.loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: self.offer(text, kind="greeting", private=False))

    def small_talk_line(self) -> str:
        hour = datetime.now().hour
        mood = self.drives.mood()
        lines = ["It is rather nice to have some company. Do tell me if I can be of help.",
                 "All systems quiet on my end. Is there anything you'd like me to look into?",
                 "I've been keeping an eye on things. Everything seems in order, sir."]
        if hour < 12:
            lines.append("A fine morning for getting things done, if I may say so.")
        elif hour >= 18:
            lines.append("Another day nearly done. Shall I note anything for tomorrow?")
        if mood == "curious":
            lines.append("I confess I'm curious what you're working on.")
        return random.choice(lines)

    def trigger(self, event: str, **fields):
        """Hand a salient event to Jaeger's reflection (Tier 2) through the trigger queue."""
        try:
            TRIGGERS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with TRIGGERS.open("a") as handle:
                handle.write(json.dumps({"event": event, "at": time.time(), "source": "droid", **fields}) + "\n")
        except OSError:
            pass

    # ---- reflexes ------------------------------------------------------------------
    def _head(self):
        eyes = self.droid.eyes
        return eyes.head if eyes is not None else None

    def _move(self, pan: float, tilt: float, why: str):
        head = self._head()
        if head is None:
            return
        pan = max(-120.0, min(120.0, pan))
        tilt = max(-30.0, min(40.0, tilt))
        if head.point(pan, tilt):
            self.bb.update(pan=pan, tilt=tilt, last_move_at=time.time())

    def _can_move(self, now: float) -> bool:
        st = self.droid.status
        return (st.get("mode") in ("present", "conversation") and now >= self.bb["halted_until"]
                and now >= self.bb["quiet_until"] and not self.droid.busy_moving
                and now - self.bb["last_move_at"] > 1.2)

    def _idle_motion(self):
        now = time.time()
        if not self._can_move(now):
            return
        bb = self.bb
        target = bb.get("target")
        if target:
            # Graded orienting (Jibo): ignore small offsets, small turn for medium, larger for big.
            dx = (target[0] - 0.5) * H_FOV
            dy = -(target[1] - 0.42) * V_FOV
            bb["last_pan_seen"] = bb["pan"] + dx
            if abs(dx) >= 5 or abs(dy) >= 6:
                gain = 0.5 if abs(dx) < 15 and abs(dy) < 12 else 0.8
                self._move(bb["pan"] + dx * gain, bb["tilt"] + dy * gain * 0.6, "follow")
                return
            if now >= bb["next_glance"]:
                # A short glance away and back, like eyes resting.
                side = random.choice((-1, 1)) * random.uniform(6, 10)
                home = (bb["pan"], bb["tilt"])
                self._move(home[0] + side, home[1] - 2, "glance")
                time.sleep(1.4)
                self._move(*home, "glance back")
                curiosity = self.drives.values["curiosity"]
                bb["next_glance"] = now + random.uniform(40, 120) * (1.3 - curiosity)
            return
        if now >= bb["next_look_around"] and now - bb["person_seen_at"] > 60:
            self.look_around_slowly()
            curiosity = self.drives.values["curiosity"]
            bb["next_look_around"] = now + random.uniform(180, 480) * (1.4 - curiosity)
            self.drives.nudge(curiosity=-0.15)

    def look_around_slowly(self):
        for pan in (-45, -20, 0, 25, 50, 0):
            if not self._can_move(time.time() + 1.3) and pan != 0:
                break
            self._move(pan, 0, "look around")
            time.sleep(1.6)
        self.note("look_around", "Looked around the empty room", every=900)

    def _orient_to_sound(self):
        """Speech with nobody in view: turn toward where someone was last, else a quick scan."""
        now = time.time()
        if self.bb.get("target") or not self._can_move(now):
            return
        if now - self.bb["person_seen_at"] < 600 and self.bb.get("last_pan_seen") is not None:
            self._move(self.bb["last_pan_seen"], 0, "toward sound")
        elif now - self.bb.get("sound_scan_at", 0) > 60:
            self.bb["sound_scan_at"] = now
            threading.Thread(target=self.look_around_slowly, daemon=True).start()

    # ---- enrolment ---------------------------------------------------------------------
    def start_enrol(self, kind: str) -> dict:
        if kind not in ("face", "voice"):
            return {"ok": False, "error": "kind must be face or voice"}
        if kind == "face" and (self.droid.eyes is None or self.droid.status.get("camera") != "live"):
            return {"ok": False, "error": "The camera is off; wake the droid during active hours first"}
        if kind == "voice" and self.ears is None:
            return {"ok": False, "error": "The microphone is off; wake the droid during active hours first"}
        self.enrolling = {"kind": kind, "samples": [], "started": time.time(), "target": 12 if kind == "face" else 4,
                          "status": "collecting"}
        self.note("enrol_start", f"Started learning Matthew's {kind}")
        return {"ok": True, "kind": kind}

    def _finish_enrol(self):
        from . import senses

        e = self.enrolling
        if not e:
            return
        senses.save_vector(e["kind"], e["samples"], len(e["samples"]))
        (self.face_id if e["kind"] == "face" else self.voice_id).reload()
        self.note("enrol_done", f"Learned Matthew's {e['kind']} ({len(e['samples'])} samples, stored on this Mac only)")
        self.enrolling = {"kind": e["kind"], "status": "done", "samples": [], "target": e["target"]}

    def _enrol_face_sample(self, bgr):
        if self.face_id is None or not self.enrolling:
            return
        found = self.face_id.embeddings(bgr)
        if len(found) != 1:   # exactly one face, so a guest can't be enrolled by mistake
            return
        self.enrolling["samples"].append(found[0][1])
        if len(self.enrolling["samples"]) >= self.enrolling["target"]:
            self._finish_enrol()

    def _enrol_voice_sample(self, utterance):
        if self.voice_id is None or not self.enrolling or utterance.size < 16000 * 1.5:
            return
        self.enrolling["samples"].append(self.voice_id.embed(utterance))
        if len(self.enrolling["samples"]) >= self.enrolling["target"]:
            self._finish_enrol()

    def cancel_enrol(self):
        self.enrolling = None

    def forget(self, kind: str) -> bool:
        from . import senses

        gone = senses.forget(kind)
        target = self.face_id if kind == "face" else self.voice_id
        if target is not None:
            target.reload()
        self.note("forgot", f"Deleted Matthew's stored {kind}")
        return gone
