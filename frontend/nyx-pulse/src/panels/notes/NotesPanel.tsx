/** The Notes tab: capture a class, then study it (Request G13).
 *
 * Three columns on a wide screen — notebooks and notes, the note itself, and the
 * study material made from it — collapsing to one column with a switcher on a
 * narrow one. Capture lives in the note's toolbar (Dictate, Record Lecture,
 * Draw); study actions sit right under it, and act on the selected text when
 * there is a selection.
 *
 * The thesis: a lecture becomes a quiz you can take before the next class.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import { Markdown } from "../../components/chat/Markdown";
import { pushToast, useToasts, dismissToast } from "../../state/toastStore";
import { Toasts } from "../../components/chat";
import { DrawingPad } from "./DrawingPad";
import { listen, speechRecognition, type Listener } from "./speech";
import { DeckView, FocusTimer, QuizView, StepsView, type Deck, type Quiz, type Steps } from "./StudyViews";
import { SlidesDrop, SlidesStudy } from "./SlidesStudy";
import "./notes.css";

interface Notebook { id: string; title: string }
interface NoteSummary { id: string; notebook_id: string; title: string; kind: string; updated_at: number; pinned: boolean; preview: string; words: number }
interface Note extends NoteSummary { body: string; quizzes: Quiz[]; decks: Deck[]; steps: Steps[] }
interface TextResult { title: string; text: string; model: string; action: string }

const QUICK: { action: string; label: string }[] = [
  { action: "detail", label: "More Detail" },
  { action: "quiz", label: "Quiz Me" },
  { action: "flashcards", label: "Flashcards" },
  { action: "steps", label: "Step by Step" },
];
const MORE: { action: string; label: string; needs?: string }[] = [
  { action: "organize", label: "Organize into Notes" },
  { action: "summarize", label: "Summarize" },
  { action: "clean", label: "Clean Up Transcript" },
  { action: "glossary", label: "Key Terms" },
  { action: "study_guide", label: "Study Guide" },
  { action: "exam", label: "Likely Exam Questions" },
  { action: "ask", label: "Ask About This Note", needs: "Your question" },
  { action: "cite", label: "Make a Citation", needs: "Title, author, year, link" },
  { action: "study_plan", label: "Study Plan", needs: "Exam date and topics" },
];

function when(ts: number): string {
  const d = new Date(ts * 1000);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function NotesPanel() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [summaries, setSummaries] = useState<NoteSummary[]>([]);
  const [book, setBook] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const [preview, setPreview] = useState(false);
  const [pane, setPane] = useState<"list" | "note" | "study">("note");
  const [working, setWorking] = useState<string | null>(null);
  const [result, setResult] = useState<TextResult | null>(null);
  const [askFor, setAskFor] = useState<{ action: string; label: string; needs: string } | null>(null);
  const [askText, setAskText] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [studyTab, setStudyTab] = useState<"quizzes" | "decks" | "steps">("quizzes");
  const [openItem, setOpenItem] = useState<string | null>(null);
  const [dictating, setDictating] = useState(false);
  const [lecture, setLecture] = useState<{ started: number; interim: string } | null>(null);
  const [now, setNow] = useState(Date.now());
  const listener = useRef<Listener | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const saveTimer = useRef<number | undefined>(undefined);
  const toasts = useToasts();
  const canListen = Boolean(speechRecognition());

  const load = useCallback(async () => {
    const result = await api.get<{ notebooks: Notebook[]; notes: NoteSummary[] }>("/api/notes");
    if (result.ok) { setNotebooks(result.data.notebooks); setSummaries(result.data.notes); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const open = useCallback(async (id: string) => {
    const result = await api.get<{ note: Note }>(`/api/notes/${id}`);
    if (result.ok) { setNote(result.data.note); setResult(null); setOpenItem(null); setPane("note"); }
  }, []);

  useEffect(() => {
    if (!note && summaries.length > 0) void open(summaries[0].id);
  }, [summaries, note, open]);

  // Autosave: the body and title are saved a moment after typing stops.
  const save = useCallback((next: Note) => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      await api.patch(`/api/notes/${next.id}`, { title: next.title, body: next.body });
      void load();
    }, 700);
  }, [load]);

  const edit = (changes: Partial<Note>) => {
    setNote((current) => {
      if (!current) return current;
      const next = { ...current, ...changes };
      save(next);
      return next;
    });
  };

  const appendText = useCallback((text: string) => {
    setNote((current) => {
      if (!current) return current;
      const next = { ...current, body: `${current.body.replace(/\s+$/, "")}${current.body.trim() ? "\n\n" : ""}${text}` };
      save(next);
      return next;
    });
  }, [save]);

  async function newNote(kind = "note", title = "") {
    const result = await api.post<{ note: Note }>("/api/notes", { kind, title, notebook_id: book === "all" ? "" : book });
    if (!result.ok) { pushToast(result.error, "warn"); return null; }
    await load();
    setNote(result.data.note);
    setPane("note");
    return result.data.note;
  }

  const [bookDraft, setBookDraft] = useState<string | null>(null);
  async function newNotebook(title: string) {
    setBookDraft(null);
    if (!title.trim()) return;
    const result = await api.post<{ notebook: Notebook }>("/api/notes/notebooks", { title });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    await load();
    setBook(result.data.notebook.id);
  }

  // --- capture: dictation and lecture ------------------------------------------------

  function stopListening() {
    listener.current?.stop();
    listener.current = null;
  }

  function toggleDictation() {
    if (dictating) { stopListening(); setDictating(false); return; }
    if (!note) return;
    const l = listen({
      lang: navigator.language || "en-US",
      keepAlive: false,
      onFinal: (text) => { if (text) appendText(text); },
      onError: (message) => { pushToast(message, "warn"); setDictating(false); },
    });
    if (!l) { pushToast("Dictation needs Chrome or Edge.", "warn"); return; }
    listener.current = l;
    setDictating(true);
  }

  async function startLecture() {
    if (!canListen) { pushToast("Lecture recording needs Chrome or Edge (they turn speech into text).", "warn"); return; }
    const target = note && note.kind === "lecture" && !note.body.trim() ? note : await newNote("lecture");
    if (!target) return;
    const started = Date.now();
    let lastStamp = 0;
    const l = listen({
      lang: navigator.language || "en-US",
      keepAlive: true,
      onFinal: (text) => {
        if (!text) return;
        const minutes = Math.floor((Date.now() - started) / 60000);
        const stamp = minutes >= lastStamp + 5 || lastStamp === 0 ? `**[${minutes} min]** ` : "";
        if (stamp) lastStamp = Math.max(1, minutes);
        appendText(`${stamp}${text}`);
      },
      onInterim: (interim) => setLecture((current) => (current ? { ...current, interim } : current)),
      onError: (message) => pushToast(message, "warn"),
    });
    listener.current = l;
    setLecture({ started, interim: "" });
  }

  function stopLecture() {
    stopListening();
    setLecture(null);
    pushToast("Recording stopped. Only the words were kept — no audio was saved.", "ok", { label: "Organize into Notes", onClick: () => void study("organize") });
  }

  useEffect(() => {
    if (!lecture) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [lecture]);
  useEffect(() => () => stopListening(), []);

  // --- study -------------------------------------------------------------------------

  const selection = () => {
    const el = bodyRef.current;
    if (!el || preview || el.selectionStart === el.selectionEnd) return "";
    return el.value.slice(el.selectionStart, el.selectionEnd);
  };

  async function study(action: string, question = "") {
    if (!note) return;
    const needs = MORE.find((m) => m.action === action)?.needs ?? (action === "steps" ? "The question or problem" : "");
    if (needs && !question) {
      setAskFor({ action, label: [...QUICK, ...MORE].find((a) => a.action === action)?.label ?? action, needs });
      setAskText(action === "steps" ? selection() : "");
      return;
    }
    window.clearTimeout(saveTimer.current);
    await api.patch(`/api/notes/${note.id}`, { title: note.title, body: note.body });
    setWorking(action);
    const response = await api.post<{ kind: string; title?: string; text?: string; model: string; item?: Quiz | Deck | Steps }>(
      `/api/notes/${note.id}/study`, { action, question, selection: selection() }, 120_000);
    setWorking(null);
    if (!response.ok) { pushToast(response.error, "warn"); return; }
    const data = response.data;
    if (data.kind === "text") {
      setResult({ title: data.title ?? action, text: data.text ?? "", model: data.model, action });
      return;
    }
    const fresh = await api.get<{ note: Note }>(`/api/notes/${note.id}`);
    if (fresh.ok) setNote(fresh.data.note);
    const tab = data.kind === "quiz" ? "quizzes" : data.kind === "deck" ? "decks" : "steps";
    setStudyTab(tab);
    setOpenItem(data.item?.id ?? null);
    setPane("study");
    pushToast(`Made with ${data.model}.`, "ok");
  }

  async function readDrawing(png: Blob, hint: string, aiRead: boolean) {
    if (!note) return;
    setWorking("drawing");
    const file = new File([png], `sketch-${Date.now()}.png`, { type: "image/png" });
    const up = await uploadFile(file);
    if (!up.ok) { setWorking(null); pushToast(up.error, "warn"); return; }
    if (!aiRead) {
      appendText(`![Sketch](/api/uploads/${up.data.id})`);
      setWorking(null);
      setDrawing(false);
      return;
    }
    window.clearTimeout(saveTimer.current);
    await api.patch(`/api/notes/${note.id}`, { title: note.title, body: note.body });
    const response = await api.post<{ note: Note; model: string }>(`/api/notes/${note.id}/drawing`, { upload_id: up.data.id, hint }, 120_000);
    setWorking(null);
    if (!response.ok) { pushToast(response.error, "warn"); return; }
    setNote(response.data.note);
    setDrawing(false);
    pushToast(`${response.data.model} read your sketch into the note.`, "ok");
  }

  // --- render ------------------------------------------------------------------------

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return summaries.filter((n) => (book === "all" || n.notebook_id === book) && (!q || `${n.title} ${n.preview}`.toLowerCase().includes(q)));
  }, [summaries, book, query]);

  const items = note ? (studyTab === "quizzes" ? note.quizzes : studyTab === "decks" ? note.decks : note.steps) : [];
  const active = items.find((i) => i.id === openItem) ?? null;
  const elapsed = lecture ? Math.floor((now - lecture.started) / 1000) : 0;

  return (
    <div className={`notes is-pane-${pane}`}>
      <div className="notes__switch segmented" role="tablist" aria-label="Notes view">
        {(["list", "note", "study"] as const).map((p) => (
          <button key={p} role="tab" aria-pressed={pane === p} onClick={() => setPane(p)}>{p === "list" ? "Notes" : p === "note" ? "Note" : "Study"}</button>
        ))}
      </div>

      {/* Notebooks and notes */}
      <aside className="notes__list" aria-label="Notebooks and notes">
        <div className="notes__list-head">
          <h2>Notes</h2>
          <button className="btn btn-primary" onClick={() => void newNote()}>New Note</button>
        </div>
        <input className="notes__search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search" aria-label="Search notes" />
        <div className="notes__books" role="list">
          <button role="listitem" className={`notes__book${book === "all" ? " is-active" : ""}`} onClick={() => setBook("all")}>All Notes <span>{summaries.length}</span></button>
          {notebooks.map((b) => (
            <button role="listitem" key={b.id} className={`notes__book${book === b.id ? " is-active" : ""}`} onClick={() => setBook(b.id)}>
              {b.title} <span>{summaries.filter((n) => n.notebook_id === b.id).length}</span>
            </button>
          ))}
          {bookDraft === null ? (
            <button className="notes__book notes__book--add" onClick={() => setBookDraft("")}>+ Notebook</button>
          ) : (
            <input className="notes__book-input" autoFocus value={bookDraft} placeholder="Notebook name, e.g. Biology 101" aria-label="New notebook name"
              onChange={(e) => setBookDraft(e.target.value)} onBlur={() => void newNotebook(bookDraft)}
              onKeyDown={(e) => { if (e.key === "Enter") void newNotebook(bookDraft); if (e.key === "Escape") setBookDraft(null); }} />
          )}
        </div>
        <div className="notes__items" role="list">
          {visible.length === 0 && <p className="notes__empty">No notes yet. Start one, or record a lecture.</p>}
          {visible.map((n) => (
            <button role="listitem" key={n.id} className={`notes__item${note?.id === n.id ? " is-active" : ""}`} onClick={() => void open(n.id)}>
              <span className="notes__item-title">{n.pinned ? "📌 " : ""}{n.kind === "lecture" ? "🎙 " : n.kind === "drawing" ? "✏️ " : ""}{n.title}</span>
              <span className="notes__item-meta">{when(n.updated_at)} · {n.preview || "Empty"}</span>
            </button>
          ))}
        </div>
      </aside>

      {/* The note */}
      <section className="notes__editor" aria-label="Note">
        {!note ? (
          <div className="notes__blank">
            <h2>Capture a class, then study it.</h2>
            <p>Record a lecture and Nyx writes down what is said. Upload the slides and it reads them, speaker notes and all. Draw a diagram and Nyx reads that too. Then turn any of it into notes, a quiz or flashcards.</p>
            <div className="notes__blank-actions">
              <button className="btn btn-primary" onClick={() => void startLecture()}>Record Lecture</button>
              <button className="btn btn-secondary" onClick={() => void newNote()}>New Note</button>
            </div>
            <SlidesDrop notebookId={book} onAdded={(id) => { void load().then(() => void open(id)); }} />
          </div>
        ) : (
          <>
            <input className="notes__title" value={note.title} onChange={(e) => edit({ title: e.target.value })} aria-label="Title" />
            <div className="notes__toolbar" role="toolbar" aria-label="Capture">
              <button className={`btn btn-secondary${dictating ? " is-live" : ""}`} onClick={toggleDictation} aria-pressed={dictating} disabled={Boolean(lecture)}>
                {dictating ? "Stop Dictating" : "Dictate"}
              </button>
              {lecture ? (
                <button className="btn notes__rec is-live" onClick={stopLecture}>■ Stop Recording</button>
              ) : (
                <button className="btn notes__rec" onClick={() => void startLecture()}>● Record Lecture</button>
              )}
              <button className="btn btn-secondary" onClick={() => setDrawing(true)}>Draw</button>
              <button className="btn btn-secondary" onClick={() => setPreview((v) => !v)} aria-pressed={preview}>{preview ? "Edit" : "Preview"}</button>
              <button className="btn btn-secondary" aria-pressed={note.pinned} onClick={async () => {
                const r = await api.patch<{ note: Note }>(`/api/notes/${note.id}`, { pinned: !note.pinned });
                if (r.ok) { setNote({ ...note, pinned: !note.pinned }); void load(); }
              }}>{note.pinned ? "Unpin" : "Pin"}</button>
            </div>

            {lecture && (
              <div className="notes__live" aria-live="polite">
                <span className="notes__live-dot" aria-hidden="true" />
                <b>Recording · {String(Math.floor(elapsed / 60)).padStart(2, "0")}:{String(elapsed % 60).padStart(2, "0")}</b>
                <span className="notes__live-text">{lecture.interim || "Listening…"}</span>
                <span className="notes__live-note">Audio isn't saved — only the words.</span>
              </div>
            )}

            <div className="notes__study-bar" role="toolbar" aria-label="Study with Nyx">
              {QUICK.map((q) => (
                <button key={q.action} className="btn btn-secondary" disabled={Boolean(working)} onClick={() => void study(q.action)}>
                  {working === q.action ? "Working…" : q.label}
                </button>
              ))}
              <div className="notes__more">
                <button className="btn btn-secondary" aria-haspopup="menu" aria-expanded={moreOpen} onClick={() => setMoreOpen((v) => !v)} disabled={Boolean(working)}>
                  {working && !QUICK.some((q) => q.action === working) ? "Working…" : "More ▾"}
                </button>
                {moreOpen && (
                  <div className="notes__menu" role="menu" onMouseLeave={() => setMoreOpen(false)}>
                    {MORE.map((m) => (
                      <button key={m.action} role="menuitem" onClick={() => { setMoreOpen(false); void study(m.action); }}>{m.label}</button>
                    ))}
                  </div>
                )}
              </div>
              <span className="notes__hint">Select text to use only that part.</span>
            </div>

            {/* A deck read into this note: pick the part, then make what you need (N89). */}
            {note.kind === "slides" && (
              <SlidesStudy
                noteId={note.id}
                onResult={(made) => setResult({ title: made.title ?? "From the slides", text: made.text ?? "", model: made.model, action: "slides" })}
                onMade={(kind, itemId) => {
                  void (async () => {
                    const fresh = await api.get<{ note: Note }>(`/api/notes/${note.id}`);
                    if (fresh.ok) setNote(fresh.data.note);
                    setStudyTab(kind === "quiz" ? "quizzes" : kind === "deck" ? "decks" : "steps");
                    if (itemId) setOpenItem(itemId);
                    setPane("study");
                  })();
                }}
              />
            )}

            {askFor && (
              <form className="notes__ask" onSubmit={(e) => { e.preventDefault(); const q = askText.trim(); if (!q) return; const a = askFor.action; setAskFor(null); void study(a, q); }}>
                <label>
                  <span>{askFor.label}</span>
                  <input autoFocus value={askText} onChange={(e) => setAskText(e.target.value)} placeholder={askFor.needs} />
                </label>
                <button className="btn btn-primary" type="submit" disabled={!askText.trim()}>Go</button>
                <button className="btn btn-secondary" type="button" onClick={() => setAskFor(null)}>Cancel</button>
              </form>
            )}

            {result && (
              <div className="notes__result" role="region" aria-label={result.title}>
                <div className="notes__result-head">
                  <b>{result.title}</b><span className="notes__result-model">{result.model}</span>
                  <button className="btn btn-primary" onClick={() => { appendText(`## ${result.title}\n\n${result.text}`); setResult(null); }}>Add to Note</button>
                  {(result.action === "organize" || result.action === "clean" || result.action === "detail") && (
                    <button className="btn btn-secondary" onClick={() => { edit({ body: result.text }); setResult(null); }}>Replace Note</button>
                  )}
                  <button className="btn btn-secondary" onClick={() => void navigator.clipboard?.writeText(result.text)}>Copy</button>
                  <button className="btn btn-secondary" onClick={() => setResult(null)} aria-label="Dismiss">Dismiss</button>
                </div>
                <div className="notes__result-body"><Markdown text={result.text} /></div>
              </div>
            )}

            {preview ? (
              <div className="notes__preview"><Markdown text={note.body || "_Nothing here yet._"} /></div>
            ) : (
              <textarea ref={bodyRef} className="notes__body" value={note.body} onChange={(e) => edit({ body: e.target.value })}
                placeholder="Type, dictate, or record a lecture. Markdown works: # headings, - bullets, **bold**, $math$." aria-label="Note text" />
            )}
            <div className="notes__foot">
              <span>{note.body.split(/\s+/).filter(Boolean).length} words · saved automatically</span>
              <button className="btn btn-secondary notes__delete" onClick={async () => {
                if (!window.confirm(`Delete “${note.title}”? Its quizzes and flashcards go with it.`)) return;
                await api.del(`/api/notes/${note.id}`);
                setNote(null);
                await load();
              }}>Delete Note</button>
            </div>
          </>
        )}
      </section>

      {/* Study material */}
      <aside className="notes__study" aria-label="Study">
        <FocusTimer />
        {note && (
          <>
            <div className="segmented notes__study-tabs" role="tablist" aria-label="Study material">
              <button aria-pressed={studyTab === "quizzes"} onClick={() => { setStudyTab("quizzes"); setOpenItem(null); }}>Quizzes {note.quizzes.length || ""}</button>
              <button aria-pressed={studyTab === "decks"} onClick={() => { setStudyTab("decks"); setOpenItem(null); }}>Flashcards {note.decks.length || ""}</button>
              <button aria-pressed={studyTab === "steps"} onClick={() => { setStudyTab("steps"); setOpenItem(null); }}>Steps {note.steps.length || ""}</button>
            </div>
            {active ? (
              <>
                <button className="chat-inline notes__back" onClick={() => setOpenItem(null)}>‹ All {studyTab === "decks" ? "flashcards" : studyTab}</button>
                {studyTab === "quizzes" && <QuizView key={active.id} noteId={note.id} quiz={active as Quiz} />}
                {studyTab === "decks" && <DeckView key={active.id} noteId={note.id} deck={active as Deck} />}
                {studyTab === "steps" && <StepsView key={active.id} steps={active as Steps} />}
              </>
            ) : items.length === 0 ? (
              <p className="notes__empty">
                {studyTab === "quizzes" ? "Press Quiz Me to make a practice quiz from this note." : studyTab === "decks" ? "Press Flashcards to make a deck from this note." : "Press Step by Step and type a problem to work through."}
              </p>
            ) : (
              <div className="notes__study-list" role="list">
                {items.map((item) => (
                  <div role="listitem" key={item.id} className="notes__study-item">
                    <button onClick={() => setOpenItem(item.id)}>
                      <b>{"title" in item ? item.title : (item as Steps).question}</b>
                      <span>
                        {studyTab === "quizzes" && `${(item as Quiz).questions.length} questions${(item as Quiz).attempts?.length ? ` · last ${Math.round(((item as Quiz).attempts!.at(-1)!.score / (item as Quiz).attempts!.at(-1)!.total) * 100)}%` : ""}`}
                        {studyTab === "decks" && `${(item as Deck).cards.length} cards · ${(item as Deck).cards.filter((c) => c.box >= 3).length} learned`}
                        {studyTab === "steps" && `${(item as Steps).steps.length} steps`}
                      </span>
                    </button>
                    <button className="notes__study-remove" aria-label="Delete" onClick={async () => {
                      await api.del(`/api/notes/${note.id}/${studyTab}/${item.id}`);
                      const fresh = await api.get<{ note: Note }>(`/api/notes/${note.id}`);
                      if (fresh.ok) setNote(fresh.data.note);
                    }}>✕</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </aside>

      {drawing && note && (
        <DrawingPad busy={working === "drawing"} onClose={() => setDrawing(false)}
          onRead={(png, hint) => void readDrawing(png, hint, true)} onSaveOnly={(png) => void readDrawing(png, "", false)} />
      )}
      <Toasts items={toasts} onDismiss={dismissToast} />
    </div>
  );
}
