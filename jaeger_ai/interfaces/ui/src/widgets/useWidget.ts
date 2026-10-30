/**
 * Widget state machine (Jenkins Robotics, 2026-10-29, original).
 *
 * idle → loading → ready | error. A widget is never "ready" without data from
 * `load()`. There is no cached default and no synthetic value.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { AnyWidgetDef, WidgetDef } from "./types";

export type WidgetState<D> =
  | { status: "loading" }
  | { status: "ready"; data: D; observedAt: number }
  | { status: "error"; error: string };

const message = (error: unknown): string => {
  if (error instanceof Error && error.message) return error.message;
  return String(error ?? "Unknown error");
};

/**
 * Run one widget's loader.
 *
 * Dependencies deliberately exclude the definition object (module identity is
 * stable) and include the source so a re-created source re-fetches. `paramsKey`
 * is a JSON string so callers can pass a fresh object literal safely.
 */
export function useWidget<D>(
  def: WidgetDef<never, D> | AnyWidgetDef,
  source: JaegerSource | undefined,
  params: unknown,
): WidgetState<D> & { reload: () => void } {
  const [state, setState] = useState<WidgetState<D>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const live = useRef(true);

  const paramsKey = JSON.stringify(params ?? null);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  useEffect(() => {
    if (!source) {
      setState({ status: "error", error: "No Jaeger source available. The gateway is not connected." });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    void (async () => {
      try {
        const data = (await (def.load as (s: JaegerSource, p: unknown) => Promise<D>)(
          source,
          JSON.parse(paramsKey) ?? undefined,
        )) as D;
        if (cancelled || !live.current) return;
        setState({ status: "ready", data, observedAt: Date.now() });
      } catch (error: unknown) {
        if (cancelled || !live.current) return;
        setState({ status: "error", error: message(error) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [def, source, paramsKey, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
