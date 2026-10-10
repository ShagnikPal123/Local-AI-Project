/** Predict — a swarm of simulated people rehearses the future (owner, 2026-10-10; predict.py; idea from MiroFish).
 *
 * Give it anything — a question, text, files, links, a video — pick how big a swarm, and watch: every dot is an
 * agent with its own persona, drifting toward the outcome it leans to (closer = surer). Bars and lines show the
 * swarm's forecast round by round, the feed shows what agents say, and you can drop an event in from a god's-eye
 * view. When it ends, a report; then ask any agent — click its dot — or the analyst.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { Markdown } from "../../components/chat/Markdown";
import "./predict.css";

interface Outcome { id: string; label: string }
interface Agent { id: string; name: string; role: string; lean: string; confidence: number; x: number; y: number }
interface Post { round: number; agent: string; name: string; lean: string; text: string }
interface Job {
  id: string; question: string; scale: string; status: string; round: number; rounds: number; outcomes: Outcome[];
  probabilities: Record<string, number>[]; events: { round: number; text: string }[]; report: string; note: string;
  agents: Agent[]; feed: Post[]; seed_names: string[]; calls: number; estimate: number;
  graph: { entities?: { id: string; name: string; kind: string }[] };
}
interface JobRow { id: string; question: string; status: string; scale: string; round: number; rounds: number }
interface Scale { id: string; agents: number; rounds: number; active: number; calls: number }
interface Seed { kind: "text" | "link" | "upload" | "path"; value: string; label: string }

const COLORS = ["#a594ff", "#5fd4f4", "#ffc46b", "#f39bd6"];
const SCALE_WORDS: Record<string, string> = { quick: "Minutes", standard: "Under an hour", large: "An hour or more", swarm: "Hours" };
const STATUS: Record<string, string> = { queued: "Starting", building: "Reading the seeds", running: "Simulating", paused: "Paused", stopped: "Stopped", done: "Done", failed: "Stopped by an error" };

export function PredictPanel() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const loadJobs = useCallback(async () => {
    const r = await api.get<{ jobs: JobRow[] }>("/api/predict/jobs");
    if (r.ok) setJobs(r.data.jobs);
  }, []);
  useEffect(() => { void loadJobs(); }, [loadJobs]);
  const open = useCallback(async (id: string) => {
    const r = await api.get<Job>(`/api/predict/jobs/${id}`);
    if (r.ok) setJob(r.data);
  }, []);
  useEffect(() => onWorkspaceEvent((event) => {
    const incoming = (event as { type: string; job?: Job }).job;
    if (event.type !== "predict.update" || !incoming) return;
    setJob((current) => (current && current.id === incoming.id ? incoming : current));
    setJobs((rows) => rows.map((r) => (r.id === incoming.id ? { ...r, status: incoming.status, round: incoming.round } : r)));
  }), []);
  // The live bus can drop an event; a slow poll keeps a running swarm honest.
  useEffect(() => {
    if (!job || !["queued", "building", "running"].includes(job.status)) return;
    const timer = window.setInterval(() => void open(job.id), 6000);
    return () => window.clearInterval(timer);
  }, [job, open]);

  return (
    <div className="pd">
      <aside className="pd__list" aria-label="Predictions">
        <button type="button" className="btn btn-primary pd__new" onClick={() => setJob(null)}>+ New prediction</button>
        {jobs.map((j) => (
          <button key={j.id} type="button" className="pd__row" aria-current={job?.id === j.id} onClick={() => void open(j.id)}>
            <b>{j.question}</b>
            <small>{STATUS[j.status] ?? j.status} · {j.scale} · round {j.round}/{j.rounds}</small>
          </button>
        ))}
      </aside>
      <section className="pd__main">
        {job ? <JobView job={job} onChange={setJob} /> : <NewPrediction onStarted={(j) => { setJob(j); void loadJobs(); }} />}
      </section>
    </div>
  );
}

function NewPrediction({ onStarted }: { onStarted: (job: Job) => void }) {
  const [question, setQuestion] = useState("");
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [scale, setScale] = useState("quick");
  const [scales, setScales] = useState<Scale[]>([]);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { void api.get<{ scales: Scale[] }>("/api/predict/scales").then((r) => { if (r.ok) setScales(r.data.scales); }); }, []);

  const addFiles = async (files: File[]) => {
    for (const f of files) {
      const r = await uploadFile(f);
      if (r.ok) setSeeds((s) => [...s, { kind: "upload", value: r.data.id, label: f.name }]);
      else setError(`${f.name}: ${r.error}`);
    }
  };
  const start = async () => {
    setBusy(true); setError("");
    const r = await api.post<Job>("/api/predict/jobs", { question, scale, seeds: seeds.map(({ kind, value }) => ({ kind, value })) });
    setBusy(false);
    if (r.ok) onStarted(r.data); else setError(r.error);
  };

  return (
    <div className="pd-new" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void addFiles(Array.from(e.dataTransfer.files)); }}>
      <h1 className="pd-new__title">What should the swarm predict?</h1>
      <p className="pd-new__lead">Many simulated people, each with their own view, argue it out round by round. Give it anything to ground them — text, files, links, a video.</p>
      <div className="pd-new__card">
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} aria-label="Question"
          placeholder="e.g. Will remote work grow or shrink in 2027? · How will fans react to this trailer? · Which ending fits this story?" />
        <div className="pd-new__seeds">
          {seeds.map((s, i) => (
            <span key={`${s.value}-${i}`} className="pd-chip">{s.kind === "link" ? "🔗" : s.kind === "text" ? "¶" : "▤"} {s.label}
              <button aria-label={`Remove ${s.label}`} onClick={() => setSeeds(seeds.filter((_, k) => k !== i))}>✕</button></span>
          ))}
        </div>
        <div className="pd-new__tools">
          <input ref={file} type="file" multiple hidden onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <button type="button" className="btn btn-secondary" onClick={() => file.current?.click()}>+ Files or video</button>
          <form onSubmit={(e) => { e.preventDefault(); if (link.trim()) { setSeeds([...seeds, { kind: "link", value: link.trim(), label: link.trim().slice(0, 40) }]); setLink(""); } }}>
            <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Paste a link" aria-label="Link" />
          </form>
          <button type="button" className="btn btn-ghost" onClick={() => { const t = window.prompt("Paste text to ground the swarm"); if (t?.trim()) setSeeds([...seeds, { kind: "text", value: t, label: t.slice(0, 30) }]); }}>+ Text</button>
        </div>
      </div>
      <div className="pd-scales" role="radiogroup" aria-label="How big a swarm">
        {scales.map((s) => (
          <button key={s.id} type="button" role="radio" aria-checked={scale === s.id} className="pd-scale" onClick={() => setScale(s.id)}>
            <b>{s.id[0].toUpperCase() + s.id.slice(1)}</b>
            <span>{s.agents} agents · {s.rounds} rounds</span>
            <small>{SCALE_WORDS[s.id]} · ≈ {s.calls} model calls</small>
          </button>
        ))}
      </div>
      {error && <p className="pd-error" role="alert">{error}</p>}
      <button type="button" className="btn btn-primary pd-new__go" disabled={busy || !question.trim()} onClick={() => void start()}>
        {busy ? "Gathering the swarm…" : "Start predicting"}
      </button>
    </div>
  );
}

function JobView({ job, onChange }: { job: Job; onChange: (job: Job) => void }) {
  const [event, setEvent] = useState("");
  const [who, setWho] = useState("report");
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<{ who: string; q: string; a: string }[]>([]);
  const [asking, setAsking] = useState(false);
  const colorOf = useMemo(() => Object.fromEntries(job.outcomes.map((o, i) => [o.id, COLORS[i % COLORS.length]])), [job.outcomes]);
  const latest = job.probabilities[job.probabilities.length - 1] ?? {};
  const running = ["queued", "building", "running"].includes(job.status);
  const act = async (action: string, body: object = {}) => {
    const r = await api.post<Job>(`/api/predict/jobs/${job.id}/${action}`, body);
    if (r.ok) onChange(r.data);
  };
  const askIt = async () => {
    if (!question.trim()) return;
    setAsking(true);
    const r = await api.post<{ answer: string }>(`/api/predict/jobs/${job.id}/chat`, { who, question }, 120000);
    setAsking(false);
    const name = who === "report" ? "Analyst" : job.agents.find((a) => a.id === who)?.name ?? who;
    setAnswers((list) => [{ who: name, q: question, a: r.ok ? r.data.answer : r.error }, ...list]);
    setQuestion("");
  };

  return (
    <div className="pd-job">
      <header className="pd-job__head">
        <div>
          <h1>{job.question}</h1>
          <p>{STATUS[job.status] ?? job.status} · round {job.round} of {job.rounds} · {job.agents.length} agents · {job.calls} of ≈{job.estimate} calls
            {job.seed_names.length > 0 && <> · from {job.seed_names.join(", ")}</>}</p>
        </div>
        <div className="pd-job__controls">
          {running && <button className="btn btn-secondary" onClick={() => void act("pause")}>Pause</button>}
          {["paused", "failed"].includes(job.status) && <button className="btn btn-primary" onClick={() => void act("resume")}>Resume</button>}
          {(running || job.status === "paused") && <button className="btn btn-ghost" onClick={() => void act("stop")}>Stop</button>}
        </div>
      </header>
      <div className="pd-progress" role="progressbar" aria-valuemin={0} aria-valuemax={job.rounds} aria-valuenow={job.round}>
        <span style={{ width: `${(job.round / Math.max(1, job.rounds)) * 100}%` }} />
      </div>
      {job.note && <p className="pd-error">{job.note}</p>}

      <div className="pd-grid">
        <div className="pd-swarm-card">
          <Swarm agents={job.agents} outcomes={job.outcomes} colorOf={colorOf} selected={who} onPick={setWho} />
          <div className="pd-legend">
            {job.outcomes.map((o) => (
              <div key={o.id} className="pd-bar" style={{ ["--c" as string]: colorOf[o.id] }}>
                <span>{o.label}</span>
                <b>{Math.round((latest[o.id] ?? 0) * 100)}%</b>
                <i style={{ width: `${(latest[o.id] ?? 0) * 100}%` }} />
              </div>
            ))}
          </div>
          <Trend probabilities={job.probabilities} outcomes={job.outcomes} colorOf={colorOf} />
        </div>

        <div className="pd-side">
          {running || job.status === "paused" ? (
            <form className="pd-inject" onSubmit={(e) => { e.preventDefault(); if (event.trim()) { void act("inject", { text: event }); setEvent(""); } }}>
              <input value={event} onChange={(e) => setEvent(e.target.value)} placeholder="God's-eye view: something happens… (next round)" aria-label="Inject an event" />
              <button className="btn btn-secondary" type="submit">Inject</button>
            </form>
          ) : null}
          {job.events.length > 0 && <ul className="pd-events">{job.events.map((e, i) => <li key={i}>Round {e.round}: {e.text}</li>)}</ul>}
          {job.report && <div className="pd-report"><Markdown text={job.report} /></div>}
          <h2 className="pd-side__title">The square</h2>
          <ol className="pd-feed">
            {[...job.feed].reverse().slice(0, 30).map((p, i) => (
              <li key={`${p.agent}-${p.round}-${i}`} style={{ ["--c" as string]: colorOf[p.lean] }}>
                <button type="button" onClick={() => setWho(p.agent)}><b>{p.name}</b> <small>r{p.round}</small></button>
                <p>{p.text}</p>
              </li>
            ))}
            {job.feed.length === 0 && <li className="pd-muted">The first round has not spoken yet.</li>}
          </ol>
          <form className="pd-ask" onSubmit={(e) => { e.preventDefault(); void askIt(); }}>
            <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="Ask whom">
              <option value="report">The analyst</option>
              {job.agents.slice(0, 200).map((a) => <option key={a.id} value={a.id}>{a.name} — {a.role}</option>)}
            </select>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask them why…" aria-label="Question" />
            <button className="btn btn-primary" disabled={asking || !question.trim()}>{asking ? "…" : "Ask"}</button>
          </form>
          {answers.map((a, i) => <div key={i} className="pd-answer"><b>{a.who}</b> <small>{a.q}</small><p>{a.a}</p></div>)}
        </div>
      </div>
    </div>
  );
}

/** Every agent as a dot drifting toward its outcome; sure ones sit further out. Positions ease between rounds. */
function Swarm({ agents, outcomes, colorOf, selected, onPick }: { agents: Agent[]; outcomes: Outcome[]; colorOf: Record<string, string>; selected: string; onPick: (id: string) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const shown = useRef<Record<string, { x: number; y: number }>>({});
  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = el.clientWidth, h = el.clientHeight;
      if (el.width !== w * dpr) { el.width = w * dpr; el.height = h * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      outcomes.forEach((o, i) => {
        const angle = (2 * Math.PI * i) / Math.max(1, outcomes.length);
        const x = w * (0.5 + Math.cos(angle) * 0.42), y = h * (0.5 + Math.sin(angle) * 0.42);
        ctx.fillStyle = colorOf[o.id]; ctx.globalAlpha = 0.9; ctx.font = "600 12px Segoe UI Variable Text, sans-serif";
        ctx.textAlign = "center"; ctx.fillText(o.label.slice(0, 26), x, y);
      });
      let moving = false;
      for (const a of agents) {
        const now = shown.current[a.id] ?? { x: 0.5, y: 0.5 };
        const nx = now.x + (a.x - now.x) * (reduced ? 1 : 0.08), ny = now.y + (a.y - now.y) * (reduced ? 1 : 0.08);
        if (Math.abs(nx - a.x) > 0.001 || Math.abs(ny - a.y) > 0.001) moving = true;
        shown.current[a.id] = { x: nx, y: ny };
        ctx.globalAlpha = 0.35 + 0.6 * a.confidence;
        ctx.fillStyle = colorOf[a.lean] ?? "#888";
        ctx.beginPath(); ctx.arc(nx * w, ny * h, a.id === selected ? 7 : 3 + a.confidence * 3, 0, Math.PI * 2); ctx.fill();
        if (a.id === selected) { ctx.globalAlpha = 1; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); }
      }
      ctx.globalAlpha = 1;
      if (moving && !reduced) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [agents, outcomes, colorOf, selected]);
  return (
    <canvas ref={canvas} className="pd-swarm" role="img" aria-label={`${agents.length} agents, coloured by the outcome they lean to`}
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width, y = (e.clientY - rect.top) / rect.height;
        let best: Agent | null = null, dist = 0.03;
        for (const a of agents) { const d = Math.hypot(a.x - x, a.y - y); if (d < dist) { dist = d; best = a; } }
        if (best) onPick(best.id);
      }} />
  );
}

function Trend({ probabilities, outcomes, colorOf }: { probabilities: Record<string, number>[]; outcomes: Outcome[]; colorOf: Record<string, string> }) {
  if (probabilities.length < 2) return null;
  const w = 100, h = 40;
  return (
    <svg className="pd-trend" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="How the forecast moved, round by round">
      {outcomes.map((o) => (
        <polyline key={o.id} fill="none" stroke={colorOf[o.id]} strokeWidth="1.2" vectorEffect="non-scaling-stroke"
          points={probabilities.map((p, i) => `${(i / (probabilities.length - 1)) * w},${h - (p[o.id] ?? 0) * h}`).join(" ")} />
      ))}
    </svg>
  );
}
