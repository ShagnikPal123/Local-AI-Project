/** Study material made from a note: practice quizzes, flashcards, step-by-step solutions, a focus timer. */

import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { Markdown } from "../../components/chat/Markdown";

export interface QuizQuestion {
  type: "mc" | "tf" | "short";
  question: string;
  options?: string[];
  answer: string | boolean;
  explanation?: string;
}
export interface Quiz { id: string; title: string; questions: QuizQuestion[]; model?: string; attempts?: { score: number; total: number; at: number }[] }
export interface Card { id: string; front: string; back: string; box: number }
export interface Deck { id: string; title: string; cards: Card[]; model?: string }
export interface Steps { id: string; question: string; steps: { title: string; detail: string }[]; answer: string; check?: string; model?: string }

type Verdict = "correct" | "partial" | "incorrect";

export function QuizView({ noteId, quiz, onDone }: { noteId: string; quiz: Quiz; onDone?: () => void }) {
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<string | boolean | null>(null);
  const [typed, setTyped] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [feedback, setFeedback] = useState("");
  const [checking, setChecking] = useState(false);
  const [score, setScore] = useState(0);
  const [finished, setFinished] = useState(false);
  const q = quiz.questions[index];

  function reset() {
    setIndex(0); setPicked(null); setTyped(""); setVerdict(null); setFeedback(""); setScore(0); setFinished(false);
  }

  async function check() {
    if (!q) return;
    if (q.type === "short") {
      setChecking(true);
      const result = await api.post<{ verdict: Verdict; feedback: string }>("/api/notes/grade", { question: q.question, expected: String(q.answer), given: typed });
      setChecking(false);
      const v = result.ok ? result.data.verdict : "partial";
      setVerdict(v);
      setFeedback(result.ok ? result.data.feedback : "Compare with the model answer.");
      setScore((s) => s + (v === "correct" ? 1 : v === "partial" ? 0.5 : 0));
      return;
    }
    const right = picked === q.answer;
    setVerdict(right ? "correct" : "incorrect");
    setScore((s) => s + (right ? 1 : 0));
  }

  function next() {
    if (index + 1 >= quiz.questions.length) {
      setFinished(true);
      void api.patch(`/api/notes/${noteId}/quizzes/${quiz.id}`, { attempt: { score, total: quiz.questions.length } });
      onDone?.();
      return;
    }
    setIndex((i) => i + 1); setPicked(null); setTyped(""); setVerdict(null); setFeedback("");
  }

  if (finished) {
    const pct = Math.round((score / quiz.questions.length) * 100);
    return (
      <div className="study-card">
        <div className="study-card__eyebrow">{quiz.title}</div>
        <div className="study-score" aria-live="polite"><b>{pct}%</b> · {score} of {quiz.questions.length}</div>
        <p className="study-card__hint">{pct >= 80 ? "Strong — try the flashcards to lock it in." : "Review the explanations, then retake it tomorrow — spacing helps it stick."}</p>
        <button className="btn btn-primary" onClick={reset}>Retake Quiz</button>
      </div>
    );
  }
  if (!q) return null;

  return (
    <div className="study-card">
      <div className="study-card__eyebrow">{quiz.title} · Question {index + 1} of {quiz.questions.length}</div>
      <div className="study-progress" aria-hidden="true"><div style={{ width: `${(index / quiz.questions.length) * 100}%` }} /></div>
      <div className="study-card__question"><Markdown text={q.question} /></div>

      {q.type === "mc" && (
        <div className="study-options" role="radiogroup" aria-label="Answers">
          {q.options!.map((option) => {
            const state = verdict && option === q.answer ? " is-right" : verdict && option === picked ? " is-wrong" : "";
            return (
              <button key={option} role="radio" aria-checked={picked === option} disabled={Boolean(verdict)}
                className={`study-option${picked === option ? " is-picked" : ""}${state}`} onClick={() => setPicked(option)}>
                {option}
              </button>
            );
          })}
        </div>
      )}
      {q.type === "tf" && (
        <div className="study-options study-options--row" role="radiogroup" aria-label="True or false">
          {[true, false].map((value) => {
            const state = verdict && value === q.answer ? " is-right" : verdict && value === picked ? " is-wrong" : "";
            return (
              <button key={String(value)} role="radio" aria-checked={picked === value} disabled={Boolean(verdict)}
                className={`study-option${picked === value ? " is-picked" : ""}${state}`} onClick={() => setPicked(value)}>
                {value ? "True" : "False"}
              </button>
            );
          })}
        </div>
      )}
      {q.type === "short" && (
        <textarea className="study-answer" rows={3} value={typed} disabled={Boolean(verdict)} placeholder="Your answer"
          onChange={(e) => setTyped(e.target.value)} />
      )}

      {verdict && (
        <div className={`study-verdict is-${verdict}`} aria-live="polite">
          <b>{verdict === "correct" ? "Correct" : verdict === "partial" ? "Partly right" : "Not quite"}</b>
          {feedback && <span> — {feedback}</span>}
          {(q.type === "short" || verdict !== "correct") && <div className="study-verdict__answer">Answer: {typeof q.answer === "boolean" ? (q.answer ? "True" : "False") : q.answer}</div>}
          {q.explanation && <div className="study-verdict__why">{q.explanation}</div>}
        </div>
      )}

      <div className="study-card__actions">
        {!verdict ? (
          <button className="btn btn-primary" onClick={() => void check()}
            disabled={checking || (q.type === "short" ? !typed.trim() : picked === null)}>{checking ? "Checking…" : "Check"}</button>
        ) : (
          <button className="btn btn-primary" onClick={next}>{index + 1 >= quiz.questions.length ? "See Score" : "Next Question"}</button>
        )}
      </div>
    </div>
  );
}

