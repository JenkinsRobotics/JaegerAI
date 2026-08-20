"""What the serving brain can do — asked, not assumed.

The engine (``jaeger_agent``) is already brain-agnostic: its adapter ABC
has no local-vs-cloud branch anywhere in it. The leaks are up here, in
the host layer, where limits derived from ONE deployment got written
down as constants. The clearest example is subagent fan-out, capped at 2
with this reasoning:

    all subagents share the ONE loaded Gemma model (no second model
    load), and llama-cpp serializes decode, so 2 is the practical
    ceiling.

Every word of that is true — about llama.cpp. It is simply false about
an Ollama Cloud endpoint, which will take eight concurrent requests
without noticing. A cap that reads as physics is really a property of
one brain, and swapping the brain should swap the number.

So the framework stops hardcoding and starts asking. A
:class:`BrainProfile` is what the live client answers about itself:

  * ``concurrency`` — how many model calls may be in flight at once.
    ONE for an in-process llama.cpp/MLX model (decode is serialized by
    the runtime and a second caller just queues behind a lock); more
    for anything that is really a server, because a server is built to
    interleave requests.
  * ``context_window`` — the real window of the lane that serves, which
    is already resolved properly per-lane by ``_context_budget_for``;
    this carries it so callers stop re-deriving it.
  * ``parallel_tools`` — whether the model emits more than one tool call
    per assistant message at all. Cheap to ask, and it decides whether
    batching guidance in the prompt is worth its tokens.

Read profiles through :func:`profile_for`, never by testing ``kind ==
"local"`` at a call site. A new backend then arrives by teaching this
module one row, instead of by grepping for every place someone wrote
down what the old backend happened to cost.

Every number here is a DEFAULT and every one is overridable:
``JAEGER_BRAIN_CONCURRENCY`` pins concurrency for operators whose brain
does not match its family (a self-hosted vLLM on one GPU, a rate-limited
free tier that should behave like a single lane).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


# Providers that are a SERVER rather than an in-process model. A server
# owns its own scheduler: concurrent requests interleave instead of
# queueing behind one decode loop. LM Studio and local Ollama are on
# this list even though they run on the same machine — "local" is about
# where the weights live, and this list is about who schedules the work.
_SERVER_PROVIDERS = frozenset({
    "lmstudio", "ollama", "ollama-cloud", "openai", "anthropic",
    "gemini", "xai",
})

# Providers whose endpoint is off-box. Higher default concurrency: a
# hosted endpoint is sized for many callers, and round-trip latency
# means overlap is where the wall-clock win actually comes from.
_CLOUD_PROVIDERS = frozenset({
    "ollama-cloud", "openai", "anthropic", "gemini", "xai",
})

# Defaults, by what the brain IS rather than by where it runs.
_CONCURRENCY_IN_PROCESS = 1   # llama.cpp / MLX — decode serializes
_CONCURRENCY_LOCAL_SERVER = 3  # LM Studio / local Ollama — one GPU, but it batches
_CONCURRENCY_CLOUD = 8        # hosted — sized for many callers

# Ceiling on any single fan-out regardless of brain. Past this the
# limiter stops being the model and starts being the host's file
# descriptors, the provider's rate limit, and the operator's bill.
MAX_CONCURRENCY = 16


@dataclass(frozen=True)
class BrainProfile:
    """What the brain serving right now can do.

    Frozen because it describes a fact about the live client, not a
    setting. Switching brains produces a new profile; nothing mutates
    one in place.
    """

    kind: str = "local"
    """``"local"`` (in-process weights) or ``"external"`` (over a wire)."""

    provider: str = "in-process"
    model: str = ""

    location: str = "local"
    """``"local"`` · ``"remote"`` (a server elsewhere on the LAN) ·
    ``"cloud"``. Reporting only — never branch behaviour on it, branch
    on the capability that actually matters."""

    concurrency: int = _CONCURRENCY_IN_PROCESS
    """Model calls that may be in flight at once."""

    context_window: int = 0
    """Real window of the serving lane; 0 when not yet known."""

    parallel_tools: bool = True
    """Whether the model emits multiple tool calls per message."""

    @property
    def serializes_decode(self) -> bool:
        """True when a second concurrent call buys nothing — the honest
        way to say "in-process" without naming a backend."""
        return self.concurrency <= 1

    @property
    def max_subagents(self) -> int:
        """Concurrent subagents to fan out.

        Identical to ``concurrency``: a subagent IS a model caller, and
        the reason to cap them is the same reason. Named separately
        because the delegation site reads better for it, and because a
        future brain might want the two to diverge.
        """
        return self.concurrency

    def describe(self) -> str:
        lane = f"{self.provider}/{self.model}" if self.model else self.provider
        window = f"{self.context_window:,} ctx" if self.context_window else "ctx unknown"
        return (
            f"{lane} · {self.location} · {window} · "
            f"{self.concurrency} concurrent"
        )


def _env_concurrency() -> int | None:
    """``JAEGER_BRAIN_CONCURRENCY``, or None when unset/unusable.

    An operator override always wins: the family defaults below are
    good guesses about a class of brain, and a guess should never beat
    someone who measured their own.
    """
    raw = os.environ.get("JAEGER_BRAIN_CONCURRENCY", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 1:
        return None
    return min(value, MAX_CONCURRENCY)


def _default_concurrency(kind: str, provider: str) -> int:
    if kind != "external":
        return _CONCURRENCY_IN_PROCESS
    if provider in _CLOUD_PROVIDERS:
        return _CONCURRENCY_CLOUD
    if provider in _SERVER_PROVIDERS:
        return _CONCURRENCY_LOCAL_SERVER
    # An unrecognised external provider is still a server, but we know
    # nothing about it — take the conservative server number.
    return _CONCURRENCY_LOCAL_SERVER


def _location_for(kind: str, provider: str) -> str:
    if kind != "external":
        return "local"
    if provider in _CLOUD_PROVIDERS:
        return "cloud"
    return "remote"


def profile_for(client: Any) -> BrainProfile:
    """The profile of ``client`` — the ONE way to ask what the brain can do.

    Best-effort by contract: an unrecognised client, or none at all,
    yields the in-process profile. That default is the conservative one
    (concurrency 1), so a caller that guesses wrong under-parallelises
    rather than stampeding a backend that cannot take it.
    """
    if client is None:
        return BrainProfile()

    kind = str(getattr(client, "kind", "local") or "local")
    provider = str(getattr(client, "provider", "") or "")
    if not provider:
        provider = "in-process" if kind != "external" else "unknown"

    window = 0
    try:
        window = max(0, int(getattr(client, "loaded_ctx", 0) or 0))
    except (TypeError, ValueError):
        window = 0

    concurrency = _env_concurrency() or _default_concurrency(kind, provider)

    return BrainProfile(
        kind=kind,
        provider=provider,
        model=str(getattr(client, "model_name", "") or ""),
        location=_location_for(kind, provider),
        concurrency=min(max(1, concurrency), MAX_CONCURRENCY),
        context_window=window,
        parallel_tools=bool(getattr(client, "parallel_tools", True)),
    )


def active_profile() -> BrainProfile:
    """The profile of the brain serving THIS process right now.

    Reads the live client off the pipeline rather than the config: the
    config states an intent and the client is the outcome, and fanning
    out eight subagents against a lane that fell back to one local model
    is exactly the mistake that distinction exists to prevent.
    """
    try:
        from jaeger_ai.main import _pipeline

        return profile_for(_pipeline.get("client"))
    except Exception:  # noqa: BLE001 — pre-boot / import cycle
        return BrainProfile()


__all__ = [
    "BrainProfile",
    "MAX_CONCURRENCY",
    "active_profile",
    "profile_for",
]
