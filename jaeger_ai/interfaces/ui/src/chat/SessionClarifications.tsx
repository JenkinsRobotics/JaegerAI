/** Pending server questions survive navigation and reload through the Gateway session owner. */
import { useEffect, useRef, useState } from "react";
import type { ClarificationSnapshot } from "../api/source";
import type { ChatHost } from "./host";
import { QuestionCard } from "./ApprovalCard";
import { clarificationAnswerKey } from "./clarificationAnswers";
import type { ClarifyAnswerResult } from "./host";

type Host = Pick<ChatHost, "clarifications" | "answerClarify">;

export function SessionClarifications({ sessionId, host, excludeIds = [] }: {
  sessionId: string; host: Host; excludeIds?: string[];
}) {
  const [rows, setRows] = useState<ClarificationSnapshot[]>([]);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState<string>();
  const deciding = useRef(new Set<string>());
  const generation = useRef(0);

  useEffect(() => {
    const owner = ++generation.current;
    let active = true;
    if (!host.clarifications) return () => { active = false; };
    void host.clarifications(sessionId).then((forms) => {
      if (!active || generation.current !== owner) return;
      setRows(forms.filter((form) => form.session_id === sessionId && form.clarify_id && Number.isInteger(form.revision) && form.revision > 0));
      setError(undefined);
    }, (reason) => {
      if (active && generation.current === owner) setError(String((reason as Error)?.message ?? reason));
    });
    return () => { active = false; generation.current++; };
  }, [host, sessionId]);

  const answer = async (form: ClarificationSnapshot, response: string): Promise<ClarifyAnswerResult> => {
    if (!host.answerClarify) throw new Error("Clarification answers are unavailable");
    if (deciding.current.has(form.clarify_id)) throw new Error("Clarification answer is already in progress");
    deciding.current.add(form.clarify_id);
    setBusy(form.clarify_id);
    const owner = generation.current;
    try {
      const result = await host.answerClarify(sessionId, form.clarify_id, form.revision, response);
      // The transcript can temporarily own this card while SSE catches up.
      // Keep the acknowledged outcome in its session owner, so remounting the
      // card cannot reopen a question the Gateway has already resolved.
      if (generation.current === owner) setRows(current => current.map(row =>
        row.clarify_id === form.clarify_id && row.session_id === sessionId && row.revision === form.revision
          ? { ...row, status: result?.status ?? "answered", answer: result?.status === "answered" ? result.answer : result ? null : response }
          : row));
      return result;
    } finally {
      deciding.current.delete(form.clarify_id);
      setBusy(undefined);
    }
  };

  return <div aria-label="Conversation questions" aria-live="polite">
    {error && <p role="alert">Couldn't load or answer question: {error}</p>}
    {rows.filter((form) => !excludeIds.includes(form.clarify_id)).map((form) => <fieldset key={form.clarify_id} disabled={busy === form.clarify_id} style={{ border: 0, padding: 0, margin: 0 }}>
      <QuestionCard title={form.question} options={form.choices.map((label, index) => ({ id: `c${index}`, label }))}
        answerKey={clarificationAnswerKey(form.clarify_id, form.revision)}
        answer={form.answer} status={form.status}
        onAnswer={form.status === "pending" && host.answerClarify ? (response) => answer(form, response) : undefined} />
    </fieldset>)}
  </div>;
}
