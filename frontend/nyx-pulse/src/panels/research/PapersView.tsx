/** Papers: search scholarly papers, read their abstracts, cite them, or research one further.
 *
 * Searches OpenAlex and arXiv through `GET /api/research/papers` (free, no key). Each result arrives with its
 * citation already formatted in every style, so the header's style switch and Copy are instant. A DOI can be
 * looked up on Crossref and cited the same way. "Research this" hands a question about the paper to the start box.
 */

import { useState } from "react";
import { api } from "../../api";
import { Icon } from "../../components/chat/Icon";
import { CiteText, CopyButton } from "./bits";
import { STYLE_LABEL, type FoundPaper, authorLine } from "./types";

const STARTERS = ["retrieval augmented generation evaluation", "spaced repetition memory", "speculative decoding"];

interface Cited {
  source: FoundPaper;
  citation: string;
  all: Record<string, string>;
}

export function PapersView({ style, onResearch }: {
  /** The citation style chosen in the header. */
  style: string;
  /** Ask Nyx to research this question (the panel opens the start box with it). */
  onResearch: (question: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  /** What the indexes were really asked: a question is searched by its topic words. */
  const [used, setUsed] = useState("");
  const [papers, setPapers] = useState<FoundPaper[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [doi, setDoi] = useState("");
  const [cited, setCited] = useState<Cited | null>(null);
  const [citing, setCiting] = useState(false);
  const [citeError, setCiteError] = useState("");

  const search = async (text: string) => {
    const clean = text.trim();
    if (clean.length < 2 || loading) return;
    setQuery(clean);
    setLoading(true);
    setError("");
    // Two public indexes answer in turn; give them longer than the usual 30 seconds before calling it a failure.
    const result = await api.get<{ papers: FoundPaper[]; query?: string }>(
      `/api/research/papers?q=${encodeURIComponent(clean)}&limit=12`,
      60_000,
    );
    setLoading(false);
    setSearched(clean);
    if (result.ok) {
      setPapers(result.data.papers);
      setUsed(result.data.query && result.data.query !== clean ? result.data.query : "");
    } else {
      setPapers(null);
      setError(result.error);
    }
  };

  const cite = async () => {
    const clean = doi.trim();
    if (!clean || citing) return;
    setCiting(true);
    setCiteError("");
    const result = await api.get<Cited>(`/api/research/cite?doi=${encodeURIComponent(clean)}&style=${encodeURIComponent(style)}`, 40_000);
    setCiting(false);
    if (result.ok) setCited(result.data);
    else {
      setCited(null);
      setCiteError(result.error);
    }
  };

  return (
    <div className="rs-papers">
      <section className="rs-papers__intro">
        <h2>Find papers</h2>
        <p>
          Searches OpenAlex and arXiv — free, no key. Every result comes with its citation in{" "}
          {STYLE_LABEL[style] ?? style} (change it at the top right).
        </p>
        <form
          className="rs-searchbar"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            void search(query);
          }}
        >
          <Icon name="search" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title words, a topic, or an author"
            aria-label="Search scholarly papers"
            maxLength={300}
          />
          <button className="rs-btn rs-btn--primary" type="submit" disabled={loading || query.trim().length < 2}>
            {loading ? "Searching…" : "Search"}
          </button>
        </form>
        {!papers && !loading && !error && (
          <div className="rs-chips">
            {STARTERS.map((starter) => (
              <button key={starter} type="button" className="rs-chip" onClick={() => void search(starter)}>
                {starter}
              </button>
            ))}
          </div>
        )}
      </section>

      {error && (
        <p className="rs-error" role="alert">
          <Icon name="alert" /> {error}
        </p>
      )}

      {loading && (
        <ul className="rs-results" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <li key={i} className="rs-paper is-loading">
              <span className="rs-skeleton" style={{ width: "70%" }} />
              <span className="rs-skeleton" style={{ width: "40%" }} />
              <span className="rs-skeleton" style={{ width: "95%" }} />
            </li>
          ))}
        </ul>
      )}

      {papers && !loading && (
        <>
          <p className="rs-hint rs-results__count" aria-live="polite">
            {papers.length === 0
              ? `No papers matched “${searched}”. Try fewer or broader words.`
              : `${papers.length} paper${papers.length > 1 ? "s" : ""} for “${used || searched}”`}
            {used && papers.length > 0 ? " — the topic words of your question, since the indexes match every word." : ""}
          </p>
          <ul className="rs-results">
            {papers.map((paper, i) => (
              <PaperCard key={`${paper.doi || paper.url || paper.title}-${i}`} paper={paper} style={style} onResearch={onResearch} />
            ))}
          </ul>
        </>
      )}

      <section className="rs-doi" aria-label="Cite a DOI">
        <div>
          <h3>Cite a DOI</h3>
          <p className="rs-hint">Paste a DOI and Nyx looks it up on Crossref and formats it.</p>
        </div>
        <form
          className="rs-row"
          onSubmit={(event) => {
            event.preventDefault();
            void cite();
          }}
        >
          <input
            className="rs-textfield"
            value={doi}
            onChange={(event) => setDoi(event.target.value)}
            placeholder="10.48550/arXiv.2205.14135"
            aria-label="DOI"
            maxLength={200}
          />
          <button className="rs-btn" type="submit" disabled={citing || !doi.trim()}>
            {citing ? "Looking up…" : "Cite"}
          </button>
        </form>
        {citeError && <p className="rs-error">{citeError}</p>}
        {cited && (
          <div className="rs-cite">
            <b className="rs-cite__title">{cited.source.title}</b>
            {style === "bibtex" ? <pre>{cited.all[style] ?? cited.citation}</pre> : <p><CiteText text={cited.all[style] ?? cited.citation} /></p>}
            <CopyButton text={cited.all[style] ?? cited.citation} label="Copy citation" />
          </div>
        )}
      </section>
    </div>
  );
}

