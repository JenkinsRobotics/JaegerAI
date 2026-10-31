/**
 * Research › YouTube (TAB-03 §4, YT-RESEARCH-UI-SPEC): jobs → videos → video deep view
 * (frames filmstrip, shot notes, on-screen text, transcript, audio), plus the job's knowledge
 * base techniques and style guide. Read-only except Pause/Resume, which the runner already owns.
 * Real data only: every pane shows its pending/empty state instead of placeholder content.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Empty, Segmented, SkeletonRows, useToast } from "../unified/ui";
import { getJson, sendJson } from "../unified/webui";
import { STEP_LABEL, STEP_ORDER, evidence, filterVideos, fmtTime, framePath, jobPath, jobState, pct, videoPath, videoRollup, ytBase,
  type Technique, type YtJob, type YtJobSummary, type YtVideo } from "./youtube";
import "./youtube.css";

type Only = "all" | "done" | "pending" | "failed";
type Pane = "videos" | "techniques" | "style";

export function YouTubePage({ params, onNavigate }: { params?: URLSearchParams; onNavigate?: (to: string) => void }) {
  const toast = useToast();
  const [jobs, setJobs] = useState<YtJobSummary[] | null>(null);
  const [err, setErr] = useState<string>();
  const [jobId, setJobId] = useState<string | undefined>(params?.get("job") ?? undefined);
  const [job, setJob] = useState<YtJob | null>(null);
  const [vid, setVid] = useState<string | undefined>(params?.get("video") ?? undefined);
  const [video, setVideo] = useState<YtVideo | null>(null);
  const [q, setQ] = useState(""); const [only, setOnly] = useState<Only>("all"); const [pane, setPane] = useState<Pane>("videos");
  const [tech, setTech] = useState<Technique[] | null>(null); const [style, setStyle] = useState<string | null | undefined>(undefined);

  const loadJobs = useCallback(() => getJson<{ jobs: YtJobSummary[] }>(ytBase).then((r) => { setJobs(r.jobs); setErr(undefined); setJobId((cur) => cur ?? r.jobs[0]?.task_id); }, (e: Error) => setErr(e.message)), []);
  useEffect(() => { void loadJobs(); const t = setInterval(() => { if (!document.hidden) void loadJobs(); }, 15000); return () => clearInterval(t); }, [loadJobs]);
  useEffect(() => {
    if (!jobId) return; let live = true;
    const read = () => getJson<YtJob>(jobPath(jobId)).then((r) => live && setJob(r), (e: Error) => live && setErr(e.message));
    void read(); const t = setInterval(() => { if (!document.hidden) void read(); }, 15000);
    return () => { live = false; clearInterval(t); };
  }, [jobId]);
  useEffect(() => { if (!jobId || !vid) { setVideo(null); return; } let live = true; setVideo(null);
    getJson<YtVideo>(videoPath(jobId, vid)).then((r) => live && setVideo(r), (e: Error) => live && toast(`Video: ${e.message}`)); return () => { live = false; }; }, [jobId, vid, toast]);
  useEffect(() => {
    if (pane === "techniques" && tech === null) getJson<{ techniques: Technique[] }>(`${ytBase}/techniques`).then((r) => setTech(r.techniques), () => setTech([]));
    if (pane === "style" && jobId && style === undefined) getJson<{ style_guide?: string; markdown?: string; text?: string }>(`${jobPath(jobId)}/style-guide`).then((r) => setStyle(r.markdown ?? r.style_guide ?? r.text ?? null), () => setStyle(null));
  }, [pane, tech, style, jobId]);

  const togglePause = async () => {
    if (!job) return;
    try { await sendJson("POST", `${jobPath(job.task_id)}/${job.paused ? "resume" : "pause"}`, {}); toast(job.paused ? "Resumed" : "Paused: running steps finish, no new ones start"); setJob({ ...job, paused: !job.paused }); }
    catch (e) { toast(String((e as Error).message ?? e)); }
  };
  const rows = useMemo(() => filterVideos(job?.videos ?? [], q, only), [job, q, only]);
  const pick = (id?: string) => { setVid(id); onNavigate?.(`/research/youtube?${new URLSearchParams({ ...(jobId ? { job: jobId } : {}), ...(id ? { video: id } : {}) })}`); };

  if (err && !jobs) return <Empty title="YouTube research unavailable">{err}</Empty>;
  if (!jobs) return <SkeletonRows n={4} />;
  if (!jobs.length) return <Empty title="No YouTube research yet">Start a playlist job from Chat or the API; it shows up here with live progress.</Empty>;
  const st = job ? jobState(job) : undefined;

  return (
    <div className="jg-yt" data-detail={vid ? "video" : "list"}>
      <aside className="jg-yt__jobs" aria-label="Research jobs">
        {jobs.map((j) => { const s = jobState(j); return (
          <button key={j.task_id} className="jg-yt__job" aria-current={j.task_id === jobId ? "true" : undefined} onClick={() => { setJobId(j.task_id); setJob(null); setStyle(undefined); pick(undefined); }}>
            <span className="jg-yt__job-title">{j.playlist_title ?? j.task_id}</span>
            <span className="jg-yt__meter" role="progressbar" aria-valuenow={pct(j.progress)} aria-valuemin={0} aria-valuemax={100} aria-label="Batch progress"><span style={{ width: `${pct(j.progress)}%` }} /></span>
            <Badge tone={s.tone}>{s.label}</Badge>
          </button>); })}
      </aside>

      <section className="jg-yt__main" aria-label="Job">
        {!job ? <SkeletonRows n={5} /> : <>
          <header className="jg-yt__head">
            <div><h2>{job.playlist_title ?? job.task_id}</h2>
              <p className="jg-yt__sub">{job.item_count ?? job.videos.length} videos in playlist · {job.videos.length} in this batch · phase {job.phase ?? "–"} · {job.video_model ?? job.model ?? "on-device models"}</p></div>
            <div className="jg-ui-toolbar">{st && <Badge tone={st.tone}>{st.label}</Badge>}<button className="jg-u-btn" onClick={() => void togglePause()}>{job.paused ? "Resume" : "Pause"}</button>{job.playlist_url && <a className="jg-u-btn" href={job.playlist_url} target="_blank" rel="noreferrer">Open playlist</a>}</div>
          </header>
          <Segmented label="Job view" value={pane} onChange={setPane} options={[{ value: "videos", label: "Videos" }, { value: "techniques", label: "Knowledge base" }, { value: "style", label: "Style guide" }]} />
          {pane === "videos" && <>
            <div className="jg-ui-toolbar jg-yt__filters">
              <input className="jg-ui-input" type="search" placeholder="Search videos" aria-label="Search videos" value={q} onChange={(e) => setQ(e.target.value)} />
              <Segmented label="Filter videos" value={only} onChange={setOnly} options={[{ value: "all", label: "All" }, { value: "done", label: "Analysed" }, { value: "pending", label: "In progress" }, { value: "failed", label: "Failed" }]} />
            </div>
            {rows.length === 0 ? <Empty title="No videos match" /> : <ul className="jg-yt__videos">{rows.map((v) => { const r = videoRollup(v); return (
              <li key={v.id}><button className="jg-yt__video" aria-current={v.id === vid ? "true" : undefined} onClick={() => pick(v.id)}>
                <span className="jg-yt__pos">{(v.position ?? 0) + 1}</span>
                <span className="jg-yt__vt"><span className="jg-yt__vtitle">{v.title}</span><span className="jg-yt__sub">{v.channel} · {fmtTime(v.duration)} · {r.done}/{r.total} steps</span></span>
                <Badge tone={r.tone}>{r.label}</Badge>
              </button></li>); })}</ul>}
          </>}
          {pane === "techniques" && (tech === null ? <SkeletonRows n={3} /> : tech.length === 0
            ? <Empty title="Knowledge base is building">Techniques appear once videos finish the analysis step ({job.progress?.videos_analysed ?? 0} analysed so far).</Empty>
            : <ul className="jg-yt__tech">{tech.map((t, i) => <li key={t.id ?? i}><strong>{t.name}</strong> <Badge>{t.type}</Badge><p>{t.summary}</p></li>)}</ul>)}
          {pane === "style" && (style === undefined ? <SkeletonRows n={3} /> : !style
            ? <Empty title="No style guide yet">It is written after a batch is analysed (status: {job.style_guide ?? "pending"}).</Empty>
            : <pre className="jg-yt__style">{style}</pre>)}
        </>}
      </section>

      <section className="jg-yt__video-pane" aria-label="Video detail">
        {!vid ? <Empty title="Pick a video">Frames, shot notes, on-screen text and the transcript show here.</Empty> : !video ? <SkeletonRows n={6} /> : <VideoDetail jobId={jobId!} v={video} onBack={() => pick(undefined)} />}
      </section>
    </div>
  );
}

function VideoDetail({ jobId, v, onBack }: { jobId: string; v: YtVideo; onBack: () => void }) {
  const [tab, setTab] = useState<"notes" | "transcript" | "steps">("notes");
  const ev = useMemo(() => evidence(v), [v]);
  const frames = v.frames ?? [];
  return (
    <div className="jg-yt__detail">
      <button className="jg-u-btn jg-yt__back" onClick={onBack}>‹ Videos</button>
      <h3>{v.meta?.title ?? v.video.title}</h3>
      <p className="jg-yt__sub">{v.video.channel} · {fmtTime(v.meta?.duration ?? v.video.duration)}{v.meta?.view_count ? ` · ${v.meta.view_count.toLocaleString()} views` : ""}{v.cut_list ? ` · ${v.cut_list.length} cuts` : ""}{v.audio?.lufs != null ? ` · ${v.audio.lufs} LUFS` : ""}{v.video.url && <> · <a href={v.video.url} target="_blank" rel="noreferrer">Open on YouTube</a></>}</p>
      {frames.length > 0 && <div className="jg-yt__strip" role="list" aria-label={`${frames.length} frames`}>
        {frames.map((f) => <figure key={f.file} role="listitem"><img loading="lazy" src={framePath(jobId, v.video.id, f.file)} alt={`Frame at ${fmtTime(f.t)} (${f.kind ?? "frame"})`} /><figcaption>{fmtTime(f.t)}</figcaption></figure>)}
      </div>}
      <Segmented label="Video detail" value={tab} onChange={setTab} options={[{ value: "notes", label: `Evidence (${ev.length})` }, { value: "transcript", label: "Transcript" }, { value: "steps", label: "Pipeline" }]} />
      {tab === "notes" && (ev.length ? <ol className="jg-yt__ev">{ev.map((e, i) => <li key={i} data-kind={e.kind}><span className="jg-yt__t">{fmtTime(e.t)}</span><Badge>{e.kind === "note" ? "Shot note" : "On-screen text"}</Badge><p>{e.text}</p></li>)}</ol>
        : <Empty title="No notes yet">Shot notes and on-screen text appear once those steps finish.</Empty>)}
      {tab === "transcript" && (v.transcript?.segments?.length ? <ol className="jg-yt__ev">{v.transcript.segments.map((s, i) => <li key={i}><span className="jg-yt__t">{fmtTime(s.start)}</span><p>{s.text}</p></li>)}</ol>
        : <Empty title="No transcript">{v.transcript?.source ? `Source: ${v.transcript.source}` : "Not fetched yet."}</Empty>)}
      {tab === "steps" && <dl className="jg-ui-kv">{STEP_ORDER.map((k) => { const s = v.video.steps?.[k]; return <Fragment key={k}><dt>{STEP_LABEL[k]}</dt><dd>{s?.status ?? "pending"}{s?.model ? ` · ${s.model}` : ""}{s?.error ? ` · ${s.error}` : ""}</dd></Fragment>; })}</dl>}
    </div>
  );
}
