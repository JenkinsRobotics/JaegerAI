/** Talk to a character on a local model, with its long-term memory (J-070). */
import { useState } from "react";
import { companionApi, type CompanionTurn } from "./companion";

export function CompanionChat({ characterId, name }: { characterId: string; name: string }) {
  const [turns, setTurns] = useState<CompanionTurn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const send = async () => {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true); setError(""); setText("");
    const history = turns;
    setTurns([...history, { role: "user", content: message }]);
    try {
      const r = await companionApi.chat(characterId, message, history);
      setTurns((t) => [...t, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The local model didn't answer.");
    } finally { setBusy(false); }
  };

  const exportCard = async () => {
    const card = await companionApi.card(characterId);
    const url = URL.createObjectURL(new Blob([JSON.stringify(card, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `${characterId}.ccv3.json`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="detail-section companion-chat" aria-label={`Talk to ${name}`}>
      <h4>Talk to {name}</h4>
      <div className="companion-log" role="log" aria-live="polite">
        {turns.map((t, i) => <p key={i} className={`companion-turn ${t.role}`}><strong>{t.role === "user" ? "You" : name}:</strong> {t.content}</p>)}
        {busy && <p className="companion-turn assistant">{name} is thinking…</p>}
      </div>
      {error && <p className="companion-error" role="alert">{error}</p>}
      <form onSubmit={(e) => { e.preventDefault(); void send(); }} className="companion-input">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={`Say something to ${name}`} aria-label="Message" maxLength={4000} />
        <button type="submit" disabled={busy || !text.trim()}>Send</button>
        <button type="button" onClick={() => void exportCard()}>Export card</button>
      </form>
    </div>
  );
}
