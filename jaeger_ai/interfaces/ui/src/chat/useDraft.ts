import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { readDraft, writeDraft, type Draft } from "./drafts";
import type { PendingFile } from "./composer";
const empty: Draft = { text: "", files: [] };
export function useDraft(sessionId?: string) {
  const [state, setState] = useState<{ owner?: string; value: Draft; ready: boolean; error?: string }>({ value: empty, ready: false });
  useEffect(() => {
    let live = true;
    if (!sessionId) return;
    setState({ owner: sessionId, value: empty, ready: false });
    void readDraft(sessionId).then(value => { if (live) setState({ owner: sessionId, value, ready: true }); }, error => {
      if (live) setState({ owner: sessionId, value: empty, ready: true, error: `Draft recovery unavailable: ${String(error)}` });
    });
    return () => { live = false; };
  }, [sessionId]);
  const ready = state.owner === sessionId && state.ready;
  const update = <K extends keyof Draft>(key: K, change: SetStateAction<Draft[K]>) => {
    if (!sessionId) return;
    setState(s => {
      if (s.owner !== sessionId || !s.ready) return s;
      const value = { ...s.value, [key]: typeof change === "function" ? (change as (old: Draft[K]) => Draft[K])(s.value[key]) : change };
      return { ...s, value };
    });
  };
  useEffect(() => {
    if (!ready || !sessionId || state.error?.startsWith("Draft recovery")) return;
    let live = true;
    void writeDraft(sessionId, state.value).then(() => {
      if (live) setState(s => s.error?.startsWith("Draft not saved") ? { ...s, error: undefined } : s);
    }).catch(error => { if (live) setState(s => ({ ...s, error: `Draft not saved: ${String(error)}` })); });
    return () => { live = false; };
  }, [ready, sessionId, state.value]);
  return {
    draft: ready ? state.value.text : "", quote: ready ? state.value.quote : undefined, files: ready ? state.value.files : [], ready, error: state.error,
    setDraft: ((change: SetStateAction<string>) => update("text", change)) as Dispatch<SetStateAction<string>>,
    setQuote: ((change: SetStateAction<Draft["quote"]>) => update("quote", change)) as Dispatch<SetStateAction<Draft["quote"]>>,
    setFiles: ((change: SetStateAction<PendingFile[]>) => update("files", change)) as Dispatch<SetStateAction<PendingFile[]>>,
  };
}
