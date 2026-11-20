/** Talk to a character on a local model, with streaming barge-in and Character Council (J-070). */
import { useEffect, useRef, useState } from "react";
import { companionApi, type CompanionTurn, type CouncilReply } from "./companion";

export interface CompanionPeer {
  id: string;
  name: string;
}

export type CompanionPresence = "idle" | "listening" | "speaking";

export function CompanionChat({
  characterId,
  name,
  peers = [],
}: {
  characterId: string;
  name: string;
  peers?: CompanionPeer[];
}) {
  const [mode, setMode] = useState<"single" | "council">("single");
  const [turns, setTurns] = useState<CompanionTurn[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [councilReplies, setCouncilReplies] = useState<CouncilReply[]>([]);
  const [selectedPeers, setSelectedPeers] = useState<string[]>([]);
  const [includeTruthSynthesis, setIncludeTruthSynthesis] = useState(true);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [presence, setPresence] = useState<CompanionPresence>("idle");
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const otherPeers = peers.filter((p) => p.id !== characterId);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const togglePeer = (peerId: string) => {
    setSelectedPeers((prev) =>
      prev.includes(peerId)
        ? prev.filter((id) => id !== peerId)
        : prev.length < 5
          ? [...prev, peerId]
          : prev,
    );
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
  };

  const sendSingle = async (message: string) => {
    const history = turns;
    setTurns([...history, { role: "user", content: message }]);
    setStreamingText("");
    setPresence("speaking");
    const controller = new AbortController();
    abortRef.current = controller;
    let partial = "";
    try {
      const r = await companionApi.stream(characterId, message, history, {
        signal: controller.signal,
        onDelta: (delta) => {
          partial += delta;
          setStreamingText(partial);
        },
      });
      const replyText = r.reply || partial;
      setTurns((t) => [...t, { role: "assistant", content: replyText }]);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        if (partial.trim()) {
          setTurns((t) => [...t, { role: "assistant", content: `${partial.trim()} [interrupted]` }]);
        }
      } else {
        setError(e instanceof Error ? e.message : "The local model didn't answer.");
      }
    } finally {
      abortRef.current = null;
      setStreamingText("");
      setPresence("idle");
      setBusy(false);
    }
  };

  const sendCouncil = async (topic: string) => {
    const members = [characterId, ...selectedPeers];
    if (members.length < 2) {
      setError("Select at least one additional character for a Council.");
      setBusy(false);
      setPresence("idle");
      return;
    }
    setPresence("speaking");
    try {
      const reply = await companionApi.council(members, topic, {
        history: turns,
        includeTruthSynthesis,
      });
      setCouncilReplies((prev) => [...prev, reply]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Council request failed.");
    } finally {
      setPresence("idle");
      setBusy(false);
    }
  };

  const send = async () => {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true);
    setError("");
    setText("");
    if (mode === "council") {
      await sendCouncil(message);
    } else {
      await sendSingle(message);
    }
  };

  const exportCard = async () => {
    const card = await companionApi.card(characterId);
    const url = URL.createObjectURL(new Blob([JSON.stringify(card, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${characterId}.ccv3.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const effectivePresence: CompanionPresence =
    busy ? presence : text.trim().length > 0 ? "listening" : "idle";

  return (
    <div
      className="detail-section companion-chat"
      aria-label={`Talk to ${name}`}
      data-presence={effectivePresence}
    >
      <div className="companion-header">
        <h4>Talk to {name}</h4>
        <span className="companion-presence" aria-live="polite">
          {effectivePresence === "speaking"
            ? `${name} speaking…`
            : effectivePresence === "listening"
              ? "Listening…"
              : "Ready"}
        </span>
        {otherPeers.length > 0 && (
          <div className="companion-mode-toggle" role="tablist" aria-label="Conversation mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "single"}
              onClick={() => setMode("single")}
            >
              Direct
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "council"}
              onClick={() => setMode("council")}
            >
              Council
            </button>
          </div>
        )}
      </div>

      {mode === "council" && otherPeers.length > 0 && (
        <div className="companion-council-picker" aria-label="Council members">
          <p className="companion-council-hint">
            Summon additional voices alongside <strong>{name}</strong> (scoped memory, no private tools):
          </p>
          <div className="companion-council-options">
            {otherPeers.map((peer) => (
              <label key={peer.id} className="companion-peer-option">
                <input
                  type="checkbox"
                  checked={selectedPeers.includes(peer.id)}
                  onChange={() => togglePeer(peer.id)}
                />
                <span>{peer.name}</span>
              </label>
            ))}
          </div>
          <label className="companion-truth-toggle">
            <input
              type="checkbox"
              checked={includeTruthSynthesis}
              onChange={(e) => setIncludeTruthSynthesis(e.target.checked)}
            />
            <span>Include Truth epistemic synthesis</span>
          </label>
        </div>
      )}

      <div className="companion-log" role="log" aria-live="polite">
        {mode === "single" ? (
          <>
            {turns.map((t, i) => (
              <p key={i} className={`companion-turn ${t.role}`}>
                <strong>{t.role === "user" ? "You" : name}:</strong> {t.content}
              </p>
            ))}
            {busy && (
              <p className="companion-turn assistant streaming">
                <strong>{name}:</strong> {streamingText || `${name} is thinking…`}
              </p>
            )}
          </>
        ) : (
          <>
            {councilReplies.map((entry, idx) => (
              <div key={idx} className="companion-council-round">
                <p className="companion-turn user">
                  <strong>Topic:</strong> {entry.topic}
                </p>
                {entry.turns.map((turn, tIdx) => (
                  <p key={tIdx} className="companion-turn assistant council-voice">
                    <strong>{turn.name}:</strong> {turn.reply}
                  </p>
                ))}
                {entry.truth_synthesis && (
                  <div className="companion-truth-synthesis" aria-label="Truth synthesis">
                    <strong>{entry.truth_synthesis.name} (Epistemic Synthesis):</strong>{" "}
                    {entry.truth_synthesis.reply}
                  </div>
                )}
              </div>
            ))}
            {busy && <p className="companion-turn assistant">Council is deliberating…</p>}
          </>
        )}
      </div>

      {error && (
        <p className="companion-error" role="alert">
          {error}
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="companion-input"
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            mode === "council"
              ? `Ask ${name} and the council a question…`
              : `Say something to ${name}`
          }
          aria-label="Message"
          maxLength={4000}
        />
        {busy && mode === "single" ? (
          <button type="button" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={busy || !text.trim()}>
            {mode === "council" ? "Convene" : "Send"}
          </button>
        )}
        <button type="button" onClick={() => void exportCard()}>
          Export card
        </button>
      </form>
    </div>
  );
}
