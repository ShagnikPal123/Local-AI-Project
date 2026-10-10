/** The court, drawn as a courtroom beside the chat (owner, 2026-10-10; court.py).
 *
 * The bench of three judges at the top, one counsel table per side facing it, the clerk below. Whoever is speaking
 * glows with the AI-presence outline (the one place that styling belongs: an AI acting right now) and their words
 * show in a bubble; the full transcript runs underneath, round by round. When the judges have voted, each judge
 * shows their pick and the winning table lights up. The owner can pick a winner at any point, or stop the case.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import "./court.css";

interface Side { id: string; name: string; stance: string; counsel: string }
interface Line { speaker: string; role: "counsel" | "judge"; round: string; side: string; text: string; at: number }
interface Case {
  id: string;
  questions: string[];
  status: "framing" | "arguing" | "deliberating" | "verdict" | "stopped" | "failed" | "decided";
  sides: Side[];
  judges: string[];
  transcript: Line[];
  speaking: string;
  verdict: { winner: string; split: boolean; votes: { judge: string; side: string; reason: string }[] } | null;
  owner_pick: string;
  origin: string;
  note: string;
}

const STATUS: Record<Case["status"], string> = {
  framing: "The clerk is framing the sides…",
  arguing: "Counsel are arguing",
  deliberating: "The judges are deliberating…",
  verdict: "Verdict",
  stopped: "Stopped",
  failed: "Could not finish",
  decided: "You decided",
};

const SIDE_COLORS = ["#a594ff", "#60cdff", "#f7b267"];

export function CourtWindow({ caseId }: { caseId?: string }) {
  const [current, setCurrent] = useState<Case | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [past, setPast] = useState<{ id: string; questions: string[]; status: string; origin: string }[]>([]);
  useEffect(() => {
    if (current) return;
    void api.get<{ cases: { id: string; questions: string[]; status: string; origin: string }[] }>("/api/court").then((r) => {
      if (r.ok) setPast(r.data.cases.slice(0, 8));
    });
  }, [current]);

  useEffect(() => {
    if (!caseId) return;
    void api.get<Case>(`/api/court/${caseId}`).then((r) => { if (r.ok) setCurrent(r.data); });
  }, [caseId]);
  useEffect(() => onWorkspaceEvent((event) => {
    const incoming = (event as { type: string; case?: Case }).case;
    if (event.type === "court.update" && incoming && (!current || incoming.id === current.id || (!caseId && !current))) {
      setCurrent(incoming);
    }
  }), [current, caseId]);

  async function open() {
    if (!question.trim()) return;
    setBusy(true);
    setError("");
    const r = await api.post<Case>("/api/court", { questions: question, origin: "chat" });
    setBusy(false);
    if (r.ok) { setCurrent(r.data); setQuestion(""); } else setError(r.error);
  }

  const colorOf = useMemo(() => {
    const map: Record<string, string> = {};
    (current?.sides ?? []).forEach((s, i) => { map[s.id] = SIDE_COLORS[i % SIDE_COLORS.length]; });
    return map;
  }, [current?.sides]);

  if (!current) {
    return (
      <div className="court court--empty">
        <div className="court__empty">
          <h2>Put a question on trial</h2>
          <p>Counsel take sides and argue it in three rounds; three judges vote. You can pick the winner yourself.</p>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3}
            placeholder="One question per line — e.g. Should Ichos keep a light theme?" aria-label="Question for the court" />
          {error && <p className="court__error" role="alert">{error}</p>}
          <button type="button" className="btn btn-primary" disabled={busy || !question.trim()} onClick={() => void open()}>
            {busy ? "Opening the case…" : "Open the case"}
          </button>
          {past.length > 0 && (
            <div className="court__past">
              <h3>Earlier cases</h3>
              {past.map((c) => (
                <button key={c.id} type="button" className="court__past-item" onClick={() => void api.get<Case>(`/api/court/${c.id}`).then((r) => { if (r.ok) setCurrent(r.data); })}>
                  <span>{c.questions[0]}</span>
                  <small>{c.origin} · {STATUS[c.status as Case["status"]] ?? c.status}</small>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  const last = [...current.transcript].reverse().find((l) => l.speaker === current.speaking);
  const winner = current.owner_pick || current.verdict?.winner || "";
  const running = ["framing", "arguing", "deliberating"].includes(current.status);
  const voteOf = (judge: string) => current.verdict?.votes.find((v) => v.judge === judge)
    ?? current.transcript.filter((l) => l.role === "judge" && l.speaker === judge).map((l) => ({ judge, side: l.side, reason: l.text }))[0];

  async function pick(side: string) {
    const r = await api.post<Case>(`/api/court/${current!.id}/pick`, { side });
    if (r.ok) setCurrent(r.data);
  }

  return (
    <div className="court">
      <header className="court__head">
        <div className="court__question">
          {current.questions.map((q) => <h2 key={q}>{q}</h2>)}
        </div>
        <span className={`court__status is-${current.status}`} aria-live="polite">{STATUS[current.status]}</span>
        {running && <button type="button" className="btn btn-secondary" onClick={() => void api.post(`/api/court/${current.id}/stop`, {})}>Stop the case</button>}
        <button type="button" className="btn btn-ghost" onClick={() => setCurrent(null)}>New case</button>
      </header>

      {/* The courtroom */}
      <div className="court__room" role="img" aria-label={`Courtroom: ${current.judges.length} judges, ${current.sides.length} sides. ${current.speaking ? `${current.speaking} is speaking.` : ""}`}>
        <div className="court__bench">
          {current.judges.map((judge) => {
            const vote = voteOf(judge);
            return (
              <div key={judge} className={`court__seat is-judge${current.speaking === judge ? " is-speaking" : ""}`}>
                <span className="court__avatar" aria-hidden="true">⚖</span>
                <span className="court__name">{judge}</span>
                {vote?.side && <span className="court__vote" style={{ color: colorOf[vote.side] }}>→ {current.sides.find((s) => s.id === vote.side)?.name}</span>}
              </div>
            );
          })}
        </div>
        <div className="court__floor">
          {current.sides.map((side) => (
            <div key={side.id}
              className={`court__table${current.speaking === side.counsel ? " is-speaking" : ""}${winner === side.id ? " is-winner" : ""}`}
              style={{ ["--side" as string]: colorOf[side.id] }}>
              <span className="court__avatar" aria-hidden="true">{side.name.slice(0, 1)}</span>
              <span className="court__name">{side.counsel}</span>
              <span className="court__stance">{side.stance}</span>
              {winner === side.id && <span className="court__crown">{current.owner_pick ? "Your pick" : "Wins"}</span>}
              <button type="button" className="btn btn-ghost court__pick" onClick={() => void pick(side.id)} aria-label={`Pick ${side.name} as the winner`}>
                Pick this side
              </button>
            </div>
          ))}
          {current.sides.length === 0 && <div className="court__clerk is-speaking">Clerk — framing the sides…</div>}
        </div>
        {last && running && (
          <div className="court__bubble" style={{ ["--side" as string]: colorOf[last.side] ?? "var(--color-accent)" }}>
            <b>{last.speaker}</b> · {last.round}
            <p>{last.text}</p>
          </div>
        )}
        {current.verdict && (
          <div className="court__verdict">
            {current.verdict.split ? "The bench is split — pick a side to decide." :
              `Verdict: ${current.sides.find((s) => s.id === current.verdict!.winner)?.name} (${current.verdict.votes.filter((v) => v.side === current.verdict!.winner).length} of ${current.verdict.votes.length} judges)`}
          </div>
        )}
        {current.note && <p className="court__error">{current.note}</p>}
      </div>

      {/* Transcript */}
      <ol className="court__transcript" aria-label="Transcript">
        {current.transcript.map((line, i) => (
          <li key={i} className={`court__line is-${line.role}`} style={{ ["--side" as string]: colorOf[line.side] ?? "var(--color-neutral-600)" }}>
            <span className="court__line-who">{line.speaker} <small>{line.round}</small></span>
            <p>{line.text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
