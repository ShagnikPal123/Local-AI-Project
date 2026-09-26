/** Improve → Deep & specific mode (owner request, 2026-09-16).
 *
 * "Clicking this shows a big box and I can paste or write specific improvements and such and it auto generates
 * the time it thinks it will take and can iterate if needed."
 *
 * The estimate comes from the server's offline planner as you type (no model call), item by item. Start works
 * through them: research → change in the review gate → write + test in a sandbox (retrying with the error up to
 * the number of tries) → reviewer reads the real diff → apply. Past the estimate it takes longer only if
 * "Take longer if needed" is on; otherwise the rest wait in Review changes.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { DiffSummary, type LineStats } from "../../components/DiffSummary";

interface PlanItem { index: number; text: string; target: string; kind: "python" | "ui" | "unknown"; why?: string; minutes: number; auto: boolean }
interface Plan { items: PlanItem[]; iterations: number; total_minutes: number; auto_count: number; manual_count: number }
interface JobItem extends PlanItem {
  state: "queued" | "working" | "applied" | "filed" | "failed" | "blocked" | "skipped"; message?: string; research?: string;
  /** Which file and how many lines the edit touched (Request R9). */
  lines?: LineStats | null;
}
interface Job {
  job_id: string; status: string; now: string; items: JobItem[]; iterations: number; apply: boolean; extend: boolean;
  estimate_minutes: number; extended_minutes: number; elapsed_minutes: number; budget_minutes: number; remaining_minutes: number;
  log: { ts: number; text: string }[];
}

const STATE_TEXT: Record<JobItem["state"], string> = {
  queued: "○ Waiting", working: "● Working", applied: "✓ Applied", filed: "◇ In review", failed: "▲ Not applied", blocked: "▲ Blocked", skipped: "– Skipped",
};
const KIND_TEXT = { python: "Nyx can apply", ui: "UI edit", unknown: "File unclear" };

export function minutesText(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
}

