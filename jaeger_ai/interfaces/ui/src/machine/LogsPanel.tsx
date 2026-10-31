/** Machine › Logs: tail of one Jaeger log (whitelisted sources, secrets redacted server-side), with level filter, search and follow. */
import { useCallback, useEffect, useRef, useState } from "react";
import { Empty, Segmented, SkeletonRows } from "../unified/ui";
import { getJson } from "../unified/webui";
import { logsUrl, type LogSource, type LogTail } from "./machineData";
import "./machine.css";

type Level = "" | "error" | "warn" | "info";

export function LogsPanel() {
  const [sources, setSources] = useState<LogSource[]>([]);
  const [src, setSrc] = useState("gateway"); const [level, setLevel] = useState<Level>(""); const [q, setQ] = useState(""); const [follow, setFollow] = useState(true);
  const [tail, setTail] = useState<LogTail | null>(null); const [err, setErr] = useState<string>();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { getJson<{ sources: LogSource[] }>("/v1/machine/logs/sources").then((r) => setSources(r.sources), (e: Error) => setErr(e.message)); }, []);
  const read = useCallback(() => getJson<LogTail>(logsUrl(src, { q, level, lines: 400 })).then((t) => { setTail(t); setErr(undefined); }, (e: Error) => setErr(e.message)), [src, q, level]);
  useEffect(() => { setTail(null); void read(); }, [read]);
  useEffect(() => { if (!follow) return; const t = setInterval(() => { if (!document.hidden) void read(); }, 5000); return () => clearInterval(t); }, [follow, read]);
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; }, [tail, follow]);
  return (
    <section className="jg-mc-card jg-mc-logs" aria-label="Logs">
      <div className="jg-ui-toolbar">
        <label className="jg-ui-field">Source
          <select className="jg-ui-input" value={src} onChange={(e) => setSrc(e.target.value)}>{(sources.length ? sources : [{ id: "gateway", exists: true, bytes: 0, mtime: null }]).map((s) => <option key={s.id} value={s.id} disabled={!s.exists}>{s.id}{s.exists ? "" : " (none yet)"}</option>)}</select>
        </label>
        <Segmented label="Level" value={level} onChange={setLevel} options={[{ value: "", label: "All" }, { value: "error", label: "Errors" }, { value: "warn", label: "Warnings" }, { value: "info", label: "Info" }]} />
        <input className="jg-ui-input" type="search" aria-label="Search log" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="jg-u-btn" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? "Pause" : "Follow"}</button>
        <button className="jg-u-btn" onClick={() => void navigator.clipboard?.writeText((tail?.lines ?? []).map((l) => l.text).join("\n"))}>Copy</button>
      </div>
      {err ? <Empty title="Logs unavailable">{err}</Empty> : !tail ? <SkeletonRows n={8} /> : !tail.exists ? <Empty title="No log yet">{src} hasn't written a log file.</Empty> :
        tail.lines.length === 0 ? <Empty title="No matching lines" /> :
        <div ref={box} className="jg-mc-logbox" role="log" aria-live="off" tabIndex={0}>{tail.lines.map((l, i) => <div key={i} className="jg-mc-logline" data-level={l.level}>{l.text}</div>)}</div>}
      {tail?.truncated && <p className="jg-mc-note">Showing the latest {tail.lines.length} lines.</p>}
    </section>
  );
}