export function DeckView({ noteId, deck }: { noteId: string; deck: Deck }) {
  const [cards, setCards] = useState(deck.cards);
  const [flipped, setFlipped] = useState(false);
  const queue = useMemo(() => [...cards].sort((a, b) => a.box - b.box), [cards]);
  const [position, setPosition] = useState(0);
  const card = queue[position % Math.max(1, queue.length)];
  const learned = cards.filter((c) => c.box >= 3).length;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea")) return;
      if (e.key === " ") { e.preventDefault(); setFlipped((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function grade(knew: boolean) {
    if (!card) return;
    const box = knew ? Math.min(5, card.box + 1) : 1;
    setCards((all) => all.map((c) => (c.id === card.id ? { ...c, box } : c)));
    void api.patch(`/api/notes/${noteId}/decks/${deck.id}`, { cards: [{ id: card.id, box }] });
    setFlipped(false);
    setPosition((p) => p + 1);
  }

  if (!card) return null;
  return (
    <div className="study-card">
      <div className="study-card__eyebrow">{deck.title} · {learned} of {cards.length} learned</div>
      <button className={`flashcard${flipped ? " is-flipped" : ""}`} onClick={() => setFlipped((v) => !v)}
        aria-label={flipped ? "Show the front" : "Show the answer"}>
        <span className="flashcard__face flashcard__front"><Markdown text={card.front} /></span>
        <span className="flashcard__face flashcard__back"><Markdown text={card.back} /></span>
      </button>
      <p className="study-card__hint">Tap the card or press Space to flip.</p>
      <div className="study-card__actions">
        <button className="btn btn-secondary" onClick={() => grade(false)} disabled={!flipped}>Again</button>
        <button className="btn btn-primary" onClick={() => grade(true)} disabled={!flipped}>Got It</button>
      </div>
    </div>
  );
}

export function StepsView({ steps }: { steps: Steps }) {
  const [shown, setShown] = useState(1);
  const [answer, setAnswer] = useState(false);
  return (
    <div className="study-card">
      <div className="study-card__eyebrow">Step by step</div>
      <div className="study-card__question"><Markdown text={steps.question} /></div>
      <ol className="study-steps">
        {steps.steps.slice(0, shown).map((step, i) => (
          <li key={i}>
            {step.title && <b>{step.title}</b>}
            <Markdown text={step.detail} />
          </li>
        ))}
      </ol>
      <div className="study-card__actions">
        {shown < steps.steps.length ? (
          <>
            <button className="btn btn-secondary" onClick={() => setShown(steps.steps.length)}>Show All</button>
            <button className="btn btn-primary" onClick={() => setShown((n) => n + 1)}>Next Step</button>
          </>
        ) : !answer ? (
          <button className="btn btn-primary" onClick={() => setAnswer(true)}>Show Answer</button>
        ) : null}
      </div>
      {answer && (
        <div className="study-verdict is-correct">
          <b>Answer</b>
          <Markdown text={steps.answer || "See the last step."} />
          {steps.check && <div className="study-verdict__why">Check: {steps.check}</div>}
        </div>
      )}
    </div>
  );
}

/** A 25/5 focus timer — the study rhythm that pairs with practice testing. */
export function FocusTimer() {
  const [mode, setMode] = useState<"focus" | "break">("focus");
  const [left, setLeft] = useState(25 * 60);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => {
      setLeft((s) => {
        if (s > 1) return s - 1;
        const next = mode === "focus" ? "break" : "focus";
        setMode(next);
        try { new Notification(next === "break" ? "Focus done — take 5 minutes." : "Break over — back to it."); } catch { /* notifications off */ }
        return next === "break" ? 5 * 60 : 25 * 60;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [running, mode]);

  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return (
    <div className="focus-timer" aria-label="Focus timer">
      <span className="focus-timer__mode">{mode === "focus" ? "Focus" : "Break"}</span>
      <span className="focus-timer__time" role="timer" aria-live="off">{mm}:{ss}</span>
      <button className="btn btn-secondary" onClick={() => setRunning((v) => !v)}>{running ? "Pause" : "Start"}</button>
      <button className="btn btn-secondary" onClick={() => { setRunning(false); setMode("focus"); setLeft(25 * 60); }} aria-label="Reset timer">Reset</button>
    </div>
  );
}
