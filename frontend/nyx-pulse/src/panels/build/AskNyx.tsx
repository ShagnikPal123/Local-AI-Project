/** Nyx in the Build tab. Every answer comes back as data the studio validates, and nothing is
 * applied to the build without the owner pressing a button - except a design job the owner
 * explicitly started, which writes as it goes so it can be watched and stopped. */

import { useEffect, useRef, useState } from "react";
import { Markdown } from "../../components/chat/Markdown";
import { buildApi, type Comparison, type Job, type Part, type Snapshot, type WiringProposal } from "./types";

type Action = "draw" | "review" | "wiring" | "compare" | "tutorial" | "apparatus";

const ACTIONS: { id: Action; label: string; placeholder: string; hint: string }[] = [
  { id: "draw", label: "Draw a part", placeholder: "e.g. a wall bracket for a 40 mm fan with M3 holes", hint: "Nyx draws it; you see it before it is saved." },
  { id: "wiring", label: "Wire it up", placeholder: "Optional: what the circuit has to do", hint: "Nyx proposes wires; you tick the ones to keep." },
  { id: "review", label: "Review the build", placeholder: "Optional: a question, e.g. will this overheat?", hint: "An engineer's read on top of the automatic checks." },
  { id: "compare", label: "Compare options", placeholder: "e.g. what should run a local AI model: Pi, Jetson or Arduino?", hint: "Real options with prices, pros and cons, and a pick." },
  { id: "tutorial", label: "Write the tutorial", placeholder: "", hint: "A step for every piece, each one lit in the 3D view." },
  { id: "apparatus", label: "Design it for me", placeholder: "e.g. a ventilated containment box for a Pi 5 running the AI", hint: "Runs in the background: plan, parts, layout, wiring, tutorial, review." },
];

export interface AskNyxProps {
  snapshot: Snapshot;
  selectedPartId: string;
  onSnapshot: (snapshot: Snapshot) => void;
  onPreviewPart: (part: Part, model: string) => void;
  onStartTutorial: (fresh?: Snapshot) => void;
  onPlaceCatalog: (catalogId: string) => void;
  onError: (message: string) => void;
  queued: { action: Action; words: string; nonce: number } | null;
}

