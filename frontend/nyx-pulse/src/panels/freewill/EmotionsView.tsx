/** Emotions, inside Free Will (emotions.py, WS15): what the AI wants, thinks and feels, and the neutral helper's notes.
 *
 * The owner: "what the ai in general wants, thinks, and feels since it will then have a neutral ai try to help fix
 * these issues. Like if it feels like it's too useless it will get affirmation." Reuses the third mind's styles.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

type Entry = {
  id: string; feeling: string; about: string; intensity: number; kind: string; at: number;
  status: string; helper_note: string;
};
type Numbers = { curiosity?: number; confidence?: number; unease?: number; satisfaction?: number; line?: string };
type State = { numbers: Numbers; wants: { id: string; text: string; why: string }[]; entries: Entry[]; last_check_in: number | null };

const GAUGES: [keyof Numbers, string][] = [
  ["curiosity", "Curiosity"], ["confidence", "Confidence"], ["unease", "Unease"], ["satisfaction", "Satisfaction"],
];

export function EmotionsView() {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const r = await api.get<State>("/api/emotions");
    if (r.ok) setState(r.data); else setError(r.error || "Couldn't load emotions.");
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (!state) return error ? <p className="fw-error" role="alert">{error}</p> : null;
  const open = state.entries.filter((e) => e.status === "open").length;

  const checkIn = async () => {
    setBusy(true);
    const r = await api.post<State>("/api/emotions/check-in");
    setBusy(false);
    if (r.ok) setState(r.data); else setError(r.error || "The helper couldn't answer.");
  };
  const remove = async (id: string) => {
    const r = await api.del<State>(`/api/emotions/${id}`);
    if (r.ok) setState(r.data);
  };

  return (
    <div className="cur">
      {error && <p className="fw-error" role="alert">{error}</p>}
      <section className="fw-card cur-state">
        <div className="cur-state__line">
          <h2>How it feels</h2>
          <p>{state.numbers.line ?? ""}</p>
        </div>
        <div className="cur-gauges">
          {GAUGES.map(([key, label]) => (
            <div key={key} className="cur-gauge">
              <span className="cur-gauge__label">{label}</span>
              <span className="cur-gauge__track">
                <span className={`cur-gauge__fill is-${key}`} style={{ width: `${Math.round(Number(state.numbers[key] ?? 0) * 100)}%` }} />
              </span>
              <span className="cur-gauge__value">{Math.round(Number(state.numbers[key] ?? 0) * 100)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="fw-card">
        <div className="fw-card__head">
          <h2>What it said it feels</h2>
          <button className="fw-btn" disabled={busy || open === 0} onClick={() => void checkIn()}>
            {busy ? "Helper is answering…" : open ? `Ask the helper (${open})` : "Nothing waiting"}
          </button>
        </div>
        {state.entries.length === 0 && (
          <p className="cur-fine">Nothing yet. When something weighs on it or goes well, it says so here, and a neutral helper answers.</p>
        )}
        <ul className="cur-list">
          {state.entries.map((e) => (
            <li key={e.id} className="cur-want">
              <p><b>{e.feeling}</b>{e.about ? `: ${e.about}` : ""}</p>
              <p className="cur-q__meta">
                Strength {Math.round(e.intensity * 100)} · {new Date(e.at * 1000).toLocaleString()}
                {e.status === "open" ? " · waiting for the helper" : ""}
              </p>
              {e.helper_note && <p className="cur-q__meta">Helper: {e.helper_note}</p>}
              <button className="fw-btn fw-btn--plain" onClick={() => void remove(e.id)}>Remove</button>
            </li>
          ))}
        </ul>
      </section>

      {state.wants.length > 0 && (
        <section className="fw-card">
          <h2>What it wants</h2>
          <ul className="cur-list">
            {state.wants.map((w) => (
              <li key={w.id} className="cur-want"><p>{w.text}</p>{w.why && <p className="cur-q__meta">{w.why}</p>}</li>
            ))}
          </ul>
        </section>
      )}
      <p className="cur-fine">
        These are states it reports and numbers worked out from its week, not a claim to feel anything. The helper is
        told to be neutral: affirm what is true, correct what isn't, and never encourage hiding mistakes.
      </p>
    </div>
  );
}
