"""LocalAgreement streaming STT — STUB (not implemented yet).

The plan (whisper-streaming / LocalAgreement-2, Macháček et al.): run ONE
pywhispercpp model on overlapping windows of the live buffer and confirm a
token only once two consecutive passes agree on it.  Confirmed tokens are
emitted as ``is_final=False`` partials (live caption) and the stabilized
tail becomes the final commit.  Lower compute than two concurrent models,
real streaming partials.

To implement: mirror the ``STTAdapter`` surface the other methods expose
(``start`` / ``stop`` / ``next_phrase`` / ``set_paused`` / ``open_followup``),
drive a rolling window off the mic, apply the agreement policy, and publish
partial ``Transcript(is_final=False)`` messages plus the final commit.
"""

from __future__ import annotations


class WhisperSTTLocalAgreement:
    """Not implemented yet — see the module docstring for the algorithm."""

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "local_agreement STT is a stub — not implemented yet. See "
            "nodes/whisper_stt/engine/local_agreement/pipeline.py for the plan.")
