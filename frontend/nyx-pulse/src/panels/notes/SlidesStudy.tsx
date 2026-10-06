/** Slides you uploaded, and everything you can make from them (Project Null N89).
 *
 * The owner: "if I upload slides it can make detailed notes, quizzes, Flashcards,
 * questions for specific parts, and has a text box where I can say to generate a
 * specific study tool."
 *
 * So the deck stays visible as a list of numbered slides grouped into its own
 * sections, and every button acts on whatever is selected — nothing selected
 * means the whole deck. Selecting a section selects its slides, because "the part
 * about enzymes" is how people actually think about a lecture.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, uploadFile } from "../../api";
import { pushToast } from "../../state/toastStore";

export interface DeckSummary {
  title: string;
  kind: string;
  name: string;
  slides: number;
  with_notes: number;
  sections: { title: string; from: number; to: number }[];
  titles: { n: number; title: string; chars: number }[];
}

export interface SlidesResult {
  kind: string;
  title?: string;
  text?: string;
  model: string;
  where?: string;
  item?: { id: string };
}

const MAKE: { action: string; label: string; hint: string }[] = [
  { action: "slides_notes", label: "Detailed Notes", hint: "Full notes from the slides and the speaker notes" },
  { action: "slides_questions", label: "Questions on This Part", hint: "Questions with model answers and slide numbers" },
  { action: "quiz", label: "Quiz Me", hint: "A quiz you can take here" },
  { action: "flashcards", label: "Flashcards", hint: "Cards to review" },
  { action: "summarize", label: "Summary", hint: "The short version" },
  { action: "glossary", label: "Key Terms", hint: "Every term, defined" },
];

/** Drop a deck on the Notes tab. Returns the new note's id. */
export function SlidesDrop({ notebookId, onAdded }: { notebookId: string; onAdded: (noteId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);

  const take = useCallback(async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    const up = await uploadFile(file);
    if (!up.ok) { setBusy(false); pushToast(up.error, "warn"); return; }
    const made = await api.post<{ note: { id: string }; deck: DeckSummary }>(
      "/api/notes/slides", { upload_id: up.data.id, notebook_id: notebookId === "all" ? "" : notebookId }, 120_000);
    setBusy(false);
    if (!made.ok) { pushToast(made.error, "warn"); return; }
    pushToast(`Read ${made.data.deck.slides} slides${made.data.deck.with_notes ? `, ${made.data.deck.with_notes} with speaker notes` : ""}.`, "ok");
    onAdded(made.data.note.id);
  }, [notebookId, onAdded]);

  return (
    <label
      className={`slides-drop${over ? " is-over" : ""}`}
      onDragOver={(event) => { event.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => { event.preventDefault(); setOver(false); void take(event.dataTransfer.files[0]); }}
    >
      <input type="file" accept=".pptx,.pdf,.txt,.md,application/pdf" hidden
             onChange={(event) => void take(event.target.files?.[0])} />
      <b>{busy ? "Reading the deck…" : "Upload slides"}</b>
      <span>Drop a .pptx or PDF here, or click to choose. Nyx keeps the slide numbers and the speaker notes.</span>
    </label>
  );
}

export function SlidesStudy({ noteId, onResult, onMade }: {
  noteId: string;
  onResult: (result: SlidesResult) => void;
  /** A quiz, deck or steps was attached to the note. */
  onMade: (kind: string, itemId?: string) => void;
}) {
  const [deck, setDeck] = useState<DeckSummary | null>(null);
  const [chosen, setChosen] = useState<number[]>([]);
  const [instruction, setInstruction] = useState("");
  const [working, setWorking] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const result = await api.get<{ deck: DeckSummary | null }>(`/api/notes/${noteId}/slides`);
      if (alive && result.ok) { setDeck(result.data.deck); setChosen([]); }
    })();
    return () => { alive = false; };
  }, [noteId]);

  const where = useMemo(() => {
    if (!chosen.length) return "the whole deck";
    if (chosen.length === 1) return `slide ${chosen[0]}`;
    return `${chosen.length} slides (${chosen[0]}–${chosen[chosen.length - 1]})`;
  }, [chosen]);

  if (!deck) return null;

  const toggleSlide = (n: number) =>
    setChosen((current) => current.includes(n) ? current.filter((x) => x !== n) : [...current, n].sort((a, b) => a - b));

  const toggleSection = (from: number, to: number) => {
    const range = deck.titles.filter((t) => t.n >= from && t.n <= to).map((t) => t.n);
    const allIn = range.every((n) => chosen.includes(n));
    setChosen((current) => (allIn ? current.filter((n) => !range.includes(n)) : [...new Set([...current, ...range])].sort((a, b) => a - b)));
  };

  async function make(action: string, typed = "") {
    setWorking(action);
    const response = await api.post<SlidesResult>(`/api/notes/${noteId}/slides/study`, {
      action, slides: chosen, instruction: typed, save: action === "slides_notes" ? "append" : "none",
    }, 180_000);
    setWorking(null);
    if (!response.ok) { pushToast(response.error, "warn"); return; }
    const data = response.data;
    if (data.kind === "text") { onResult(data); return; }
    onMade(data.kind, data.item?.id);
    pushToast(`Made from ${data.where ?? "the deck"} with ${data.model}.`, "ok");
  }

  const visibleSlides = showAll ? deck.titles : deck.titles.slice(0, 24);

  return (
    <section className="slides" aria-label="The slides in this note">
      <div className="slides__head">
        <h3>{deck.slides} slides{deck.with_notes > 0 && <span> · {deck.with_notes} with speaker notes</span>}</h3>
        <span className="slides__where">Working on <b>{where}</b>{chosen.length > 0 && (
          <button type="button" className="slides__clear" onClick={() => setChosen([])}>use the whole deck</button>
        )}</span>
      </div>

      {deck.sections.length > 1 && (
        <div className="slides__sections">
          {deck.sections.map((section) => {
            const range = deck.titles.filter((t) => t.n >= section.from && t.n <= section.to).map((t) => t.n);
            const allIn = range.length > 0 && range.every((n) => chosen.includes(n));
            return (
              <button key={`${section.from}-${section.to}`} type="button" className={`slides__section${allIn ? " is-chosen" : ""}`}
                      aria-pressed={allIn} onClick={() => toggleSection(section.from, section.to)}>
                {section.title}
                <span>{section.from === section.to ? `slide ${section.from}` : `slides ${section.from}–${section.to}`}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="slides__list" role="list">
        {visibleSlides.map((slide) => (
          <button key={slide.n} role="listitem" type="button"
                  className={`slides__slide${chosen.includes(slide.n) ? " is-chosen" : ""}${slide.chars < 5 ? " is-thin" : ""}`}
                  aria-pressed={chosen.includes(slide.n)} onClick={() => toggleSlide(slide.n)}>
            <b>{slide.n}</b>
            <span>{slide.title || "(no title)"}</span>
          </button>
        ))}
        {deck.titles.length > 24 && (
          <button type="button" className="slides__more" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${deck.titles.length}`}
          </button>
        )}
      </div>

      <div className="slides__make" role="group" aria-label="Make study material">
        {MAKE.map((item) => (
          <button key={item.action} type="button" className="btn btn-secondary" title={item.hint}
                  disabled={working !== null} onClick={() => void make(item.action)}>
            {working === item.action ? "Working…" : item.label}
          </button>
        ))}
      </div>

      <form className="slides__ask" onSubmit={(event) => { event.preventDefault(); if (instruction.trim()) void make("custom", instruction.trim()); }}>
        <input value={instruction} onChange={(event) => setInstruction(event.target.value)}
               placeholder="Or ask for anything: “a one-page cheat sheet of the formulas”, “10 hard questions on slides 12–18”"
               aria-label="Ask for a specific study tool" />
        <button className="btn btn-primary" disabled={!instruction.trim() || working !== null}>
          {working === "custom" ? "Making…" : "Make It"}
        </button>
      </form>
    </section>
  );
}
