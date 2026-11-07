import { createContext, useContext, useState, type ReactNode } from "react";
import type { ClarifyAnswerResult } from "./host";

const Answers = createContext<{
  outcomes: Record<string, ClarifyAnswerResult>;
  record(key: string, result: ClarifyAnswerResult): void;
} | undefined>(undefined);

/** Acknowledged Gateway outcomes belong to the conversation, not either card renderer. */
export function ClarificationAnswers({ children }: { children: ReactNode }) {
  const [outcomes, setOutcomes] = useState<Record<string, ClarifyAnswerResult>>({});
  return <Answers.Provider value={{ outcomes, record: (key, result) => setOutcomes(current => ({ ...current, [key]: result })) }}>{children}</Answers.Provider>;
}

export const clarificationAnswerKey = (id: string, revision: number) => JSON.stringify([id, revision]);
export const useClarificationAnswers = () => useContext(Answers);
