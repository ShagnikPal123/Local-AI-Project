/** The third mind, inside Free Will: what it wonders, wants, and got wrong.
 *
 * The owner asked for "a tab in the free will tab that shows its growth,
 * understanding, and wants in its lifetime". So this reads as a life, not a
 * dashboard: the state it is in now, what it has been asking, what it would
 * like to be able to do, and the mistakes it has written down — with the lesson
 * it took, because owning it was the point.
 *
 * Nothing here runs by itself unless the owner switches that on, and studying
 * one question is always a button.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

type Question = {
  id: string; text: string; why: string; topic: string; source: string; status: string;
  asked: number; interest: number; answer: string; learned: string; created_at: number; answered_at: number;
};
type Mistake = { id: string; what_happened: string; got_wrong: string; learned: string; kind: string; at: number };
type Want = { id: string; text: string; why: string; at: number };
type Feelings = { curiosity: number; confidence: number; unease: number; satisfaction: number; line: string };
type Growth = {
  asked: number; answered: number; open: number; mistakes: number; lessons: number; wants: number;
  concepts: number; parameters: number; level: string; since: number;
  history: { at: number; question: string; learned: string }[];
};
type State = {
  settings: { notice: boolean; study_alone: boolean; per_day: number };
  questions: Question[]; mistakes: Mistake[]; wants: Want[];
  feelings: Feelings; growth: Growth; next: Question | null; studied_today: number;
};

const FEELINGS: [keyof Feelings, string][] = [
  ["curiosity", "Curiosity"], ["confidence", "Confidence"], ["unease", "Unease"], ["satisfaction", "Satisfaction"],
];

function when(seconds: number): string {
  if (!seconds) return "";
  const days = Math.floor((Date.now() / 1000 - seconds) / 86400);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

export function CuriosityView() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState<"question" | "want" | "mistake">("question");
  const [result, setResult] = useState<{ question: string; answer: string; learned: string } | null>(null);

  const load = useCallback(async () => {
    const got = await api.get<State>("/api/curiosity");
    if (got.ok) { setState(got.data); setError(""); } else setError(got.error);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const file = useCallback(async () => {
    const text = draft.trim();
    if (text.length < 4) return;
    setBusy("file");
    await api.post("/api/curiosity/ask", { kind, text });
    setDraft("");
    setBusy("");
    void load();
  }, [draft, kind, load]);

  const study = useCallback(async (id: string) => {
    setBusy(id);
    const got = await api.post<{ ok: boolean; question?: string; answer?: string; learned?: string; error?: string }>(
      "/api/curiosity/study", { id }, 180_000);
    setBusy("");
    if (got.ok && got.data.ok) {
      setResult({ question: got.data.question ?? "", answer: got.data.answer ?? "", learned: got.data.learned ?? "" });
    } else {
      setError(got.ok ? String(got.data.error ?? "It could not answer that one.") : got.error);
    }
    void load();
  }, [load]);

  const drop = useCallback(async (id: string) => {
    await api.del(`/api/curiosity/questions/${id}`);
    void load();
  }, [load]);

  const save = useCallback(async (changes: Partial<State["settings"]>) => {
    const got = await api.put<{ settings: State["settings"] }>("/api/curiosity/settings", changes);
    if (got.ok) setState((s) => (s ? { ...s, settings: got.data.settings } : s));
  }, []);

  if (!state) return <p className="fw-muted">{error || "Loading…"}</p>;
  const open = state.questions.filter((q) => q.status === "open");
  const answered = state.questions.filter((q) => q.status === "answered");

  return (
    <div className="cur">
      {error && <p className="fw-error" role="alert">{error}</p>}

      <section className="fw-card cur-state">
        <div className="cur-state__line">
          <h2>How it is</h2>
          <p>{state.feelings.line}</p>
        </div>
        <div className="cur-gauges">
          {FEELINGS.map(([key, label]) => (
            <div key={key} className="cur-gauge">
              <span className="cur-gauge__label">{label}</span>
              <span className="cur-gauge__track">
                <span className={`cur-gauge__fill is-${key}`} style={{ width: `${Math.round(Number(state.feelings[key]) * 100)}%` }} />
              </span>
              <span className="cur-gauge__value">{Math.round(Number(state.feelings[key]) * 100)}</span>
            </div>
          ))}
        </div>
        <p className="cur-fine">
          These are four numbers worked out from the last week — open questions, answers found, mistakes and their
          lessons. They are a description of what it is working from, not a claim to feel anything.
        </p>
      </section>

      <section className="fw-card cur-growth">
        <h2>Its life so far</h2>
        <div className="cur-stats">
          <Stat value={state.growth.asked} label="questions asked" />
          <Stat value={state.growth.answered} label="answered" />
          <Stat value={state.growth.wants} label="things it wants" />
          <Stat value={state.growth.mistakes} label="mistakes owned" />
          <Stat value={state.growth.lessons} label="lessons kept" />
          <Stat value={state.growth.concepts.toLocaleString()} label="things in the brain" />
        </div>
        <p className="cur-fine">
          Wondering since {when(state.growth.since) || "today"}
          {state.growth.level ? ` · Nyx Core level ${state.growth.level}` : ""}
          {state.studied_today ? ` · looked into ${state.studied_today} today` : ""}
        </p>
      </section>

      <section className="fw-card">
        <div className="fw-card__head">
          <h2>Questions it has</h2>
          <span className="fw-muted">{open.length} open</span>
        </div>
        <div className="cur-file">
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} aria-label="What to file">
            <option value="question">A question</option>
            <option value="want">Something it wants</option>
            <option value="mistake">A mistake to own</option>
          </select>
          <input value={draft} onChange={(e) => setDraft(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") void file(); }}
                 placeholder={kind === "question" ? "Something for it to wonder about…"
                   : kind === "want" ? "Something it should be able to do…" : "What went wrong…"} />
          <button className="fw-btn" disabled={busy === "file" || draft.trim().length < 4} onClick={() => void file()}>File it</button>
        </div>
        {open.length === 0 && <p className="fw-muted">Nothing open. Questions arrive when it runs into something it doesn't know.</p>}
        <ul className="cur-list">
          {open.map((q) => (
            <li key={q.id} className="cur-q">
              <div className="cur-q__main">
                <p className="cur-q__text">{q.text}</p>
                <p className="cur-q__meta">
                  {q.source === "owner" ? "you asked it" : q.source === "itself" ? "it asked itself" : `came up in ${q.source}`}
                  {q.asked > 1 ? ` · came back ${q.asked}×` : ""} · {when(q.created_at)}
                </p>
              </div>
              <span className="cur-q__interest" title={`${Math.round(q.interest * 100)}% interesting to it`}>
                <span style={{ width: `${Math.round(q.interest * 100)}%` }} />
              </span>
              <button className="fw-btn" disabled={busy === q.id} onClick={() => void study(q.id)}>
                {busy === q.id ? "Looking…" : "Look into it"}
              </button>
              <button className="fw-btn fw-btn--plain" onClick={() => void drop(q.id)} aria-label="Let this one go">Let go</button>
            </li>
          ))}
        </ul>
      </section>

      {result && (
        <section className="fw-card cur-result">
          <h2>What it found</h2>
          <p className="cur-q__text">{result.question}</p>
          <p>{result.answer}</p>
          {result.learned && <p className="cur-learned"><b>It keeps:</b> {result.learned}</p>}
          <button className="fw-btn fw-btn--plain" onClick={() => setResult(null)}>Close</button>
        </section>
      )}

      {state.wants.length > 0 && (
        <section className="fw-card">
          <h2>What it wants</h2>
          <ul className="cur-list">
            {state.wants.map((w) => (
              <li key={w.id} className="cur-want">
                <p>{w.text}</p>
                {w.why && <p className="cur-q__meta">{w.why}</p>}
              </li>
            ))}
          </ul>
          <p className="cur-fine">Wants are filed, never acted on. Building one is the Apply tab, with you pressing the button.</p>
        </section>
      )}

      {state.mistakes.length > 0 && (
        <section className="fw-card">
          <h2>Mistakes it owns</h2>
          <ul className="cur-list">
            {state.mistakes.map((m) => (
              <li key={m.id} className="cur-mistake">
                <p>{m.what_happened}</p>
                {m.got_wrong && <p className="cur-q__meta">It got wrong: {m.got_wrong}</p>}
                {m.learned ? <p className="cur-learned"><b>It takes:</b> {m.learned}</p>
                           : <p className="cur-q__meta">No lesson written yet.</p>}
                <p className="cur-q__meta">{when(m.at)}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {answered.length > 0 && (
        <section className="fw-card">
          <h2>What it has learned</h2>
          <ul className="cur-list">
            {answered.slice(0, 12).map((q) => (
              <li key={q.id} className="cur-answered">
                <p className="cur-q__text">{q.text}</p>
                {q.learned && <p className="cur-learned">{q.learned}</p>}
                <p className="cur-q__meta">{when(q.answered_at)}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="fw-card">
        <h2>How much of this happens on its own</h2>
        <label className="cur-check">
          <input type="checkbox" checked={state.settings.notice} onChange={(e) => void save({ notice: e.target.checked })} />
          File questions when it runs into something it doesn't know
        </label>
        <label className="cur-check">
          <input type="checkbox" checked={state.settings.study_alone} onChange={(e) => void save({ study_alone: e.target.checked })} />
          Look things up by itself when nothing else is happening
        </label>
        <label className="cur-field">
          <span>At most per day</span>
          <input type="number" min={0} max={24} value={state.settings.per_day}
                 onChange={(e) => void save({ per_day: Number(e.target.value) })} />
        </label>
        <p className="cur-fine">
          Studying on its own only runs while Free Will is allowed and not paused, and it never joins a conversation —
          it files what it learns for later.
        </p>
      </section>
    </div>
  );
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="cur-stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}
