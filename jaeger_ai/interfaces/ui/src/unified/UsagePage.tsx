/**
 * Models › Usage: sessions, messages, tokens and cost per model from GET /v1/usage (the WebUI's
 * local session analytics). Token columns are only shown as numbers when the provider reported
 * them; otherwise the page says "not metered" instead of printing zeros as if they were real.
 */
import { useEffect, useState } from "react";
import { Badge, Empty, Segmented, SkeletonRows, Sparkline, PageHead } from "./ui";
import { getJson } from "./webui";
import "./usage.css";

export type UsageModel = { model: string; sessions: number; input_tokens: number; output_tokens: number; total_tokens: number; cost: number; session_share: number };
export type Usage = { period_days: number; total_sessions: number; total_messages: number; total_tokens: number; total_cost: number; models: UsageModel[]; daily_tokens: { date: string; sessions: number; input_tokens: number; output_tokens: number }[] };

export const metered = (u: Pick<Usage, "total_tokens">) => u.total_tokens > 0;
export const fmtNum = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);

export function UsagePage() {
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const [u, setU] = useState<Usage | null>(null); const [err, setErr] = useState<string>();
  useEffect(() => { let live = true; setU(null); getJson<Usage>(`/v1/usage?days=${days}`).then((r) => live && (setU(r), setErr(undefined)), (e: Error) => live && setErr(e.message)); return () => { live = false; }; }, [days]);
  const m = u ? metered(u) : false;
  return (
    <div className="jg-u-page">
      <PageHead embedded title="Usage" subtitle="Sessions and tokens per model, from this Mac's WebUI sessions."
        actions={<Segmented label="Period" value={days} onChange={setDays} options={[{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }]} />} />
      {err ? <Empty title="Usage unavailable">{err}</Empty> : !u ? <SkeletonRows n={5} /> : <>
        <dl className="jg-ui-kv">
          <dt>Sessions</dt><dd>{u.total_sessions}</dd>
          <dt>Messages</dt><dd>{u.total_messages}</dd>
          <dt>Tokens</dt><dd>{m ? fmtNum(u.total_tokens) : <Badge tone="warn">Not metered by these providers</Badge>}</dd>
          <dt>Cost</dt><dd>{m ? `$${u.total_cost.toFixed(2)}` : "–"}</dd>
        </dl>
        <Sparkline label={`Sessions per day, last ${u.period_days} days`} values={u.daily_tokens.map((d) => d.sessions)} />
        {u.models.length === 0 ? <Empty title="No sessions in this period" /> :
          <table className="jg-u-table"><thead><tr><th scope="col">Model</th><th scope="col">Sessions</th><th scope="col">Share</th><th scope="col">Tokens</th><th scope="col">Cost</th></tr></thead>
            <tbody>{u.models.map((r) => <tr key={r.model}><td>{r.model === "unknown" ? <span title="Older sessions did not record their model">Unrecorded model</span> : r.model}</td><td>{r.sessions}</td><td>{r.session_share}%</td><td>{r.total_tokens ? fmtNum(r.total_tokens) : "–"}</td><td>{r.total_tokens ? `$${r.cost.toFixed(2)}` : "–"}</td></tr>)}</tbody></table>}
      </>}
    </div>
  );
}