function PaperCard({ paper, style, onResearch }: { paper: FoundPaper; style: string; onResearch: (question: string) => void }) {
  const [open, setOpen] = useState(false);
  const citation = paper.cite?.[style] ?? "";
  const meta = [paper.year ? String(paper.year) : "", paper.venue,
    typeof paper.citations === "number" ? `cited ${paper.citations.toLocaleString()}×` : ""].filter(Boolean);
  return (
    <li className="rs-paper">
      <div className="rs-card__tags">
        <span className="rs-tag rs-tag--paper"><Icon name="file" /> {paper.found_by || "Paper"}</span>
        {paper.pdf_url && <span className="rs-tag rs-tag--ok">Free PDF</span>}
      </div>
      {paper.url ? (
        <a className="rs-card__title" href={paper.url} target="_blank" rel="noopener noreferrer">
          {paper.title} <Icon name="external" />
        </a>
      ) : (
        <span className="rs-card__title">{paper.title}</span>
      )}
      <p className="rs-card__meta">
        {authorLine(paper.authors)}
        {meta.length ? ` · ${meta.join(" · ")}` : ""}
      </p>
      {paper.abstract ? (
        <>
          <p className={`rs-card__text${open ? " is-open" : ""}`}>{paper.abstract}</p>
          {paper.abstract.length > 260 && (
            <button className="rs-link" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              {open ? "Show less" : "Read the abstract"}
            </button>
          )}
        </>
      ) : (
        <p className="rs-card__text is-missing">No abstract in the index.</p>
      )}
      {citation && (
        <div className="rs-cite">
          {style === "bibtex" ? <pre>{citation}</pre> : <p><CiteText text={citation} /></p>}
        </div>
      )}
      <div className="rs-row">
        {citation && <CopyButton text={citation} label={`Copy ${STYLE_LABEL[style] ?? style}`} className="rs-btn" />}
        {paper.pdf_url && (
          <a className="rs-btn rs-btn--quiet" href={paper.pdf_url} target="_blank" rel="noopener noreferrer">
            <Icon name="file" /> PDF
          </a>
        )}
        <button
          className="rs-btn rs-btn--quiet"
          onClick={() => onResearch(`What does "${paper.title}"${paper.year ? ` (${paper.year})` : ""} find, and how does later work build on or challenge it?`)}
        >
          <Icon name="search" /> Research this
        </button>
      </div>
    </li>
  );
}
