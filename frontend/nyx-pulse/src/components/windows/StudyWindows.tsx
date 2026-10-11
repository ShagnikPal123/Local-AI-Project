/** Quiz bar and Screenshot → Code — chat windows (owner, 2026-10-10).
 *
 * Quiz: "allow for the creation of quizzes similar to gemini so it opens on the right as a bar the user can use and
 * they can have flashcards, the AI analyses the time they take and answers they give". Ichos's make_quiz tool writes
 * the questions; this bar times every answer, then sends the results back so Ichos can analyse them in the chat.
 *
 * Screenshot → Code: drop a UI image, pick a stack, get a page (routes_workbench /api/s2c). The preview is an iframe
 * with srcdoc and sandbox="allow-scripts" — no same-origin, so the generated page can never touch Ichos's storage.
 */

import { useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import "./study.css";

// --- Quiz ---------------------------------------------------------------------------------------------------

interface Question { q: string; choices?: string[]; answer: string; explain?: string }
interface Card { front: string; back: string }

export function QuizWindow({ title = "Quiz", questions = [], cards = [] }: { title?: string; questions?: Question[]; cards?: Card[] }) {
  const [mode, setMode] = useState<"quiz" | "cards">(questions.length ? "quiz" : "cards");
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [log, setLog] = useState<{ q: string; given: string; correct: boolean; seconds: number }[]>([]);
  const started = useRef(Date.now());
  const [flip, setFlip] = useState(false);
  const [sent, setSent] = useState(false);
  useEffect(() => { started.current = Date.now(); setPicked(null); setTyped(""); }, [i]);

  const q = questions[i];
  const done = mode === "quiz" && i >= questions.length;
  const check = (given: string) => {
    if (!q || picked !== null) return;
    const correct = given.trim().toLowerCase() === q.answer.trim().toLowerCase();
    setPicked(given);
    setLog((l) => [...l, { q: q.q, given, correct, seconds: Math.round((Date.now() - started.current) / 100) / 10 }]);
  };
  const score = log.filter((l) => l.correct).length;
  const sendResults = () => {
    const lines = log.map((l, k) => `${k + 1}. ${l.correct ? "✓" : "✗"} ${l.seconds}s — ${l.q} (answered: ${l.given})`).join("\n");
    window.dispatchEvent(new CustomEvent("nyx:chat-send", { detail: { text:
      `I finished the quiz "${title}": ${score}/${log.length}.\n${lines}\nAnalyse my answers and timing: what I know, what I guessed, what to review next.` } }));
    setSent(true);
  };

  return (
    <div className="study">
      <header className="study__head">
        <b>{title}</b>
        <div className="segmented" role="group" aria-label="Quiz or flashcards">
          {questions.length > 0 && <button type="button" aria-pressed={mode === "quiz"} onClick={() => setMode("quiz")}>Quiz</button>}
          {cards.length > 0 && <button type="button" aria-pressed={mode === "cards"} onClick={() => { setMode("cards"); setI(0); setFlip(false); }}>Flashcards</button>}
        </div>
      </header>
      {mode === "quiz" && !done && q && (
        <div className="study__body">
          <div className="study__progress"><span style={{ width: `${(i / questions.length) * 100}%` }} /></div>
          <p className="study__count">Question {i + 1} of {questions.length}</p>
          <h3 className="study__q">{q.q}</h3>
          {q.choices?.length ? (
            <div className="study__choices">
              {q.choices.map((c) => (
                <button key={c} type="button" disabled={picked !== null}
                  className={`study__choice${picked !== null && c === q.answer ? " is-right" : ""}${picked === c && c !== q.answer ? " is-wrong" : ""}`}
                  onClick={() => check(c)}>{c}</button>
              ))}
            </div>
          ) : (
            <form className="study__type" onSubmit={(e) => { e.preventDefault(); check(typed); }}>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Your answer" aria-label="Your answer" disabled={picked !== null} />
              <button className="btn btn-primary" disabled={picked !== null || !typed.trim()}>Check</button>
            </form>
          )}
          {picked !== null && (
            <div className={`study__feedback ${picked.trim().toLowerCase() === q.answer.trim().toLowerCase() ? "is-right" : "is-wrong"}`}>
              <b>{picked.trim().toLowerCase() === q.answer.trim().toLowerCase() ? "Right" : `Answer: ${q.answer}`}</b>
              {q.explain && <p>{q.explain}</p>}
              <button className="btn btn-primary" onClick={() => setI(i + 1)}>{i + 1 < questions.length ? "Next" : "See results"}</button>
            </div>
          )}
        </div>
      )}
      {done && (
        <div className="study__body">
          <h3 className="study__q">{score} of {log.length} right</h3>
          <p className="study__count">Average {(log.reduce((t, l) => t + l.seconds, 0) / Math.max(1, log.length)).toFixed(1)} s per question</p>
          <ul className="study__log">
            {log.map((l, k) => <li key={k} className={l.correct ? "is-right" : "is-wrong"}>{l.correct ? "✓" : "✗"} {l.q} <small>{l.seconds}s</small></li>)}
          </ul>
          <div className="study__row">
            <button className="btn btn-primary" disabled={sent} onClick={sendResults}>{sent ? "Sent to Ichos" : "Ask Ichos to analyse this"}</button>
            <button className="btn btn-secondary" onClick={() => { setI(0); setLog([]); setSent(false); }}>Try again</button>
          </div>
        </div>
      )}
      {mode === "cards" && cards.length > 0 && (
        <div className="study__body">
          <p className="study__count">Card {i + 1} of {cards.length} · click to flip</p>
          <button type="button" className={`study__card${flip ? " is-flipped" : ""}`} onClick={() => setFlip((f) => !f)} aria-label="Flip the card">
            <span className="study__face">{cards[i % cards.length].front}</span>
            <span className="study__face study__face--back">{cards[i % cards.length].back}</span>
          </button>
          <div className="study__row">
            <button className="btn btn-secondary" onClick={() => { setI((i - 1 + cards.length) % cards.length); setFlip(false); }}>← Back</button>
            <button className="btn btn-primary" onClick={() => { setI((i + 1) % cards.length); setFlip(false); }}>Next →</button>
          </div>
        </div>
      )}
      {!questions.length && !cards.length && (
        <p className="study__count study__body">Ask in the chat: “quiz me on photosynthesis” or “flashcards for Spanish verbs”.</p>
      )}
    </div>
  );
}

// --- Screenshot → Code --------------------------------------------------------------------------------------

const STACKS: [string, string][] = [["html_tailwind", "HTML + Tailwind"], ["html_css", "HTML + CSS"], ["react_tailwind", "React"], ["vue_tailwind", "Vue"], ["bootstrap", "Bootstrap"]];

export function ScreenshotCodeWindow({ path = "", stack: initialStack = "html_tailwind", notes: initialNotes = "" }: { path?: string; stack?: string; notes?: string }) {
  const [upload, setUpload] = useState<{ id: string; name: string; url: string } | null>(null);
  const [stack, setStack] = useState(initialStack);
  const [notes, setNotes] = useState(initialNotes);
  const [html, setHtml] = useState("");
  const [view, setView] = useState<"preview" | "code">("preview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [change, setChange] = useState("");
  const [saveAs, setSaveAs] = useState("");
  const [saved, setSaved] = useState("");

  const take = async (file: File) => {
    setError("");
    const r = await uploadFile(file);
    if (r.ok) setUpload({ id: r.data.id, name: file.name, url: URL.createObjectURL(file) }); else setError(r.error);
  };
  const run = async (instruction = "") => {
    setBusy(true); setError("");
    const r = await api.post<{ html: string }>("/api/s2c", { upload_id: upload?.id ?? "", path: upload ? "" : path, stack, notes,
      current: instruction ? html : "", instruction }, 240000);
    setBusy(false);
    if (r.ok) { setHtml(r.data.html); setChange(""); } else setError(r.error);
  };
  const save = async () => {
    const r = await api.post<{ saved: string }>("/api/s2c/save", { path: saveAs, html });
    if (r.ok) setSaved(r.data.saved); else setError(r.error);
  };

  return (
    <div className="study s2c" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) void take(f); }}>
      <header className="study__head">
        <b>Screenshot → Code</b>
        <select value={stack} onChange={(e) => setStack(e.target.value)} aria-label="Stack">
          {STACKS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </header>
      <div className="s2c__input">
        <label className="s2c__drop">
          {upload ? <img src={upload.url} alt={upload.name} /> : <span>{path ? `Using ${path.split(/[\\/]/).pop()}` : "Drop a screenshot here, or click to pick one"}</span>}
          <input type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void take(f); }} />
        </label>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Notes (optional): dark mode, my brand colour…" aria-label="Notes" />
        <button className="btn btn-primary" disabled={busy || (!upload && !path)} onClick={() => void run()}>{busy ? "Writing the page…" : html ? "Write it again" : "Make the page"}</button>
      </div>
      {error && <p className="study__error" role="alert">{error}</p>}
      {html && (
        <>
          <div className="study__row">
            <div className="segmented" role="group" aria-label="View">
              <button type="button" aria-pressed={view === "preview"} onClick={() => setView("preview")}>Preview</button>
              <button type="button" aria-pressed={view === "code"} onClick={() => setView("code")}>Code</button>
            </div>
            <button className="btn btn-ghost" onClick={() => void navigator.clipboard?.writeText(html)}>Copy</button>
          </div>
          {view === "preview"
            ? <iframe className="s2c__frame" title="Preview of the generated page" sandbox="allow-scripts" srcDoc={html} />
            : <pre className="s2c__code">{html}</pre>}
          <form className="study__type" onSubmit={(e) => { e.preventDefault(); if (change.trim()) void run(change); }}>
            <input value={change} onChange={(e) => setChange(e.target.value)} placeholder="Change something: make the header sticky…" aria-label="Change" />
            <button className="btn btn-secondary" disabled={busy || !change.trim()}>Apply</button>
          </form>
          <form className="study__type" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <input value={saveAs} onChange={(e) => setSaveAs(e.target.value)} placeholder="Save as… C:\\Users\\you\\Desktop\\page.html" aria-label="Save as" />
            <button className="btn btn-secondary" disabled={!saveAs.trim()}>Save</button>
          </form>
          {saved && <p className="study__count">Saved to {saved}</p>}
        </>
      )}
    </div>
  );
}
