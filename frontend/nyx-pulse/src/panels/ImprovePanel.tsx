/** Improve — self-improvement on the owner's schedule, steered by the owner's controls.
 *
 * The owner asked to say things like "improve and auto-approve everything for 22
 * hours" or "study for an hour, improve for an hour, loop until I stop", and to
 * have Nyx add new sliders here. So the tab is:
 *
 *   1. an Improve console — type the plan in words (or pick a preset); Nyx's
 *      `improve_schedule` understands the same sentences in any chat;
 *   2. the live autopilot run — phase timeline, time left, what it is doing now,
 *      auto-approve state, Pause / Stop, and its log;
 *   3. controls — every slider/toggle/picker from `controls.json`, including the
 *      ones Nyx added ("added by Nyx"), which the autopilot follows;
 *   4. what it learned (lessons) and what it changed (diffs, with Roll back).
 *
 * A single "improve X now" is just a one-phase plan; `improve_self` in chat still
 * starts a bare analysis session when that is all the owner wants.
 *
 * The server is the gate: auto-approved changes are critic-reviewed, tested in a
 * sandbox and applied only on green; everything applied can be rolled back.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading } from "../components/Panel";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { DiffSummary } from "../components/DiffSummary";
import { DeepMode } from "./improve/DeepMode";
import { ReviewQueue } from "./improve/ReviewQueue";
import "./improve/improve.css";

interface Phase { kind: "study" | "improve" | "detox" | "rest"; minutes: number; focus?: string }
interface Run {
  run_id: string; instruction: string; phases: Phase[]; loop: boolean; auto_approve: boolean; focus: string;
  created_at: number; ends_at: number | null; status: string; phase_index: number; phase: Phase;
  phase_remaining_seconds: number | null; remaining_seconds: number | null; cycles: number; work: string;
  stats: Record<string, number>; log: { ts: number; kind: string; text: string }[];
}
interface Control {
  key: string; label: string; kind: "slider" | "toggle" | "select" | "multiselect" | "text";
  min?: number; max?: number; step?: number; options?: string[]; value: unknown; description?: string;
  affects?: string; added_by?: string; custom?: boolean;
}
interface Lesson { topic: string; insight: string; improvement: string; module: string; research?: string; ts: number }
interface ChangeItem {
  id: string; title: string; description: string; target: string; status: string; ai_review: string;
  reviewed_by: string; created_at: number; diff: string; applied: boolean; rolled_back: boolean; can_roll_back: boolean;
}
interface State { active: Run | null; runs: Run[]; controls: Control[]; lessons: Lesson[] }

const PRESETS: { label: string; hint: string; instruction: string }[] = [
  { label: "Auto-approve for 22 hours", hint: "Improve continuously; changes are reviewed, tested and applied", instruction: "improve and auto approve all improvements for 22 hours" },
  { label: "Study 1 h ↔ improve 1 h", hint: "Loops until you stop it; waits for your approval", instruction: "study for 1 hour and improve for 1 hour, loop until I stop" },
  { label: "Detox hour", hint: "Consolidate what it learned, then a gentle tidy-up", instruction: "take a detox hour" },
  { label: "Overnight, auto-approve", hint: "Study then improve while you sleep", instruction: "study 1 hour then improve for 7 hours, auto approve" },
];

const PHASE_COLOR: Record<string, string> = { study: "#64d2ff", improve: "#a594ff", detox: "#30d158", rest: "#5a5a63" };

function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "until stopped";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : m ? `${m} min` : `${s} s`;
}

function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="diff">
      {diff.split("\n").map((line, i) => (
        <span key={i} className={line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : line.startsWith("@@") ? "hunk" : ""}>
          {line}{"\n"}
        </span>
      ))}
    </pre>
  );
}

function ControlRow({ control, onChange, onRemove }: { control: Control; onChange: (value: unknown) => void; onRemove?: () => void }) {
  const [local, setLocal] = useState<unknown>(control.value);
  useEffect(() => setLocal(control.value), [control.value]);
  const id = `ctl-${control.key}`;
  const nyx = control.added_by === "nyx";
  return (
    <div className="field-row">
      <div className="field-row__text">
        <label className="field-row__label" htmlFor={id}>
          {control.label}
          {nyx && <span className="badge-nyx">added by Nyx</span>}
        </label>
        {(control.affects || control.description) && <div className="field-row__hint">{control.affects || control.description}</div>}
        {control.kind === "slider" && (
          <input id={id} type="range" className="slider" min={control.min} max={control.max} step={control.step ?? 1}
            value={Number(local)} style={{ ["--fill" as string]: `${((Number(local) - (control.min ?? 0)) / ((control.max ?? 1) - (control.min ?? 0))) * 100}%` }}
            onChange={(e) => setLocal(Number(e.target.value))} onPointerUp={() => onChange(local)} onKeyUp={() => onChange(local)} />
        )}
        {control.kind === "multiselect" && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }} role="group" aria-label={control.label}>
            {(control.options ?? []).map((option) => {
              const values = Array.isArray(local) ? (local as string[]) : [];
              const on = values.includes(option);
              return (
                <button key={option} className="chip" aria-pressed={on}
                  onClick={() => { const next = on ? values.filter((v) => v !== option) : [...values, option]; setLocal(next); onChange(next); }}>
                  {option}
                </button>
              );
            })}
          </div>
        )}
        {control.kind === "text" && (
          <input id={id} className="text-input" style={{ marginTop: 6 }} value={String(local ?? "")}
            onChange={(e) => setLocal(e.target.value)} onBlur={() => onChange(local)} />
        )}
      </div>
      {control.kind === "slider" && <span className="field-row__value">{String(local)}</span>}
      {control.kind === "toggle" && (
        <button id={id} className="switch" role="switch" aria-checked={Boolean(local)} aria-label={control.label}
          onClick={() => { setLocal(!local); onChange(!local); }} />
      )}
      {control.kind === "select" && (
        <div className="segmented" role="group" aria-label={control.label}>
          {(control.options ?? []).map((option) => (
            <button key={option} aria-pressed={local === option} onClick={() => { setLocal(option); onChange(option); }}>{option}</button>
          ))}
        </div>
      )}
      {onRemove && <button className="btn btn-secondary" onClick={onRemove} aria-label={`Remove ${control.label}`}>Remove</button>}
    </div>
  );
}

export function ImprovePanel() {
  const [state, setState] = useState<State | null>(null);
  const [changes, setChanges] = useState<ChangeItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [openDiff, setOpenDiff] = useState<string | null>(null);
  const [newControl, setNewControl] = useState({ label: "", kind: "slider", affects: "", min: 0, max: 10 });

  const load = useCallback(async () => {
    const [auto, changeList] = await Promise.all([
      api.get<State>("/api/improve/autopilot"),
      api.get<{ changes: ChangeItem[] }>("/api/improve/changes"),
    ]);
    if (auto.ok) { setState(auto.data); setError(null); } else setError(auto.error);
    if (changeList.ok) setChanges(changeList.data.changes);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((e) => { if (e.type === "improve.autopilot") void load(); }), [load]);
  useEffect(() => {
    if (!state?.active) return;
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 10000);
    return () => window.clearInterval(timer);
  }, [state?.active, load]);

  const start = async (text: string) => {
    if (!text.trim() || busy) return;
    setBusy(true);
    const result = await api.post<Run & { review?: { message: string } }>("/api/improve/autopilot", { instruction: text });
    setBusy(false);
    if (!result.ok) { setNotice(result.error); return; }
    setInstruction("");
    // "Apply all", "approve these changes": the server runs the review queue instead of a new improve run.
    setNotice(result.data.review ? `${result.data.review.message} — see Review changes below.` : "");
    void load();
  };
  const act = async (action: "stop" | "pause" | "resume") => {
    const result = await api.post(`/api/improve/autopilot/${action}`);
    if (!result.ok) setNotice(result.error);
    void load();
  };
  const setControl = async (key: string, value: unknown) => {
    const result = await api.put(`/api/improve/controls/${key}`, { value });
    if (!result.ok) setNotice(result.error);
    void load();
  };
  const removeControl = async (key: string) => {
    const result = await api.del(`/api/improve/controls/${key}`);
    if (!result.ok) setNotice(result.error);
    void load();
  };
  const addControl = async () => {
    if (!newControl.label.trim()) return;
    const result = await api.post("/api/improve/controls", { ...newControl, key: newControl.label });
    if (result.ok) { setNewControl({ label: "", kind: "slider", affects: "", min: 0, max: 10 }); void load(); } else setNotice(result.error);
  };
  const rollback = async (id: string) => {
    if (!window.confirm("Put this file back exactly as it was before the change? Nyx restarts to load it.")) return;
    const result = await api.post<{ message: string }>(`/api/improve/changes/${id}/rollback`);
    setNotice(result.ok ? result.data.message : result.error);
    void load();
  };

  if (error && !state) return <div className="page"><div className="page__inner"><ErrorState error={error} /></div></div>;
  if (!state) return <div className="page"><div className="page__inner"><Loading what="Loading the autopilot" /></div></div>;

  const run = state.active;
  const totalMinutes = run ? run.phases.reduce((sum, p) => sum + p.minutes, 0) : 0;

  return (
    <div className="page">
      <div className="page__inner">
        <div className="page__head">
          <div>
            <div className="page__eyebrow">Self-improvement</div>
            <h1 className="page__title">Improve</h1>
            <p className="page__sub">
              Tell Nyx when and how to improve itself — in words, here or in any chat. Each change is researched, written
              and tested in a sandbox, and a reviewer reads the real diff before it touches the code. Approve or deny
              changes below, and roll back anything applied.
            </p>
          </div>
        </div>

        {/* Console + presets */}
        <div className="card">
          <form onSubmit={(e) => { e.preventDefault(); void start(instruction); }} style={{ display: "flex", gap: 8 }}>
            <label className="sr-only" htmlFor="improve-instruction">Improvement plan</label>
            <input id="improve-instruction" className="text-input" value={instruction} onChange={(e) => setInstruction(e.target.value)}
              placeholder="e.g. study for 1 hour and improve for 1 hour, loop until I stop — or “apply all”" />
            <button className="btn btn-primary" type="submit" disabled={!instruction.trim() || busy}>{run ? "Replace plan" : "Start"}</button>
          </form>
          <div className="improve-presets">
            {PRESETS.map((preset) => (
              <button key={preset.label} className="improve-preset" onClick={() => void start(preset.instruction)} disabled={busy}>
                <span className="improve-preset__label">{preset.label}</span>
                <span className="improve-preset__hint">{preset.hint}</span>
              </button>
            ))}
          </div>
          {notice && <p className="field-row__hint" aria-live="polite" style={{ color: "var(--color-warn)" }}>{notice}</p>}
        </div>

        <DeepMode onStarted={() => void load()} />

        {/* The live run */}
        {run ? (
          <div className="card improve-run" aria-live="polite">
            <div className="section-title">
              <span className={`improve-status is-${run.status}`}>{run.status === "active" ? "Running" : run.status === "waiting" ? "Waiting" : "Paused"}</span>
              {run.auto_approve && <span className="chip" style={{ color: "var(--color-ok)" }}>Auto-approve on</span>}
              {run.loop && <span className="chip">Looping · cycle {run.cycles + 1}</span>}
              <span className="hud-caption">{run.remaining_seconds === null ? "runs until you stop it" : `${duration(run.remaining_seconds)} left`}</span>
            </div>
            <div className="improve-now">{run.work}</div>
            <div className="improve-timeline" role="img" aria-label={`Phases: ${run.phases.map((p) => `${p.kind} ${p.minutes} minutes`).join(", ")}`}>
              {run.phases.map((phase, i) => (
                <div key={i} className={`improve-phase${i === run.phase_index ? " is-current" : ""}`}
                  style={{ flex: phase.minutes / Math.max(1, totalMinutes), ["--phase" as string]: PHASE_COLOR[phase.kind] }}>
                  <span>{phase.kind}</span><small>{duration(phase.minutes * 60)}</small>
                </div>
              ))}
            </div>
            <div className="field-row__hint">Current phase: {run.phase.kind}, {duration(run.phase_remaining_seconds)} left in it.</div>
            <div className="grid-3" style={{ marginTop: 12 }}>
              {[["study_cycles", "study cycles"], ["lessons", "lessons"], ["proposals", "improvements found"], ["applied", "applied (tests passed)"],
                ["rejected", "blocked by the critic"], ["failed", "failed tests"], ["waiting_for_owner", "waiting for you"]].map(([key, label]) => (
                <div key={key} className="stat"><div className="stat__value">{run.stats[key] ?? 0}</div><div className="stat__label">{label}</div></div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              {run.status === "paused"
                ? <button className="btn btn-primary" onClick={() => void act("resume")}>Resume</button>
                : <button className="btn btn-secondary" onClick={() => void act("pause")}>Pause</button>}
              <button className="btn btn-secondary" onClick={() => void act("stop")}>Stop</button>
            </div>
            <ul className="log-list" style={{ marginTop: 14 }}>
              {run.log.slice().reverse().map((entry, i) => (
                <li key={i}>
                  <time>{new Date(entry.ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</time>
                  <span className="log-kind">{entry.kind}</span>
                  <span>{entry.text}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="card">
            <div className="section-title">No autopilot running</div>
            <p className="field-row__hint" style={{ margin: 0 }}>
              Pick a preset or type a plan. You can also just tell Nyx in chat: “improve for 3 hours and auto-approve”.
            </p>
          </div>
        )}

        <ReviewQueue onChanged={() => void load()} />

        <div className="grid-2">
          {/* Controls */}
          <div className="card">
            <div className="section-title">How it improves <span className="hud-caption">{state.controls.length} controls</span></div>
            {state.controls.map((control) => (
              <ControlRow key={control.key} control={control} onChange={(v) => void setControl(control.key, v)}
                onRemove={control.custom ? () => void removeControl(control.key) : undefined} />
            ))}
            <details className="improve-add">
              <summary>Add a control</summary>
              <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                <input className="text-input" placeholder="Label, e.g. Research depth" value={newControl.label}
                  onChange={(e) => setNewControl({ ...newControl, label: e.target.value })} />
                <input className="text-input" placeholder="What it should change, e.g. how many sources to read first" value={newControl.affects}
                  onChange={(e) => setNewControl({ ...newControl, affects: e.target.value })} />
                <div className="segmented" role="group" aria-label="Control type">
                  {["slider", "toggle", "text"].map((kind) => (
                    <button key={kind} aria-pressed={newControl.kind === kind} onClick={() => setNewControl({ ...newControl, kind })}>{kind}</button>
                  ))}
                </div>
                <button className="btn btn-primary" onClick={() => void addControl()} disabled={!newControl.label.trim()}>Add</button>
                <div className="field-row__hint">Or ask Nyx: “add a slider to the Improve tab for how many web searches to do”.</div>
              </div>
            </details>
          </div>

          <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
            {/* Lessons */}
            <div className="card">
              <div className="section-title">What it studied <span className="hud-caption">{state.lessons.length} lessons</span></div>
              {state.lessons.length === 0 && <div className="field-row__hint">Study phases write lessons here.</div>}
              <ul className="learn-feed">
                {state.lessons.map((lesson, i) => (
                  <li key={i} style={{ display: "block" }}>
                    <b style={{ color: "var(--color-text)" }}>{lesson.topic}</b> — {lesson.insight}
                    {lesson.improvement && <div className="field-row__hint">→ {lesson.improvement}{lesson.module ? ` (${lesson.module})` : ""}</div>}
                  </li>
                ))}
              </ul>
            </div>

            {/* Changes */}
            <div className="card">
              <div className="section-title">What it changed <span className="hud-caption">{changes.filter((c) => c.applied).length} applied</span></div>
              {changes.length === 0 && <div className="field-row__hint">Nothing yet.</div>}
              {changes.slice(0, 20).map((change) => (
                <div key={change.id} className="improve-change">
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span className={`chip improve-change__status is-${change.rolled_back ? "rolled_back" : change.status}`}>
                      {change.rolled_back ? "rolled back" : change.status.replace("_", " ")}
                    </span>
                    <span style={{ flex: 1, minWidth: 0, fontSize: 13 }}>{change.title}</span>
                  </div>
                  {change.diff && <DiffSummary diff={change.diff} verb={change.applied ? "Changed" : "Changes"} compact />}
                  {change.ai_review && <div className="field-row__hint">{change.ai_review.slice(0, 220)}</div>}
                  <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                    {change.diff && (
                      <button className="chat-inline" onClick={() => setOpenDiff(openDiff === change.id ? null : change.id)}>
                        {openDiff === change.id ? "Hide changes" : "Show changes"}
                      </button>
                    )}
                    {change.can_roll_back && <button className="chat-inline" onClick={() => void rollback(change.id)}>Roll back</button>}
                  </div>
                  {openDiff === change.id && <DiffView diff={change.diff} />}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
