"""Multi-Model Roundtable & Blind Compare engine for jaeger-models.

Combines side-by-side multi-provider comparison (with optional blind A/B labels
for unbiased evaluation) and collaborative peer critique + consensus synthesis
so multiple models can cross-check each other and converge on a stronger answer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
import random
import time
from typing import Any, Sequence

from jaeger_contracts import ModelPort


@dataclass(frozen=True)
class RoundtableParticipant:
    name: str
    model: ModelPort
    role_prompt: str = ""


@dataclass
class ParticipantResponse:
    label: str
    model_name: str
    ok: bool
    content: str
    latency_ms: int
    error: str | None = None
    critique: str = ""

    def to_dict(self, *, hide_identity: bool = False) -> dict[str, Any]:
        return {
            "label": self.label,
            "model_name": self.label if hide_identity else self.model_name,
            "ok": self.ok,
            "content": self.content,
            "latency_ms": self.latency_ms,
            "chars": len(self.content),
            "error": self.error,
            **({"critique": self.critique} if self.critique else {}),
        }


@dataclass
class RoundtableReport:
    prompt: str
    blind: bool
    responses: list[ParticipantResponse] = field(default_factory=list)
    reveal_map: dict[str, str] = field(default_factory=dict)
    consensus: str = ""
    synthesizer_model: str = ""
    total_latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": any(r.ok for r in self.responses),
            "prompt": self.prompt,
            "blind": self.blind,
            "responses": [r.to_dict(hide_identity=self.blind) for r in self.responses],
            "reveal_map": dict(self.reveal_map),
            "consensus": self.consensus,
            "synthesizer_model": self.synthesizer_model,
            "total_latency_ms": self.total_latency_ms,
        }

    def to_markdown(self) -> str:
        lines = [f"# Roundtable Comparison", "", f"**Prompt:** {self.prompt}", ""]
        for r in self.responses:
            heading = r.label if self.blind else f"{r.label} ({r.model_name})"
            lines.append(f"## {heading} — {r.latency_ms} ms")
            if r.ok:
                lines.append(r.content.strip())
                if r.critique:
                    lines.extend(["", "**Peer Critique:**", r.critique.strip()])
            else:
                lines.append(f"_Error: {r.error}_")
            lines.append("")
        if self.consensus:
            lines.extend(["## Consensus Synthesis", "", self.consensus.strip(), ""])
        return "\n".join(lines).strip()


class ModelRoundtable:
    """Runs parallel multi-model comparison with optional blind labeling, critique, and consensus."""

    def __init__(
        self,
        participants: Sequence[RoundtableParticipant],
        *,
        synthesizer: ModelPort | None = None,
        max_workers: int = 4,
    ) -> None:
        if not participants:
            raise ValueError("ModelRoundtable requires at least one participant")
        self._participants = list(participants)
        self._synthesizer = synthesizer
        self._max_workers = max(1, min(int(max_workers), 8))

    def _call_one(
        self,
        participant: RoundtableParticipant,
        label: str,
        prompt: str,
    ) -> ParticipantResponse:
        messages: list[dict[str, Any]] = []
        if participant.role_prompt.strip():
            messages.append({"role": "system", "content": participant.role_prompt.strip()})
        messages.append({"role": "user", "content": prompt})
        t0 = time.monotonic()
        try:
            res = participant.model.complete(messages)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ParticipantResponse(
                label=label,
                model_name=participant.name,
                ok=True,
                content=str(res.get("content") or "").strip(),
                latency_ms=elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ParticipantResponse(
                label=label,
                model_name=participant.name,
                ok=False,
                content="",
                latency_ms=elapsed_ms,
                error=f"{type(exc).__name__}: {exc}",
            )

    def run(
        self,
        prompt: str,
        *,
        blind: bool = False,
        critique_round: bool = False,
        consensus: bool = True,
        seed: int | None = None,
    ) -> RoundtableReport:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            raise ValueError("prompt is required")

        t_start = time.monotonic()
        ordered = list(self._participants)
        if blind and len(ordered) > 1:
            rng = random.Random(seed)
            rng.shuffle(ordered)

        labels = [f"Model {chr(65 + i)}" for i in range(len(ordered))]
        reveal_map = {labels[i]: ordered[i].name for i in range(len(ordered))}

        results: dict[int, ParticipantResponse] = {}
        if len(ordered) == 1:
            results[0] = self._call_one(ordered[0], labels[0], clean_prompt)
        else:
            with ThreadPoolExecutor(max_workers=min(self._max_workers, len(ordered))) as pool:
                fut_map = {
                    pool.submit(self._call_one, ordered[i], labels[i], clean_prompt): i
                    for i in range(len(ordered))
                }
                for fut in as_completed(fut_map):
                    idx = fut_map[fut]
                    results[idx] = fut.result()

        responses = [results[i] for i in range(len(ordered))]
        healthy = [r for r in responses if r.ok and r.content]

        # Optional Round 2: peer critique across healthy responses
        if critique_round and len(healthy) >= 2:
            peer_bundle = "\n\n".join(
                f"### {r.label}\n{r.content[:2000]}" for r in healthy
            )
            for idx, resp in enumerate(responses):
                if not resp.ok:
                    continue
                critique_prompt = (
                    f"Original prompt: {clean_prompt}\n\n"
                    f"Peer responses:\n{peer_bundle}\n\n"
                    f"You are {resp.label}. In 3-5 concise bullet points, note where peers agree, "
                    "spot any factual/logical flaws, and refine your recommendation."
                )
                c_res = self._call_one(ordered[idx], resp.label, critique_prompt)
                if c_res.ok:
                    resp.critique = c_res.content

        # Optional Final Round: Consensus synthesis
        consensus_text = ""
        synth_name = ""
        if consensus and healthy:
            synth_model = self._synthesizer
            if synth_model is None:
                # Use the first healthy participant's model as synthesizer.
                first_ok_idx = next(i for i, r in enumerate(responses) if r.ok and r.content)
                synth_model = ordered[first_ok_idx].model
                synth_name = ordered[first_ok_idx].name
            else:
                synth_name = getattr(synth_model, "name", "synthesizer")

            if len(healthy) == 1:
                consensus_text = healthy[0].content
            else:
                sections = []
                for r in healthy:
                    part = f"### {r.label}\n{r.content[:2500]}"
                    if r.critique:
                        part += f"\n\nCritique from {r.label}:\n{r.critique[:1200]}"
                    sections.append(part)
                synth_prompt = (
                    f"You are moderating a multi-model roundtable.\n\n"
                    f"Question:\n{clean_prompt}\n\n"
                    f"Candidate Answers:\n" + "\n\n".join(sections) + "\n\n"
                    "Synthesize a single crisp consensus answer covering:\n"
                    "1. Best unified recommendation\n"
                    "2. Key points of agreement\n"
                    "3. Important disagreements or caveats\n"
                )
                try:
                    out = synth_model.complete([{"role": "user", "content": synth_prompt}])
                    consensus_text = str(out.get("content") or "").strip()
                except Exception as exc:  # noqa: BLE001
                    consensus_text = f"(Consensus synthesis failed: {type(exc).__name__}: {exc})"

        total_ms = int((time.monotonic() - t_start) * 1000)
        return RoundtableReport(
            prompt=clean_prompt,
            blind=blind,
            responses=responses,
            reveal_map=reveal_map,
            consensus=consensus_text,
            synthesizer_model=synth_name,
            total_latency_ms=total_ms,
        )


__all__ = [
    "ModelRoundtable",
    "ParticipantResponse",
    "RoundtableParticipant",
    "RoundtableReport",
]