export function AskNyx({ snapshot, onSnapshot, onPreviewPart, onStartTutorial, onPlaceCatalog, onError, queued }: AskNyxProps) {
  const project = snapshot.project;
  const [action, setAction] = useState<Action>("draw");
  const [words, setWords] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [review, setReview] = useState<{ text: string; model: string } | null>(null);
  const [wiring, setWiring] = useState<{ connections: WiringProposal[]; notes: string; model: string; keep: Set<string> } | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(project.comparison);
  const [jobs, setJobs] = useState<Job[]>([]);
  const lastQueued = useRef(0);

  useEffect(() => setComparison(project.comparison), [project.id, project.comparison]);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => { window.clearInterval(timer); setElapsed(0); };
  }, [busy]);

  // Jobs: poll while one runs, and pull the project so parts appear as they are written.
  const running = jobs.some((job) => job.state === "running");
  useEffect(() => {
    let alive = true;
    const load = async () => {
      const result = await buildApi.jobs(project.id);
      if (!alive || !result.ok) return;
      setJobs(result.data.jobs);
      if (result.data.jobs.some((job) => job.state === "running")) {
        const fresh = await buildApi.open(project.id);
        if (alive && fresh.ok && fresh.data.project.updated_at !== project.updated_at) onSnapshot(fresh.data);
      }
    };
    void load();
    if (!running) return () => { alive = false; };
    const timer = window.setInterval(() => void load(), 3000);
    return () => { alive = false; window.clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, running]);

  const run = async (which: Action, text: string) => {
    setBusy(true);
    try {
      if (which === "draw") {
        const result = await buildApi.ask<{ part: Part; model: string }>(project.id, { action: "draw", words: text });
        if (!result.ok) return onError(result.error);
        onPreviewPart(result.data.part, result.data.model);
      } else if (which === "review") {
        const result = await buildApi.ask<{ text: string; model: string }>(project.id, { action: "review", question: text });
        if (!result.ok) return onError(result.error);
        setReview(result.data);
      } else if (which === "wiring") {
        const result = await buildApi.ask<{ connections: WiringProposal[]; notes: string; model: string }>(project.id, { action: "wiring", question: text });
        if (!result.ok) return onError(result.error);
        setWiring({ ...result.data, keep: new Set(result.data.connections.map((c) => c.id)) });
      } else if (which === "compare") {
        const result = await buildApi.ask<Snapshot & { model: string }>(project.id, { action: "compare", question: text || "Which board should this build use?" });
        if (!result.ok) return onError(result.error);
        onSnapshot(result.data);
        setComparison(result.data.project.comparison);
      } else if (which === "tutorial") {
        const result = await buildApi.ask<Snapshot & { model: string }>(project.id, { action: "tutorial" });
        if (!result.ok) return onError(result.error);
        onSnapshot(result.data);
        onStartTutorial(result.data);
      } else if (which === "apparatus") {
        const result = await buildApi.ask<{ job: Job }>(project.id, { action: "apparatus", words: text || project.goal, budget_minutes: minutes });
        if (!result.ok) return onError(result.error);
        setJobs((current) => [result.data.job, ...current]);
      }
    } finally {
      setBusy(false);
    }
  };

  // Other panels ("Ask Nyx" on a check) hand a question over.
  useEffect(() => {
    if (!queued || queued.nonce === lastQueued.current) return;
    lastQueued.current = queued.nonce;
    setAction(queued.action);
    setWords(queued.words);
    void run(queued.action, queued.words);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queued]);

  const current = ACTIONS.find((a) => a.id === action)!;
  const needsWords = action === "draw" || (action === "apparatus" && !project.goal);

  return (
    <div className="bs-inspector">
      <section className="bs-section">
        <div className="bs-section__head"><h3>Ask Nyx</h3><span className="bs-muted">uses the “3D build studio” model in Keys & Models</span></div>
        <div className="bs-chips" role="group" aria-label="What Nyx should do">
          {ACTIONS.map((a) => (
            <button key={a.id} className="chip" aria-pressed={action === a.id} onClick={() => setAction(a.id)}>{a.label}</button>
          ))}
        </div>
        <p className="bs-muted">{current.hint}</p>
        <form className="bs-askbox" onSubmit={(e) => { e.preventDefault(); if (!busy && (!needsWords || words.trim())) void run(action, words.trim()); }}>
          {action !== "tutorial" && (
            <textarea rows={3} value={words} onChange={(e) => setWords(e.target.value)} placeholder={action === "apparatus" && project.goal ? `Leave empty to use the goal: ${project.goal}` : current.placeholder}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) (e.currentTarget.form as HTMLFormElement).requestSubmit(); }} />
          )}
          {action === "apparatus" && (
            <label className="bs-field bs-field--inline"><span>Time it may take</span>
              <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                {[10, 30, 60, 120, 240, 480].map((m) => <option key={m} value={m}>{m < 60 ? `${m} minutes` : `${m / 60} hour${m === 60 ? "" : "s"}`}</option>)}
              </select>
            </label>
          )}
          <button className="btn btn-primary" disabled={busy || (needsWords && !words.trim()) || (action === "apparatus" && running)}>
            {busy ? `Nyx is working… ${elapsed}s` : current.label}
          </button>
        </form>
      </section>

      {jobs.filter((job) => job.state === "running" || Date.now() / 1000 - (job.steps.at(-1)?.at ?? 0) < 3600).slice(0, 3).map((job) => (
        <section key={job.id} className={`bs-section bs-job is-${job.state}`}>
          <div className="bs-section__head">
            <h3>{job.state === "running" ? job.phase_label || "Designing" : job.state === "done" ? "Design finished" : job.state === "stopped" ? "Stopped" : job.state === "interrupted" ? "Interrupted" : "Stopped with a problem"}</h3>
            {job.state === "running" && <button className="bs-link bs-link--danger" onClick={async () => { await buildApi.stopJob(job.id); setJobs((j) => j.map((x) => x.id === job.id ? { ...x, state: "stopped" } : x)); }}>Stop</button>}
          </div>
          <p className="bs-muted">{job.brief}</p>
          <div className="bs-progress" role="progressbar" aria-valuenow={Math.round(job.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${Math.max(4, job.progress * 100)}%` }} />
          </div>
          <ol className="bs-joblog">
            {job.steps.slice(-8).map((step, i) => <li key={i}><b>{step.phase}</b> {step.text}{step.model ? <span className="bs-model"> · {step.model}</span> : null}</li>)}
          </ol>
          {job.state !== "running" && <p className="bs-muted">{job.message}</p>}
          {job.state === "done" && project.tutorial && <button className="btn btn-secondary btn-sm" onClick={() => onStartTutorial()}>Walk through it</button>}
        </section>
      ))}

      {wiring && (
        <section className="bs-section">
          <div className="bs-section__head"><h3>Proposed wiring</h3><span className="bs-model">{wiring.model}</span></div>
          <ul className="bs-proposals">
            {wiring.connections.map((c) => (
              <li key={c.id}>
                <label>
                  <input type="checkbox" checked={wiring.keep.has(c.id)} onChange={() => setWiring((w) => {
                    if (!w) return w;
                    const keep = new Set(w.keep);
                    if (keep.has(c.id)) keep.delete(c.id); else keep.add(c.id);
                    return { ...w, keep };
                  })} />
                  <span><b>{c.name}</b><br /><span className="bs-muted">{c.from.label} → {c.to.label}</span>{c.why && <><br /><span className="bs-muted">{c.why}</span></>}</span>
                </label>
              </li>
            ))}
          </ul>
          {wiring.notes && <p className="bs-note">{wiring.notes}</p>}
          <div className="bs-row">
            <button className="btn btn-primary btn-sm" disabled={!wiring.keep.size} onClick={async () => {
              const chosen = wiring.connections.filter((c) => wiring.keep.has(c.id));
              const result = await buildApi.applyWiring(project.id, chosen);
              if (!result.ok) return onError(result.error);
              onSnapshot(result.data);
              setWiring(null);
              if (result.data.refused.length) onError(`Wired ${result.data.wired}. Refused: ${result.data.refused.join(" ")}`);
            }}>Connect {wiring.keep.size}</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setWiring(null)}>Dismiss</button>
          </div>
        </section>
      )}

      {review && (
        <section className="bs-section">
          <div className="bs-section__head"><h3>Nyx’s review</h3><button className="bs-link" onClick={() => setReview(null)}>Close</button></div>
          <div className="bs-answer"><Markdown text={review.text} /><div className="bs-model">{review.model}</div></div>
        </section>
      )}

      {comparison && (
        <section className="bs-section">
          <div className="bs-section__head"><h3>Options</h3><span className="bs-model">{comparison.model}</span></div>
          {comparison.question && <p className="bs-muted">{comparison.question}</p>}
          <div className="bs-options">
            {comparison.options.map((option) => (
              <article key={option.id} className={`bs-option${option.name === comparison.recommendation ? " is-pick" : ""}`}>
                <header>
                  <b>{option.name}</b>
                  {option.name === comparison.recommendation && <span className="chip">Nyx’s pick</span>}
                </header>
                <div className="bs-option__meta">{option.price_usd ? `≈ $${option.price_usd}` : "price unknown"} · score {option.score}/10</div>
                <p>{option.summary}</p>
                {option.pros.length > 0 && <ul className="bs-pros">{option.pros.map((p) => <li key={p}>{p}</li>)}</ul>}
                {option.cons.length > 0 && <ul className="bs-cons">{option.cons.map((c) => <li key={c}>{c}</li>)}</ul>}
                {option.catalog_id && <button className="btn btn-secondary btn-sm" onClick={() => onPlaceCatalog(option.catalog_id)}>Add to build</button>}
              </article>
            ))}
          </div>
          {comparison.because && <p className="bs-note">{comparison.because}</p>}
        </section>
      )}
    </div>
  );
}
