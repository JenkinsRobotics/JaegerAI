"""Streaming ASR node: monotonic engine, DriftAnchor, labels, and aggregation.

Extracted 2026-09-02 from ../gemma_multimodal.py (the canonical single file).
Keep in sync by re-extraction; behavior must stay byte-equivalent."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import numpy as np

try:  # packaged engine
    from jaeger_agent.core.context import match_wake
except ImportError:  # portable node folder loaded by the playground
    from context import match_wake

# ═══════════════════════════════════════════════════════════════════════════
# section: streaming audio pipeline (full) — from 04 (drift-anchored engine)
# ═══════════════════════════════════════════════════════════════════════════

_BRACKETED_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")

def _is_event_only(text: str) -> bool:
    """Is this transcript nothing but bracketed non-speech?

    Whisper labels what it hears rather than inventing words: "(clapping)",
    "(applause)", "(people chattering)", "[BLANK_AUDIO]". Those are honest
    outputs and useless as SENTENCES — committing them fills the live buffer
    with noise that only clears when the whole turn flushes, which is what
    made a 90-second turn look like the app was holding on to the room.

    Strip the brackets; if nothing is left, it was never speech.
    """
    return not _BRACKETED_RE.sub("", text or "").strip(" .,!?-\"'")

_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*(?=\s)")

_ABBREV = re.compile(r"\b(mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|no|fig)\.$", re.I)

STABLE_PASSES = 2          # identical decodes before a trailing sentence commits

MIN_COMMIT_CHARS = 2       # ignore stray punctuation fragments

def split_sentences(text: str) -> list[str]:
    """Split on sentence ends, without breaking decimals or abbreviations."""
    text = " ".join(text.split())
    if not text:
        return []
    out: list[str] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        end = m.end()                     # inclusive of the punctuation
        piece = text[start:end].strip()
        if not piece:
            continue
        # "3.5" — digits either side of a lone period are not a boundary.
        if (m.group().startswith(".")
                and text[m.start() - 1:m.start()].isdigit()
                and text[end + 1:end + 2].isdigit()):
            continue
        if _ABBREV.search(piece):
            continue
        out.append(piece)
        start = end
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out

@dataclass
class SentenceCommitter:
    """Feed it each rolling transcript; it yields sentences once, in order."""

    stable_passes: int = STABLE_PASSES
    committed: list[str] = field(default_factory=list)
    _seen: dict[int, tuple[str, int]] = field(default_factory=dict)  # idx -> (text, passes)

    def update(self, transcript: str, allow_tail_commit: bool = True) -> list[str]:
        """Returns sentences that just became final. Call once per decode.

        allow_tail_commit=False withholds STABILITY commits for the last
        sentence. Used when the decode window ends right at that sentence:
        Whisper hallucinates plausible completions at the window edge, and a
        pause makes the hallucination identical across passes — stable, wrong,
        and frozen. Superseded-rule commits are unaffected (a later sentence
        existing proves the tail is not at the edge).
        """
        sentences = split_sentences(transcript)
        ready: list[str] = []
        n_committed = len(self.committed)

        for idx, sentence in enumerate(sentences):
            if idx < n_committed:
                continue                      # already emitted, never revisit

            prev_text, prev_passes = self._seen.get(idx, ("", 0))
            passes = prev_passes + 1 if sentence == prev_text else 1
            self._seen[idx] = (sentence, passes)

            # A later sentence exists -> the speaker moved on -> this one is done.
            superseded = idx < len(sentences) - 1
            settled = passes >= self.stable_passes and (
                superseded or allow_tail_commit)
            if (superseded or settled) and len(sentence) >= MIN_COMMIT_CHARS:
                # Only commit contiguously: never skip a sentence that is still
                # churning, or the transcript would come out reordered.
                if idx == len(self.committed):
                    self.committed.append(sentence)
                    ready.append(sentence)
        return ready

    def force_oldest(self) -> list[str]:
        """Commit the oldest pending sentence regardless of stability.

        For pressure relief only: when unstable audio (applause, crowd noise)
        stops anything from stabilising and the buffer keeps growing, the
        oldest sentence has been re-decoded for many passes — it is as
        confirmed as it will ever get. Committing it one sentence at a time
        preserves order; the old alternative was a 40s cap dump that discarded
        whole clauses (found by jfk_regression --diff on the full speech).
        """
        idx = len(self.committed)
        if idx in self._seen:
            text = self._seen[idx][0]
            if len(text) >= MIN_COMMIT_CHARS:
                self.committed.append(text)
                return [text]
        return []

    def flush(self) -> list[str]:
        """End of turn — emit whatever is left, stable or not."""
        ready = []
        for idx in sorted(self._seen):
            if idx == len(self.committed):
                text = self._seen[idx][0]
                if len(text) >= MIN_COMMIT_CHARS:
                    self.committed.append(text)
                    ready.append(text)
        return ready

    def pending(self, transcript: str) -> str:
        """The uncommitted tail — what to show as provisional."""
        sentences = split_sentences(transcript)
        return " ".join(sentences[len(self.committed):])

    def reset(self) -> None:
        self.committed.clear()
        self._seen.clear()

SAMPLE_RATE = 16000

T_UNITS = 0.01                    # whisper timestamps are centiseconds

EDGE_GUARD_S = 1.0

def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

class IncrementalTranscriber:
    """feed() audio, decode_pass() on a cadence, flush() at end of turn."""

    def __init__(self, model, language: str = "en", stable_passes: int = 2,
                 sample_rate: int = SAMPLE_RATE, min_seconds: float = 1.0,
                 pad_ms: int = 250, max_seconds: float = 40.0,
                 soft_cap_seconds: float = 25.0) -> None:  # 12 was tried for the omission and regressed BOTH clean speakers (3.7->20.4, 18.3->36.1); staleness needs a tail-commit, not a shorter guillotine
        self.model = model
        self.language = language
        # Words already committed, fed back as the decoder's initial_prompt.
        # Trimming committed audio deletes the model's left context; without
        # this, every post-trim decode starts cold and the boundary words
        # come out wrong (measured on clean360: 7.4% vs a 1.85% ceiling).
        self._context_tail = ""

        self.stable_passes = stable_passes
        self.sample_rate = sample_rate
        self.min_samples = int(sample_rate * min_seconds)
        self.max_samples = int(sample_rate * max_seconds)
        self.soft_cap_s = soft_cap_seconds
        self.pad = np.zeros(int(sample_rate * pad_ms / 1000), dtype=np.float32)

        self._lock = threading.Lock()
        self._buf = np.zeros(0, dtype=np.float32)
        self._since_decode = 0
        self.committer = SentenceCommitter(stable_passes=stable_passes)
        self.all_committed: list[str] = []    # across trims, whole turn
        self.pending = ""
        # THE LEDGER: committed words whose audio is still in the buffer. Their
        # audio sits at the buffer head in order, so re-decodes re-hear exactly
        # these words. Stripping against this ledger — and nothing else — makes
        # "same audio re-heard" vs "speaker genuinely repeated it" an exact
        # distinction: a genuine repeat's first copy is already trimmed away.
        self.untrimmed: list[str] = []
        self._last_raw = ""              # final-flush punctuation reconciliation
        # STRUCTURED SEAM (2026-09-01, default-on in the live apps): fires
        # with the audio span whose words just committed — at trim time the
        # cut chunk IS that audio, exactly. Streaming has no endpointed turn
        # to annotate, so this is where speaker/prosody context attaches.
        self.on_commit_audio = None
        self.decodes = 0
        self.debug: list[dict] | None = None  # set to [] to record trim/strip decisions

    # -- audio in ------------------------------------------------------------
    def feed(self, frame: np.ndarray) -> None:
        f = np.asarray(frame, dtype=np.float32).reshape(-1)
        with self._lock:
            self._buf = np.concatenate([self._buf, f])
            self._since_decode += f.size

    @property
    def buffer_seconds(self) -> float:
        with self._lock:
            return self._buf.size / self.sample_rate

    @property
    def undecoded_seconds(self) -> float:
        with self._lock:
            return self._since_decode / self.sample_rate

    def over_cap(self) -> bool:
        return self.buffer_seconds > self.max_samples / self.sample_rate

    # -- text out ------------------------------------------------------------
    def turn_text(self) -> str:
        return " ".join(self.all_committed)

    def display_text(self) -> str:
        """Committed + churning tail — what a live preview should show."""
        settled = self.turn_text()
        if settled and self.pending:
            return f"{settled} {self.pending}"
        return settled or self.pending

    # -- decode / commit / trim -----------------------------------------------
    @staticmethod
    def _tok_eq(a: str, b: str) -> bool:
        return a == b or (len(a) > 3 and a[:4] == b[:4])

    def _strip_untrimmed(self, text: str, *, include_tracked: bool = False
                         ) -> tuple[str, int, bool]:
        """Drop the re-heard committed words from the transcript head.

        Returns (kept_text, n_ledger_words_matched, aligned). aligned=False
        means the head could not be reconciled with the ledger at all — the
        caller must not run commit decisions on that transcript, or ledger
        words would re-commit as "new" sentences.
        """
        if not self.untrimmed:
            return text, 0, True
        # Words still tracked by this committer must remain in its transcript
        # so sentence indexes do not shift.  This matters when a sentence
        # commits but Whisper exposes no safe segment boundary and _trim()
        # cuts zero audio.  Only strip older ledger residue left by a previous
        # trim/reset; the current committer already de-duplicates its own
        # committed prefix by index.
        tracked = (0 if include_tracked else
                   len(compact(" ".join(self.committer.committed)).split()))
        strip_count = max(0, len(self.untrimmed) - tracked)
        if strip_count == 0:
            return text, 0, True
        limit = strip_count if include_tracked else min(60, strip_count)
        def clean_token(token: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", token.lower())
        want = [clean_token(w) for w in self.untrimmed[:limit]]
        head = compact(text).split()
        low = [clean_token(t) for t in head]
        if not low:
            return text, 0, True
        i = j = 0
        misses = 0
        hits = 0
        budget = max(2, len(want) // 3)
        while i < len(want) and j < len(low):
            if self._tok_eq(want[i], low[j]):
                hits += 1
                i += 1
                j += 1
                continue
            misses += 1
            if misses > budget:
                break
            if i + 1 < len(want) and self._tok_eq(want[i + 1], low[j]):
                i += 2
                j += 1
            elif j + 1 < len(low) and self._tok_eq(want[i], low[j + 1]):
                i += 1
                j += 2
            else:
                i += 1
                j += 1
        consumed = i
        aligned = hits >= max(1, int(consumed * 0.5)) and consumed >= min(
            len(want), 2)
        if not aligned:
            return text, 0, False
        return " ".join(head[j:]), consumed, True

    def decode_pass(self, abort_cb=None) -> list[str]:
        """One rolling decode. Returns sentences that just became final."""
        with self._lock:
            if self._buf.size < self.min_samples:
                return []
            snapshot = self._buf.copy()
            self._since_decode = 0
        if snapshot.size > self.soft_cap_s * self.sample_rate:
            # Stalled: nothing has committed for this long. The drain is the
            # stall handler, so it must run BEFORE the alignment gate below —
            # gating first meant an unaligned decode returned early, the drain
            # never fired, and commits froze permanently (run 9: 78.7%).
            return self._drain_old(snapshot, abort_cb)
        audio = np.concatenate([snapshot, self.pad])
        kwargs = {"language": self.language}
        if abort_cb is not None:
            kwargs["abort_callback"] = abort_cb
        _tail = " ".join(" ".join(self.all_committed).split()[-12:])
        # gated: fragments poison conversational decodes (measured −2 pts on
        # AMI); only a tail ending at a sentence boundary is fed forward
        if _tail and _tail.rstrip()[-1:] in ".!?":
            kwargs["initial_prompt"] = _tail
        segs = self.model.transcribe(audio, **kwargs)
        raw = compact(" ".join(s.text for s in segs))
        self._last_raw = raw
        text, _, aligned = self._strip_untrimmed(raw)
        self.decodes += 1
        if not aligned:
            # The ledger words are in this audio but the decode re-phrased them
            # beyond reconciliation. Committing now would duplicate them; wait
            # for a cleaner decode (the drain resolves true stalls).
            return []
        if not text:
            return []

        edge = snapshot.size - int(EDGE_GUARD_S * self.sample_rate)
        tail_hot = bool(segs) and int(segs[-1].t1 * T_UNITS * self.sample_rate) >= edge
        newly = self.committer.update(text, allow_tail_commit=not tail_hot)
        # Event-only "sentences" are dropped from the RETURNED commits and
        # the transcript — but they must still enter the ledger and drive
        # the trim, or the word-walk desyncs from committer.committed and
        # the event audio squats in the buffer (review 2026-09-01, #1).
        speech = [x for x in newly if not _is_event_only(x)]
        self.all_committed.extend(speech)
        for sentence in newly:
            self.untrimmed.extend(sentence.split())
        if newly:
            self._trim(segs, snapshot.size)
        self.pending = self.committer.pending(text)
        return speech

    def _drain_old(self, snapshot, abort_cb=None) -> list[str]:
        span = snapshot[: int(self.soft_cap_s * self.sample_rate)]
        kwargs = {"language": self.language}
        if abort_cb is not None:
            kwargs["abort_callback"] = abort_cb
        _tail = " ".join(" ".join(self.all_committed).split()[-12:])
        # gated: fragments poison conversational decodes (measured −2 pts on
        # AMI); only a tail ending at a sentence boundary is fed forward
        if _tail and _tail.rstrip()[-1:] in ".!?":
            kwargs["initial_prompt"] = _tail
        segs = self.model.transcribe(np.concatenate([span, self.pad]), **kwargs)
        guard = span.size - int(EDGE_GUARD_S * self.sample_rate)
        keep = []
        cut = 0
        for sg in segs:
            t1 = int(sg.t1 * T_UNITS * self.sample_rate)
            if t1 >= guard:
                break
            piece = compact(sg.text)
            if piece:
                keep.append(piece)
            cut = t1
        edge_words: list[str] = []
        if cut <= 0 or not keep:
            # Dense no-pause speech (podcasts) can decode the whole span as ONE
            # segment whose t1 sits past the guard — then no cut point exists,
            # the drain returns empty forever, commits freeze, and the 40s cap
            # fires with sentences still pending (seen live). Cut at the guard
            # and keep all the text; the few words describing the ~1s of audio
            # left behind go on the ledger so the next decode strips them
            # instead of re-committing them.
            keep = [compact(sg.text) for sg in segs if compact(sg.text)]
            if not keep:
                return []
            cut = guard
            # ponytail: positional — last 4 words ~ 1s of speech; the ledger's
            # skip/sub-tolerant walk absorbs the slack either way
            edge_words = compact(" ".join(keep)).split()[-4:]
        raw = compact(" ".join(keep))
        text, consumed, aligned = self._strip_untrimmed(raw)
        if not aligned and self.untrimmed:
            # The ledger words' audio sits at the buffer FRONT, inside the span
            # being cut — it is gone either way. If the re-decode cannot be
            # aligned word-for-word, drop their re-decode POSITIONALLY instead:
            # roughly the first len(ledger) words of the span correspond to that
            # audio, whatever the model renamed them to. Leaving the ledger
            # populated after the cut froze every later commit (coverage fell
            # to 78.7% in jfk_regression run 9).
            head = raw.split()
            text = " ".join(head[min(len(self.untrimmed), len(head)):])
        with self._lock:
            if self.on_commit_audio is not None and cut > 0:
                try:
                    self.on_commit_audio(self._buf[:cut].copy())
                except Exception:
                    pass
            self._buf = self._buf[cut:]
        # Whatever the alignment said, the cut removed the front of the buffer,
        # which is where every ledger word's audio lived. The ledger is settled
        # — except a guard-cut, whose edge words' audio stays behind.
        self.untrimmed = edge_words
        self.committer = SentenceCommitter(stable_passes=self.stable_passes)
        # Event-only drain text is dropped EVERYWHERE — returning it while
        # excluding it from the transcript split the two (review, #4).
        if not text or _is_event_only(text):
            return []
        self.all_committed.append(text)
        return [text]

    def _trim(self, segs, snapshot_size: int) -> None:
        """Cut committed audio at the last segment that verifiably lies inside
        the committed text. feed() only appends, so the snapshot's front is
        still the buffer's front and the cut index stays valid under concurrency.

        Consumption is by WORD COUNT, not verification. A per-segment fuzzy
        verification was tried and made 30% of trims cut nothing under ordinary
        re-phrasing drift — committed audio then piled up un-trimmed and the
        drain re-committed whole passages (17% duplication in jfk_regression).
        The failure the verification guarded against (cutting past the committed
        text on an inflated final t1) is already prevented by the edge guard,
        and boundary fuzz is handled by the untrimmed-words ledger.
        """
        # Everything this window has committed is re-hearable until cut, so it
        # ALL goes on the ledger first; the cut then consumes from the front.
        committed_words = compact(" ".join(self.committer.committed)).split()
        n_total = len(self.untrimmed)
        acc = 0
        cut = 0
        edge = snapshot_size - int(EDGE_GUARD_S * self.sample_rate)
        for sg in segs:
            words = compact(sg.text).lower().split()
            if not words or acc + len(words) > n_total:
                break
            t1_samples = int(sg.t1 * T_UNITS * self.sample_rate)
            if t1_samples >= edge:
                break                    # t1 inflated to the window end — do not
                                         # cut audio we may not have heard yet
            acc += len(words)
            cut = t1_samples
        if self.debug is not None:
            self.debug.append({
                "ev": "trim", "committed": " ".join(committed_words)[-70:],
                "cut_s": round(cut / self.sample_rate, 2),
                "ledger_left": " ".join(self.untrimmed[acc:acc + 8]),
                "segs": [compact(sg.text)[:40] for sg in segs][:6]})
        if cut <= 0:
            return
        cut = min(cut, snapshot_size)
        with self._lock:
            if self.on_commit_audio is not None:
                try:
                    self.on_commit_audio(self._buf[:cut].copy())
                except Exception:
                    pass
            self._buf = self._buf[cut:]
        self.untrimmed = self.untrimmed[acc:]
        self.committer = SentenceCommitter(stable_passes=self.stable_passes)

    def flush(self, abort_cb=None) -> list[str]:
        """End of turn: decode whatever remains, then release the tail.

        The edge guard does not apply here — the speaker has stopped, the
        buffer ends in real trailing silence, and committer.flush() releases
        the tail regardless.

        A buffer past the soft cap drains only its front span per pass, so
        flushing after ONE pass would drop everything behind the span. Drain
        until the buffer is under the cap, then decode the remainder.
        """
        newly: list[str] = []
        while self.buffer_seconds > self.soft_cap_s:
            got = self.decode_pass(abort_cb=abort_cb)
            newly += got
            if not got:
                break                       # no progress — do not spin
        final_newly = self.decode_pass(abort_cb=abort_cb)
        newly += final_newly
        # A complete endpoint decode may remove the punctuation present in its
        # previews. Sentence indexes then collapse, so reconcile by the words
        # whose audio is still buffered and keep the authoritative final tail.
        if final_newly:
            left = self.committer.flush()
        else:
            final_tail, _, aligned = self._strip_untrimmed(
                self._last_raw, include_tracked=True)
            left = ([compact(final_tail)] if aligned and compact(final_tail)
                    else self.committer.flush())
        self.all_committed.extend(left)
        if left and self.on_commit_audio is not None:
            with self._lock:
                tail_audio = self._buf.copy()
            if tail_audio.size:
                try:
                    self.on_commit_audio(tail_audio)
                except Exception:
                    pass
        self.pending = ""
        return newly + left

    def finalize_cached(self, *, decode_produced_commits: bool = False
                        ) -> list[str]:
        """Finalize a probable-end decode without re-decoding added silence.

        Valid only when endpointing confirms no voiced packet followed the
        speculative snapshot. If no usable snapshot exists, use normal flush.
        """
        if not self._last_raw:
            return self.flush()
        if decode_produced_commits:
            left = self.committer.flush()
        else:
            final_tail, _, aligned = self._strip_untrimmed(
                self._last_raw, include_tracked=True)
            left = ([compact(final_tail)] if aligned and compact(final_tail)
                    else self.committer.flush())
        self.all_committed.extend(left)
        self.pending = ""
        return left

    def hard_flush(self) -> list[str]:
        """Cap backstop: speech that never finishes a sentence. Never silent."""
        left = self.committer.flush()
        self.all_committed.extend(left)
        self.reset_audio()
        return left

    def reset_audio(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
            self._since_decode = 0
        self.committer = SentenceCommitter(stable_passes=self.stable_passes)
        self.pending = ""
        self.untrimmed = []
        self._last_raw = ""

    def reset(self) -> None:
        """New turn: clear everything including the committed text."""
        self.reset_audio()
        self.all_committed = []
        self.decodes = 0

SAMPLE_RATE = 16000

# ═════════════════════════════════════════════════════════════════════════
# end vendored engine
# ═════════════════════════════════════════════════════════════════════════

DECODE_EVERY_S = 1.5


class StreamGovernor:
    """Decides, per frame, whether the engine should decode, flush, or wait.

    The stability tax (work-ratio 5-9x on oratory) came from decoding on a
    blind timer. Two observations fix most of it:

    * SILENCE CARRIES NO WORDS. If nothing above the energy floor arrived
      since the last decode, a pass cannot commit anything new — skip it.
    * A PAUSE IS A FREE COMMIT. After ~600 ms of quiet, the tail is as
      stable as it will ever get: flush once, commit it, TRIM the buffer.
      Conversational speech pauses constantly, so the buffer stays short
      and every second is decoded only a couple of times.

    Still monotonic: the flush is one decode of the remaining tail, not a
    re-decode of committed audio.
    """

    def __init__(self, floor: float = 0.008, cadence_s: float = DECODE_EVERY_S,
                 flush_after_silence_s: float = 1.0, frame_s: float = 0.03,
                 stale_commit_s: float = 8.0, stale_buffer_s: float = 15.0):
        self.floor = floor
        self.cadence = cadence_s
        self.flush_frames = max(1, int(flush_after_silence_s / frame_s))
        self._speech_since_decode = False
        self._silent_run = 0
        self._last_decode = 0.0
        # Bounded staleness: if the engine keeps decoding but COMMITS nothing
        # for this long, the stability rule is starving (long sentences churn
        # forever) and content is at risk. Force one flush-and-trim: a
        # possible seam error at the boundary beats wholesale omission.
        # Keyed on commit drought, not buffer length — the soft-cap-12
        # experiment proved a length cap guillotines healthy long sentences
        # (it regressed BOTH clean speakers).
        self.stale_commit_s = stale_commit_s
        # Drought ALONE cannot distinguish starvation from a healthy long
        # sentence mid-stabilisation — measured: drought-8s cut the healthy
        # speaker from 3.7% to 22.2% WER. The discriminator is the buffer:
        # healthy commits TRIM it, starvation lets it march toward the cap.
        # Staleness fires only when drought AND a long buffer coincide.
        self.stale_buffer_s = stale_buffer_s
        self._last_commit = 0.0

    def observe(self, frame: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(np.square(frame))))
        if rms >= self.floor:
            self._speech_since_decode = True
            self._silent_run = 0

        else:
            self._silent_run += 1

    def note_commits(self, n: int, now: float) -> None:
        """The loop reports commit counts so drought can be measured."""
        if n:
            self._last_commit = now

    def action(self, now: float, undecoded_s: float, has_pending: bool,
               buffer_s: float = 0.0) -> str:
        """-> 'decode' | 'flush' | 'wait'."""
        if not self._last_commit:
            self._last_commit = now          # arm on first observation
        if (has_pending
                and buffer_s >= self.stale_buffer_s
                and now - self._last_commit >= self.stale_commit_s):
            self._last_commit = now          # re-arm either way
            self._last_decode = now
            self._speech_since_decode = False
            return "flush"
        if self._silent_run >= self.flush_frames:
            if has_pending or (self._speech_since_decode and undecoded_s > 0.2):
                self._speech_since_decode = False
                self._last_decode = now
                return "flush"
            return "wait"                    # quiet room, nothing owed
        if (now - self._last_decode >= self.cadence
                and self._speech_since_decode and undecoded_s >= 1.0):
            self._speech_since_decode = False
            self._last_decode = now
            return "decode"
        return "wait"


# ═══════════════════════════════════════════════════════════════════════════
# section: structured context — BAKED IN (2026-09-01). Turn-based can be
# structure-blind because silence hands it clean units; streaming has no
# gift-wrapped units, so speaker/prosody context is part of the pipeline,
# not an addon. v2 fingerprint vendored from the turn family (pitch-first
# weighted distance — v1 cosine measured 0.990–0.998 between DIFFERENT
# live voices and never split anyone).
# ═══════════════════════════════════════════════════════════════════════════
class StreamAnnotator:
    """Per-commit speaker + prosody from the committed audio span."""

    _FP_SCALE = np.asarray([0.25, 0.08, 0.40, 0.80, 0.30], dtype=np.float32)
    _FP_W = np.asarray([3.0, 1.0, 1.0, 0.5, 0.5], dtype=np.float32)

    def __init__(self, max_speakers: int = 4, new_speaker_dist: float = 1.0):
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        self.max_speakers = max_speakers
        self.new_speaker_dist = new_speaker_dist
        self.last: dict | None = None

    @staticmethod
    def fingerprint(audio: np.ndarray) -> tuple[np.ndarray, dict]:
        x = np.asarray(audio, dtype=np.float32).reshape(-1)
        frames = x[: len(x) // 480 * 480].reshape(-1, 480)
        if not len(frames):
            v = np.asarray([np.log2(150.0), 0.1, 1.0, 2.0, 0.0],
                           dtype=np.float32)
            return v, {"pitch_hz": 0.0, "energy_db": -90.0}
        rms = np.sqrt((frames ** 2).mean(axis=1))
        voiced = frames[rms > max(0.01, np.percentile(rms, 60))]
        if len(voiced) < 4:
            voiced = frames
        zcrs, cents, rolls, pitches = [], [], [], []
        for fr in voiced[:100]:
            zcrs.append(float(np.mean(np.abs(np.diff(np.sign(fr))) > 0)))
            spec = np.abs(np.fft.rfft(fr * np.hanning(len(fr))))
            freqs = np.fft.rfftfreq(len(fr), 1 / 16000)
            cents.append(float((spec * freqs).sum() / max(spec.sum(), 1e-9)))
            cum = np.cumsum(spec)
            rolls.append(float(freqs[int(np.searchsorted(cum, 0.85 * cum[-1]))]))
            ac = np.correlate(fr, fr, "full")[len(fr) - 1:]
            lo, hi = 16000 // 400, 16000 // 70
            if hi > lo:
                pitches.append(float(16000 / (lo + int(np.argmax(ac[lo:hi])))))
        p = np.asarray(pitches if pitches else [150.0], dtype=np.float32)
        p_med = float(np.median(p))
        spread = float(np.log2(max(np.percentile(p, 90), 1.0)
                               / max(np.percentile(p, 10), 1.0)))
        v = np.asarray([np.log2(max(p_med, 1.0)), float(np.mean(zcrs)),
                        float(np.mean(cents)) / 1000.0,
                        float(np.mean(rolls)) / 1000.0, spread],
                       dtype=np.float32)
        pros = {"pitch_hz": round(p_med, 1),
                "energy_db": round(20 * float(np.log10(
                    np.sqrt((x ** 2).mean()) + 1e-9)), 1)}
        return v, pros

    @classmethod
    def _dist(cls, a, b) -> float:
        z = (a - b) / cls._FP_SCALE
        return float(np.sqrt(float((cls._FP_W * z * z).sum())
                     / float(cls._FP_W.sum())))

    def label(self, audio: np.ndarray) -> dict:
        v, pros = self.fingerprint(audio)
        self.last_fp = v
        if not self.centroids:
            self.centroids.append(v)
            self.counts.append(1)
            self.last = {"speaker": 1, "conf": 1.0, **pros}
            return self.last
        self.last_fp = v
        dists = [self._dist(v, c) for c in self.centroids]
        best = int(np.argmin(dists))
        d = dists[best]
        if d <= self.new_speaker_dist or len(self.centroids) >= self.max_speakers:
            n = self.counts[best]
            self.centroids[best] = (self.centroids[best] * n + v) / (n + 1)
            self.counts[best] += 1
            self.last = {"speaker": best + 1,
                         "conf": round(1.0 / (1.0 + d), 3), **pros}
        else:
            self.centroids.append(v)
            self.counts.append(1)
            self.last = {"speaker": len(self.centroids), "conf": 1.0, **pros}
        return self.last


DRIFT_MIN_BUFFER_S = 6.0     # the discriminator that made it a clean sweep
DRIFT_CHECK_EVERY_S = 0.6
DRIFT_WIN_S = 1.2
DRIFT_CONFIRM = 2


class DriftAnchor:
    """Benchmarked 2026-09-01 (vcflush/vcconfirm, large-v3-turbo, normalized
    WER): flush when the buffer's acoustics drift past the speaker-boundary
    distance — but only once the buffer exceeds 6 s. Improved or tied EVERY
    measured stream: 576@120s 33.6->19.6, 210@120s 27.7->19.6, AMI#1 tie
    (0 fires), AMI#2 47.1->41.4 — the first engine change in six attempts
    with no losing content class. Without the 6 s floor the same rule
    REGRESSED 210@120 (+2.7): short buffers don't need breaking.
    Mechanism: NOT speaker detection — long buffers are where overlapping
    decodes stop converging, and acoustic drift marks a safe break point."""

    def __init__(self) -> None:
        self._anchor = None
        self._hits = 0
        self._last = -1.0

    def should_flush(self, eng, now: float) -> bool:
        if now - self._last < DRIFT_CHECK_EVERY_S:
            return False
        self._last = now
        with eng._lock:
            buf = eng._buf.copy()
        w = int(DRIFT_WIN_S * eng.sample_rate)
        if buf.size < max(int(DRIFT_MIN_BUFFER_S * eng.sample_rate), 2 * w):
            self._anchor = None
            self._hits = 0
            return False
        if self._anchor is None:
            self._anchor, _ = StreamAnnotator.fingerprint(buf[:w])
        v, _ = StreamAnnotator.fingerprint(buf[-w:])
        if StreamAnnotator._dist(v, self._anchor) > 1.0:
            self._hits += 1
            if self._hits >= DRIFT_CONFIRM:
                self.reset()
                return True
        else:
            self._hits = 0
        return False

    def reset(self) -> None:
        self._anchor = None
        self._hits = 0



FRAME_MS = 30                     # the family frame size (03's capture const)

def sentence_turn(text: str, label: dict | None) -> dict:
    """A committed sentence + its StreamAnnotator label, shaped like the
    turn records the context-line/policy layer already understands."""
    label = label or {}
    complete = bool(re.search(r"[.!?][\"')\]]*$", text.strip()))
    return {
        "text": text,
        "speaker": label.get("speaker", 0),
        "speaker_conf": label.get("conf", 0.0),
        "complete": complete,
        "holding": not complete,
        "question": text.strip().endswith("?"),
        "prosody": {k: label[k] for k in ("pitch_hz", "energy_db")
                    if k in label},
    }


class UtteranceAggregator:
    """The full-duplex 'turn': assembled from monotonic commits, not from
    endpointed audio. Cleared when a reply consumes it."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def push(self, turn: dict) -> None:
        self.items.append(turn)
        if len(self.items) > 12:             # hard bound (review, #2)
            self.items = self.items[-12:]

    def text(self) -> str:
        return " ".join(t["text"] for t in self.items)

    def turns(self) -> list[dict]:
        return self.items

    def wake(self):
        return match_wake(self.items[-1]["text"]) if self.items else None

    def clear(self) -> None:
        self.items = []


__all__ = [
    "_is_event_only",
    "split_sentences",
    "SentenceCommitter",
    "compact",
    "IncrementalTranscriber",
    "StreamGovernor",
    "StreamAnnotator",
    "DriftAnchor",
    "sentence_turn",
    "UtteranceAggregator",
    "_BRACKETED_RE",
    "_SENTENCE_END",
    "_ABBREV",
    "STABLE_PASSES",
    "MIN_COMMIT_CHARS",
    "SAMPLE_RATE",
    "T_UNITS",
    "EDGE_GUARD_S",
    "DECODE_EVERY_S",
    "DRIFT_MIN_BUFFER_S",
    "DRIFT_CHECK_EVERY_S",
    "DRIFT_WIN_S",
    "DRIFT_CONFIRM",
    "FRAME_MS",
]