export function DeepMode({ onStarted }: { onStarted?: () => void }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("nyx.improve.deep") === "1"; } catch { return false; } });
  const [text, setText] = useState(() => { try { return localStorage.getItem("nyx.improve.deep.draft") ?? ""; } catch { return ""; } });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [targets, setTargets] = useState<Record<number, string>>({});
  const [iterations, setIterations] = useState(2);
  const [apply, setApply] = useState(true);
  const [extend, setExtend] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { try { localStorage.setItem("nyx.improve.deep", open ? "1" : "0"); } catch { /* not kept */ } if (open) area.current?.focus(); }, [open]);
  useEffect(() => { try { localStorage.setItem("nyx.improve.deep.draft", text); } catch { /* not kept */ } }, [text]);

  // The estimate follows the text as it is typed.
  useEffect(() => {
    if (!open || !text.trim()) { setPlan(null); return; }
    const timer = window.setTimeout(async () => {
      const result = await api.post<Plan>("/api/improve/deep/plan", { text, iterations });
      if (result.ok) { setPlan(result.data); setError(""); } else setError(result.error);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [text, iterations, open]);

  useEffect(() => {
    void api.get<{ job: Job | null }>("/api/improve/deep").then((r) => { if (r.ok && r.data.job) setJob(r.data.job); });
    return onWorkspaceEvent((event) => { if (event.type === "improve.deep" && event.job) setJob(event.job as Job); });
  }, []);
  useEffect(() => {
    if (job?.status !== "running") return;
    const timer = window.setInterval(async () => {
      const r = await api.get<{ job: Job | null }>("/api/improve/deep");
      if (r.ok && r.data.job) setJob(r.data.job);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [job?.status]);

  async function start() {
    if (!plan) return;
    setBusy(true);
    const items = plan.items.map((item) => ({ ...item, target: targets[item.index] ?? item.target }));
    const result = await api.post<{ job: Job }>("/api/improve/deep", { text, items, iterations, apply, extend }, 30_000);
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setJob(result.data.job);
    onStarted?.();
  }

  const running = job?.status === "running";
  const total = plan?.total_minutes ?? 0;

  return (
    <section className={`card deep${open ? " is-open" : ""}`} aria-labelledby="deep-title">
      <div className="deep__head">
        <div>
          <h2 id="deep-title" className="section-title" style={{ margin: 0 }}>Deep & specific</h2>
          <p className="field-row__hint" style={{ margin: "4px 0 0" }}>Paste or write exactly what to improve. Nyx estimates the time as you type.</p>
        </div>
        <button className="btn btn-secondary deep__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "Close" : "Open Deep & Specific"}
        </button>
      </div>

      {open && !running && (
        <div className="deep__editor">
          <label className="sr-only" htmlFor="deep-text">Specific improvements</label>
          <textarea id="deep-text" ref={area} className="deep__text" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"One improvement per line works best, e.g.\n- The router should try another NVIDIA model when Nemotron times out\n- Voice replies should pause briefly between paragraphs\n- Add logging to the storage cleanup so I can see what it removed"} />
          <div className="deep__estimate" aria-live="polite">
            <div className="deep__total">
              <span className="deep__clock" aria-hidden="true">◷</span>
              <b>{plan ? `≈ ${minutesText(total)}` : "—"}</b>
              <span>{plan ? `for ${plan.items.length} improvement${plan.items.length === 1 ? "" : "s"} · ${plan.auto_count} Nyx can apply · ${plan.manual_count} need you or a UI edit` : "Start typing to get an estimate"}</span>
            </div>
            {plan && plan.items.length > 0 && (
              <ol className="deep__items">
                {plan.items.map((item) => (
                  <li key={item.index}>
                    <span className="deep__itemtext">{item.text}</span>
                    <input className="deep__target" value={targets[item.index] ?? item.target} placeholder="file.py"
                      aria-label={`File for item ${item.index + 1}`} onChange={(e) => setTargets((t) => ({ ...t, [item.index]: e.target.value }))} />
                    <span className={`chip deep__kind is-${(targets[item.index] ?? item.target).endsWith(".py") ? "python" : item.kind}`}>
                      {KIND_TEXT[(targets[item.index] ?? item.target).endsWith(".py") ? "python" : item.kind]}
                    </span>
                    <span className="deep__min">{minutesText(item.minutes)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="deep__options">
            <label className="deep__stepper">
              <span>Tries per item</span>
              <button type="button" className="btn btn-secondary" aria-label="Fewer tries" onClick={() => setIterations((n) => Math.max(1, n - 1))}>−</button>
              <b aria-live="polite">{iterations}</b>
              <button type="button" className="btn btn-secondary" aria-label="More tries" onClick={() => setIterations((n) => Math.min(5, n + 1))}>+</button>
            </label>
            <label className="deep__opt"><button type="button" className="switch" role="switch" aria-checked={apply} onClick={() => setApply((v) => !v)} />
              <span><b>Apply when tests pass</b><em>Off: research and file each one for your approval</em></span></label>
            <label className="deep__opt"><button type="button" className="switch" role="switch" aria-checked={extend} onClick={() => setExtend((v) => !v)} />
              <span><b>Take longer if needed</b><em>Off: stop at the estimate; the rest wait in Review changes</em></span></label>
            <button className="btn btn-primary deep__start" disabled={!plan || plan.items.length === 0 || busy} onClick={() => void start()}>
              {busy ? "Starting…" : plan ? `Start — about ${minutesText(total)}` : "Start"}
            </button>
          </div>
          {error && <p className="field-row__hint" style={{ color: "var(--color-warn)" }}>{error}</p>}
        </div>
      )}

      {job && (running || open) && (
        <div className={`deep__run is-${job.status}`} aria-live="polite">
          <div className="deep__runhead">
            <b>{running ? "Working through your list" : `Last run — ${job.status.replace("_", " ")}`}</b>
            <span className="hud-caption">
              {minutesText(job.elapsed_minutes)} of {minutesText(job.budget_minutes)}
              {job.extended_minutes > 0 ? ` (extended by ${minutesText(job.extended_minutes)})` : ""}
              {running ? ` · about ${minutesText(job.remaining_minutes)} left` : ""}
            </span>
            {running && <button className="btn btn-secondary" onClick={() => void api.post("/api/improve/deep/stop")}>Stop</button>}
          </div>
          <div className="dispatch__bar"><span style={{ width: `${Math.min(100, (job.elapsed_minutes / Math.max(1, job.budget_minutes)) * 100)}%` }} /></div>
          <div className="field-row__hint">{job.now}</div>
          <ol className="deep__items deep__items--run">
            {job.items.map((item) => (
              <li key={item.index} className={`is-${item.state}`}>
                <span className="deep__itemtext">{item.text}{item.message && <em>{item.message}</em>}
                  {item.lines && item.lines.files?.length > 0 && <DiffSummary lines={item.lines} verb="Changed" compact />}
                </span>
                <code>{item.target || "—"}</code>
                <span className={`deep__state is-${item.state}`}>{STATE_TEXT[item.state]}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
