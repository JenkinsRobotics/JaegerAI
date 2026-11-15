"""The relay loop: phone ⇄ home chat, plus outbox deliveries and approvals."""

from __future__ import annotations

import os
import signal
import threading
import time
import uuid
from typing import Any

from . import gateway, outbox
from .config import load_config, read_state, telegram_token, write_state
from .imessage import IMessageSelfChat
from .telegram import TelegramBot

TERMINAL = {"completed", "failed", "cancelled", "error", "denied", "execution_unknown", "interrupted"}
TURN_TIMEOUT_S = float(os.environ.get("JAEGER_CHANNEL_TURN_TIMEOUT_S", "900"))


def log(msg: str) -> None:
    print(f"[channels] {time.strftime('%H:%M:%S')} {msg}", flush=True)


class Relay:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.state = read_state("relay_state")
        self.state.setdefault("imessage", {})
        self.state.setdefault("telegram", {})
        self.state.setdefault("approvals_sent", {})
        self.imessage = IMessageSelfChat(self.cfg["imessage"], self.state["imessage"])
        self.telegram = TelegramBot(self.cfg["telegram"], self.cfg, telegram_token(), self.state["telegram"])
        self.prefix = str(self.cfg.get("reply_prefix") or "Jaeger: ")
        self.stop = threading.Event()
        self.turn_lock = threading.Lock()
        self.home: str | None = None
        self.started_at = time.time()
        self.counters = {"inbound": 0, "replies": 0, "delivered": 0, "failed": 0}

    # -- transports ------------------------------------------------------
    def transports(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.cfg["telegram"].get("enabled", True) and self.telegram.configured and self.telegram.chat_id is not None:
            out["telegram"] = self.telegram
        if self.cfg["imessage"].get("enabled", True) and self.imessage.configured:
            out["imessage"] = self.imessage
        return out

    def send_on(self, channel: str, text: str) -> dict[str, Any]:
        transport = self.transports().get(channel)
        if transport is None:
            return {"sent": False, "error": f"{channel} not live"}
        body = text if channel != "imessage" else self.prefix + text
        return transport.send(body)

    # -- status ------------------------------------------------------------
    def write_status(self) -> None:
        write_state("status", {
            "pid": os.getpid(),
            "updated_at": time.time(),
            "started_at": self.started_at,
            "home_session": self.home,
            "telegram": {**self.telegram.status(), "live": "telegram" in self.transports()},
            "imessage": {**self.imessage.status(), "live": "imessage" in self.transports()},
            "outbox_pending": len(outbox.pending()),
            "counters": self.counters,
        })
        write_state("relay_state", self.state)

    # -- inbound → turn ---------------------------------------------------------
    def handle_inbound(self, channel: str, text: str) -> None:
        self.counters["inbound"] += 1
        log(f"inbound on {channel} ({len(text)} chars)")
        if self.try_approval_reply(channel, text):
            return
        with self.turn_lock:
            try:
                reply = self.run_turn(channel, text)
            except Exception as exc:  # noqa: BLE001
                reply = f"(Jaeger couldn't run that: {exc})"
        if reply:
            res = self.send_on(channel, reply)
            self.counters["replies" if res.get("sent") else "failed"] += 1

    def run_turn(self, channel: str, text: str) -> str:
        if self.home is None:
            self.home = gateway.home_session(self.cfg.get("home_agent") or "native:jaeger")
        session = self.home
        rid = f"ch-{channel}-{uuid.uuid4().hex[:16]}"
        body = {"text": text, "request_id": rid, "source": channel}
        if channel == "telegram":
            self.telegram.typing()
        deadline = time.time() + TURN_TIMEOUT_S
        while True:
            try:
                gateway.call("POST", f"/v1/sessions/{gateway.q(session)}/turns", body)
                break
            except gateway.GatewayError as exc:
                if exc.status == 409 and "belongs" not in str(exc) and time.time() < deadline:
                    time.sleep(4)  # home chat busy: wait our turn
                    continue
                raise
        last_typing = time.time()
        while time.time() < deadline and not self.stop.is_set():
            time.sleep(1.5)
            row = gateway.call("GET", f"/v1/sessions/{gateway.q(session)}/requests/{gateway.q(rid)}")
            status = str(row.get("status") or "")
            if status in TERMINAL:
                result = row.get("result") or {}
                output = str(result.get("output") or "").strip()
                if status == "completed":
                    return output or "(done — no text reply)"
                return output or f"(that turn ended: {status})"
            if channel == "telegram" and time.time() - last_typing > 4:
                self.telegram.typing()
                last_typing = time.time()
        return "(still working — I'll post the result in the home chat)"

    # -- approvals --------------------------------------------------------------
    def poll_approvals(self) -> None:
        if not self.cfg["deliver"].get("approvals", True):
            return
        try:
            items = gateway.call("GET", "/v1/approvals?status=pending").get("approvals") or []
        except Exception as exc:  # noqa: BLE001
            log(f"approvals poll failed: {exc}")
            return
        sent = self.state["approvals_sent"]
        live_ids = {a.get("approval_id") for a in items}
        for key in list(sent):
            if key not in live_ids:
                sent.pop(key, None)
        for item in items:
            aid = str(item.get("approval_id") or "")
            if not aid or aid in sent:
                continue
            # Only new requests: anything created before the relay started is
            # already visible in the app and would just be noise.
            if float(item.get("created_at") or 0) < self.started_at - 60:
                sent[aid] = "skipped_preexisting"
                continue
            short = aid.rsplit("_", 1)[-1][:4]
            risk = item.get("risk") or "medium"
            title = item.get("title") or item.get("prompt") or "Approval needed"
            text = (f"Approval needed ({risk}): {title}\n"
                    f"Reply \"approve {short}\" or \"deny {short}\".")
            outbox.enqueue(text, kind="approval", dedupe_key=f"approval:{aid}")
            sent[aid] = short

    def try_approval_reply(self, channel: str, text: str) -> bool:
        words = text.strip().lower().split()
        if not words or words[0] not in {"approve", "deny", "yes", "no", "allow"}:
            return False
        pending = {short: aid for aid, short in self.state["approvals_sent"].items()
                   if short and short != "skipped_preexisting"}
        if len(words) == 2:
            aid = pending.get(words[1])
        elif len(words) == 1 and len(pending) == 1:
            aid = next(iter(pending.values()))
        else:
            return False
        if aid is None:
            self.send_on(channel, "I don't have a pending approval with that code.")
            return True
        decision = "deny" if words[0] in {"deny", "no"} else "once"
        try:
            gateway.call("POST", f"/v1/approvals/{gateway.q(aid)}", {"decision": decision})
            self.state["approvals_sent"].pop(aid, None)
            self.send_on(channel, "Approved." if decision == "once" else "Denied.")
        except gateway.GatewayError as exc:
            self.send_on(channel, f"Couldn't record that: {exc}")
        return True

    # -- outbox -----------------------------------------------------------------
    def drain_outbox(self) -> None:
        import json
        live = self.transports()
        if not live:
            return
        order = [c for c in self.cfg["deliver"].get("channels") or [] if c in live] or list(live)
        for path in outbox.pending()[:20]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                outbox.settle(path, "failed", {"error": "unreadable"})
                continue
            kind = item.get("kind")
            if kind == "schedule" and not self.cfg["deliver"].get("schedules", True):
                outbox.settle(path, "failed", {"error": "schedules delivery off"})
                continue
            if kind == "notification" and not self.cfg["deliver"].get("notifications", True):
                outbox.settle(path, "failed", {"error": "notifications delivery off"})
                continue
            targets = [c for c in (item.get("channels") or order) if c in live]
            if self.cfg["deliver"].get("fanout") != "all" and not item.get("channels"):
                targets = targets[:1]
            text = item["text"]
            if item.get("title"):
                text = f"{item['title']}\n{text}"
            results = {c: self.send_on(c, text) for c in targets}
            ok = any(r.get("sent") for r in results.values())
            self.counters["delivered" if ok else "failed"] += 1
            outbox.settle(path, "sent" if ok else "failed", {"results": results})

    # -- loops ------------------------------------------------------------------
    def _inbound_loop(self, transport: Any, poll_fn) -> None:
        while not self.stop.is_set():
            try:
                for msg in poll_fn():
                    threading.Thread(target=self.handle_inbound, args=(transport.name, msg["text"]),
                                     daemon=True, name=f"turn-{transport.name}").start()
            except Exception as exc:  # noqa: BLE001
                log(f"{transport.name} poll error: {exc}")
                self.stop.wait(5)
            if transport.name == "imessage":
                self.stop.wait(2)

    def run(self) -> None:
        log("relay starting")
        threads = []
        if self.telegram.configured:
            threads.append(threading.Thread(target=self._inbound_loop, args=(self.telegram, self.telegram.poll),
                                            daemon=True, name="telegram"))
        else:
            log("telegram: no bot token yet (JAEGER_TELEGRAM_BOT_TOKEN in ~/.jaeger/secrets.env)")
        if self.imessage.configured:
            threads.append(threading.Thread(target=self._inbound_loop,
                                            args=(self.imessage, lambda: self.imessage.poll(self.prefix)),
                                            daemon=True, name="imessage"))
        else:
            log("imessage: self-chat not configured")
        for t in threads:
            t.start()
        last_approvals = 0.0
        while not self.stop.is_set():
            try:
                if time.time() - last_approvals > 10:
                    self.poll_approvals()
                    last_approvals = time.time()
                self.drain_outbox()
                self.write_status()
            except Exception as exc:  # noqa: BLE001
                log(f"loop error: {exc}")
            self.stop.wait(3)
        self.write_status()


def main() -> None:
    try:
        from jaeger_ai.core.secrets_env import load_secrets_env
        load_secrets_env()
    except Exception:  # noqa: BLE001
        pass
    relay = Relay()
    signal.signal(signal.SIGTERM, lambda *_: relay.stop.set())
    signal.signal(signal.SIGINT, lambda *_: relay.stop.set())
    relay.run()
