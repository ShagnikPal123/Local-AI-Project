/** One research job: watch it work, then read the cited report, its sources, the evidence, and Paper mode.
 *
 * While it runs the page shows the pipeline the engine really follows (plan → search → read → weigh → write), the
 * step it is on and its log, and the sources fill in as they are found. When it is done the report reads like a
 * document: a summary, the findings with clickable `[n]` citations, and a reference list in the style chosen in the
 * header — switching style re-formats it from the sources at once, no model involved. Every source shows what Nyx
 * actually read, and its citation is one press from the clipboard.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../components/chat/Icon";
import { Markdown } from "../../components/chat/Markdown";
import { ConfirmButton, CiteText, CopyButton } from "./bits";
import { saveFrom } from "./save";
import {
  RUNNING,
  STATUS_LABEL,
  STYLE_LABEL,
  type CitationList,
  type Job,
  type Paper,
  type Source,
  authorLine,
  citedNumbers,
  linkCitations,
  reportBody,
  tookLabel,
  whenLabel,
} from "./types";

type Pane = "report" | "sources" | "evidence" | "paper";

const STAGES: { key: string; label: string; deepOnly?: boolean }[] = [
  { key: "planning", label: "Plan", deepOnly: true },
  { key: "searching", label: "Search" },
  { key: "reading", label: "Read" },
  { key: "analyzing", label: "Weigh evidence", deepOnly: true },
  { key: "writing", label: "Write" },
];

/** Where in the pipeline a status sits; queued counts as before the first stage. */
const ORDER: Record<string, number> = { queued: -1, planning: 0, searching: 1, reading: 2, analyzing: 3, writing: 4, done: 9 };

export function JobView({ job, style, sections, onChanged, onDelete, onError, onOpen }: {
  job: Job;
  /** The citation style chosen in the header. */
  style: string;
  /** Section names Paper mode can use. */
  sections: string[];
  onChanged: (job: Job) => void;
  onDelete: () => void;
  onError: (message: string) => void;
  /** A new job started from this one (Go deeper). */
  onOpen: (job: Job) => void;
}) {
  const running = RUNNING.has(job.status);
  const deep = job.mode === "deep";
  const [pane, setPane] = useState<Pane>("report");
  const [citations, setCitations] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<"" | "stop" | "teach" | "deeper">("");
  const [exportOpen, setExportOpen] = useState(false);

  // A different job opens on its report.
  useEffect(() => setPane("report"), [job.job_id]);

  // The sources in the chosen style. Asked again when the style changes or new sources arrive — never a model call.
  const sourceCount = job.sources.length;
  useEffect(() => {
    if (!sourceCount) {
      setCitations({});
      return;
    }
    let alive = true;
    void api.get<CitationList>(`/api/research/${job.job_id}/citations?style=${encodeURIComponent(style)}`).then((result) => {
      if (alive && result.ok) setCitations(Object.fromEntries(result.data.citations.map((c) => [c.n, c.text])));
    });
    return () => {
      alive = false;
    };
  }, [job.job_id, style, sourceCount]);

  const act = async (kind: "stop" | "teach" | "deeper") => {
    setBusy(kind);
    if (kind === "stop") {
      const result = await api.post<{ job: Job }>(`/api/research/${job.job_id}/stop`);
      if (result.ok) onChanged(result.data.job);
      else onError(result.error);
    } else if (kind === "teach") {
      const result = await api.post<{ taught: Job["taught"] }>(`/api/research/${job.job_id}/teach`);
      if (result.ok) onChanged({ ...job, taught: result.data.taught });
      else onError(result.error);
    } else {
      const result = await api.post<{ job: Job }>("/api/research", {
        question: job.question,
        mode: "deep",
        web: job.include_web,
        papers: job.include_papers,
      });
      if (result.ok) onOpen(result.data.job);
      else onError(result.error);
    }
    setBusy("");
  };

  const exportAs = async (format: string, what: "report" | "paper" = "report") => {
    setExportOpen(false);
    const failed = await saveFrom(
      `/api/research/${job.job_id}/export?format=${format}&style=${encodeURIComponent(style)}&what=${what}`,
      `research.${format === "citations" ? "txt" : format}`,
    );
    if (failed) onError(failed);
  };

  const evidenceCount = job.notes.length;
  const panes: { key: Pane; label: string; hidden?: boolean }[] = [
    { key: "report", label: "Report" },
    { key: "sources", label: `Sources${sourceCount ? ` · ${sourceCount}` : ""}` },
    { key: "evidence", label: `Evidence · ${evidenceCount}`, hidden: !deep || evidenceCount === 0 },
    { key: "paper", label: "Paper", hidden: job.status !== "done" },
  ];

  return (
    <section className="rs-job" aria-busy={running || undefined}>
      <header className="rs-job__head">
        <div className="rs-job__eyebrow">
          <span className={`rs-pill rs-pill--${job.status}`}>
            <span className={`rs-dot rs-dot--${job.status}`} aria-hidden="true" />
            {STATUS_LABEL[job.status] ?? job.status}
          </span>
          <span>{deep ? "Deep" : "Standard"}</span>
          <span>{whenLabel(job.created_at)}</span>
          {job.elapsed_seconds > 0 && <span>{running ? "running " : "took "}{tookLabel(job.elapsed_seconds)}</span>}
          {sourceCount > 0 && <span>{sourceCount} sources</span>}
          {job.models.length > 0 && <span title="The model that wrote it">{job.models.join(", ")}</span>}
        </div>
        <h2 className="rs-job__q">{job.question}</h2>
        <div className="rs-job__actions">
          {running ? (
            <button className="rs-btn" onClick={() => void act("stop")} disabled={busy === "stop"}>
              <Icon name="stop" /> {busy === "stop" ? "Stopping…" : "Stop"}
            </button>
          ) : (
            <>
              <div className="rs-menu">
                <button
                  className="rs-btn"
                  aria-haspopup="menu"
                  aria-expanded={exportOpen}
                  disabled={!job.report}
                  onClick={() => setExportOpen((open) => !open)}
                >
                  <Icon name="download" /> Export <Icon name="chevronDown" />
                </button>
                {exportOpen && (
                  <ExportMenu style={style} onPick={(format) => void exportAs(format)} onClose={() => setExportOpen(false)} />
                )}
              </div>
              {job.report && <CopyButton text={job.report} label="Copy report" className="rs-btn" />}
              {job.status === "done" && (
                <button
                  className="rs-btn"
                  onClick={() => void act("teach")}
                  disabled={busy === "teach"}
                  title="Put what this found into Nyx's memory and its learning set"
                >
                  <Icon name={job.taught?.at ? "check" : "brain"} />{" "}
                  {busy === "teach" ? "Teaching…" : job.taught?.at ? "Taught Nyx" : "Teach Nyx"}
                </button>
              )}
              {!deep && job.status === "done" && (
                <button className="rs-btn" onClick={() => void act("deeper")} disabled={busy === "deeper"}
                  title="Research the same question in deep mode: sub-questions, more sources, claims first">
                  <Icon name="search" /> {busy === "deeper" ? "Starting…" : "Go deeper"}
                </button>
              )}
            </>
          )}
          <ConfirmButton onConfirm={onDelete} className="rs-btn rs-btn--quiet rs-btn--danger" title="Delete this research">
            <Icon name="trash" /> Delete
          </ConfirmButton>
        </div>
        {job.taught?.at && (
          <p className="rs-note">
            <Icon name="brain" /> Nyx learned from this {whenLabel(job.taught.at)}: {job.taught.facts ?? 0} facts in its memory
            {job.taught.examples ? `, ${job.taught.examples} worked example for its own model` : ""}.
          </p>
        )}
      </header>

      {(running || job.status === "stopped" || job.status === "error") && <LiveCard job={job} />}

      {(sourceCount > 0 || job.report) && (
        <>
          <div className="rs-panes segmented" role="tablist" aria-label="What to show">
            {panes.filter((p) => !p.hidden).map((p) => (
              <button key={p.key} role="tab" aria-selected={pane === p.key} aria-pressed={pane === p.key} onClick={() => setPane(p.key)}>
                {p.label}
              </button>
            ))}
          </div>

          {pane === "report" && <ReportPane job={job} style={style} citations={citations} onSources={() => setPane("sources")} />}
          {pane === "sources" && <SourcesPane sources={job.sources} style={style} citations={citations} />}
          {pane === "evidence" && <EvidencePane job={job} />}
          {pane === "paper" && (
            <PaperPane job={job} style={style} sections={sections} onChanged={onChanged} onError={onError}
              onExport={(format) => void exportAs(format, "paper")} />
          )}
        </>
      )}
    </section>
  );
}

function ExportMenu({ style, onPick, onClose }: { style: string; onPick: (format: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (ref.current && !ref.current.parentElement?.contains(event.target as Node)) onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [onClose]);
  const items: [string, string, string][] = [
    ["md", "Markdown", ".md — the report as written"],
    ["html", "Web page", ".html — opens in any browser"],
    ["tex", "LaTeX", ".tex — with \\cite keys"],
    ["bib", "BibTeX", ".bib — every source"],
    ["citations", `Reference list · ${STYLE_LABEL[style] ?? style}`, ".txt — every source in this style"],
  ];
  return (
    <div className="rs-menu__list" role="menu" ref={ref}>
      {items.map(([format, label, hint]) => (
        <button key={format} role="menuitem" onClick={() => onPick(format)}>
          <b>{label}</b>
          <span>{hint}</span>
        </button>
      ))}
    </div>
  );
}

/** The pipeline, the step it is on, and its own log — the part you watch. */
function LiveCard({ job }: { job: Job }) {
  const stages = STAGES.filter((stage) => !stage.deepOnly || job.mode === "deep");
  const at = ORDER[job.status] ?? -1;
  const failed = job.status === "error" || job.status === "stopped";
  // Where a failed or stopped job got to: the last stage it logged.
  const reached = failed
    ? Math.max(-1, ...job.log.map((entry) => {
        const text = entry.text.toLowerCase();
        if (text.startsWith("writing")) return 4;
        if (text.startsWith("extracting")) return 3;
        if (text.startsWith("read") || text.startsWith("found")) return 2;
        if (text.startsWith("searching")) return 1;
        if (text.startsWith("planning")) return 0;
        return -1;
      }))
    : at;
  const log = job.log.slice(-7).reverse();
  return (
    <div className={`rs-live${failed ? " is-ended" : ""}`}>
      <ol className="rs-stages" aria-label="Research steps">
        {stages.map((stage) => {
          const n = ORDER[stage.key];
          const state = n < reached ? "done" : n === reached ? (failed ? "ended" : "current") : "todo";
          return (
            <li key={stage.key} className={`rs-stage is-${state}`} aria-current={state === "current" ? "step" : undefined}>
              <span className="rs-stage__mark" aria-hidden="true">{state === "done" ? <Icon name="check" /> : null}</span>
              {stage.label}
            </li>
          );
        })}
      </ol>
      <div className="rs-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)}
        aria-label="Progress">
        <span style={{ width: `${Math.max(2, Math.round(job.progress * 100))}%` }} />
      </div>
      <p className="rs-live__step">
        {job.status === "error" ? <Icon name="alert" /> : null}
        {job.status === "error" ? job.error || job.step : job.step}
        {!failed && <span className="rs-live__pct">{Math.round(job.progress * 100)}%</span>}
      </p>
      {job.plan.length > 0 && (
        <div className="rs-plan">
          <span className="rs-label">Sub-questions</span>
          <ol>
            {job.plan.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        </div>
      )}
      {log.length > 0 && (
        <ul className="rs-log" aria-label="What it has done">
          {log.map((entry, i) => (
            <li key={`${entry.ts}-${i}`}>
              <time>{clock(entry.ts)}</time>
              <span>{entry.text}</span>
            </li>
          ))}
        </ul>
      )}
      {!failed && <p className="rs-hint">It keeps going if you leave this tab. The sources appear below as they are found.</p>}
    </div>
  );
}

function clock(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function ReportPane({ job, style, citations, onSources }: {
  job: Job;
  style: string;
  citations: Record<number, string>;
  onSources: () => void;
}) {
  const body = useMemo(() => reportBody(job.report), [job.report]);
  const linked = useMemo(() => linkCitations(body, job.sources), [body, job.sources]);
  const cited = useMemo(() => citedNumbers(body), [body]);
  const byNumber = useMemo(() => new Map(job.sources.map((s) => [s.n, s])), [job.sources]);

  if (!job.report) {
    return (
      <div className="rs-empty-pane">
        {RUNNING.has(job.status) ? (
          <>
            <span className="rs-spinner" aria-hidden="true" />
            <p>The report is written after the sources are read. {job.sources.length ? "You can look through the sources now." : ""}</p>
            {job.sources.length > 0 && (
              <button className="rs-btn" onClick={onSources}>
                See the sources
              </button>
            )}
          </>
        ) : (
          <p>No report was written{job.error ? ` — ${job.error}` : "."}</p>
        )}
      </div>
    );
  }

  return (
    <article className="rs-report">
      {/* The engine's summary is the report's own Summary section; shown apart only when the report has none. */}
      {job.summary && !/^##\s*Summary\b/im.test(body) && (
        <aside className="rs-summary">
          <span className="rs-label">In short</span>
          <p>{job.summary}</p>
        </aside>
      )}
      {job.removed_citations.length > 0 && (
        <p className="rs-note rs-note--warn">
          <Icon name="info" /> Nyx removed {job.removed_citations.length} citation{job.removed_citations.length > 1 ? "s" : ""} the model
          wrote that pointed at no source it had read ({job.removed_citations.slice(0, 5).join(" ")}).
        </p>
      )}
      <div className="rs-report__body">
        <Markdown text={linked} />
      </div>
      {cited.length > 0 && (
        <section className="rs-refs" aria-label="References">
          <h3>
            References <span>{STYLE_LABEL[style] ?? style}</span>
          </h3>
          {style === "bibtex" ? (
            <pre className="rs-bibtex">{cited.map((n) => citations[n]).filter(Boolean).join("\n\n")}</pre>
          ) : (
            <ol>
              {cited.map((n) => {
                const source = byNumber.get(n);
                const text = citations[n];
                return (
                  <li key={n}>
                    <span className="rs-refs__n">[{n}]</span>
                    <span className="rs-refs__text">
                      {text ? <CiteText text={style === "ieee" ? text.replace(/^\[\d+\]\s*/, "") : text} /> : source?.title}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          {cited.length > 0 && (
            <div className="rs-refs__tools">
              <CopyButton
                text={cited.map((n) => citations[n]).filter(Boolean).join(style === "bibtex" ? "\n\n" : "\n")}
                label="Copy references"
              />
            </div>
          )}
        </section>
      )}
    </article>
  );
}

function SourcesPane({ sources, style, citations }: { sources: Source[]; style: string; citations: Record<number, string> }) {
  const read = sources.filter((s) => s.read).length;
  return (
    <div className="rs-sources">
      <p className="rs-hint">
        {sources.length} found · {read} read in full or by abstract · citations in {STYLE_LABEL[style] ?? style}
      </p>
      <ol className="rs-cards">
        {sources.map((source) => (
          <SourceCard key={source.n} source={source} citation={citations[source.n] ?? ""} bibtex={style === "bibtex"} />
        ))}
      </ol>
    </div>
  );
}

function SourceCard({ source, citation, bibtex }: { source: Source; citation: string; bibtex: boolean }) {
  const [open, setOpen] = useState(false);
  const text = source.excerpt || source.abstract || source.snippet;
  const meta = [authorLine(source.authors), source.year ? String(source.year) : "", source.venue,
    typeof source.citations === "number" ? `cited ${source.citations.toLocaleString()}×` : ""].filter(Boolean);
  return (
    <li className="rs-card" id={`rs-source-${source.n}`}>
      <span className="rs-card__n">{source.n}</span>
      <div className="rs-card__body">
        <div className="rs-card__tags">
          <span className={`rs-tag rs-tag--${source.kind}`}>
            <Icon name={source.kind === "paper" ? "file" : "globe"} /> {source.kind === "paper" ? "Paper" : "Web"}
          </span>
          {source.kind === "paper" && source.found_by && <span className="rs-tag">{source.found_by}</span>}
          <span className={`rs-tag ${source.read ? "rs-tag--ok" : "rs-tag--muted"}`} title={source.error || undefined}>
            {source.read ? (source.kind === "paper" ? "Abstract read" : "Page read") : source.error ? "Not read" : "Not read yet"}
          </span>
        </div>
        {source.url ? (
          <a className="rs-card__title" href={source.url} target="_blank" rel="noopener noreferrer">
            {source.title || source.url} <Icon name="external" />
          </a>
        ) : (
          <span className="rs-card__title">{source.title || "Untitled"}</span>
        )}
        {meta.length > 0 && <p className="rs-card__meta">{meta.join(" · ")}</p>}
        {text && (
          <>
            <p className={`rs-card__text${open ? " is-open" : ""}`}>{text}</p>
            {text.length > 260 && (
              <button className="rs-link" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
                {open ? "Show less" : source.excerpt ? "Show what Nyx read" : "Show more"}
              </button>
            )}
          </>
        )}
        {citation && (
          <div className="rs-cite">
            {bibtex ? <pre>{citation}</pre> : <p><CiteText text={citation} /></p>}
            <CopyButton text={citation} label="Copy citation" />
          </div>
        )}
        {source.pdf_url && (
          <a className="rs-link" href={source.pdf_url} target="_blank" rel="noopener noreferrer">
            <Icon name="file" /> PDF
          </a>
        )}
      </div>
    </li>
  );
}

function EvidencePane({ job }: { job: Job }) {
  const byNumber = new Map(job.sources.map((s) => [s.n, s]));
  return (
    <div className="rs-evidence">
      <p className="rs-hint">
        Deep mode pulls each claim out of the sources before writing, and keeps only claims tied to a source it read.
      </p>
      <ul>
        {job.notes.map((note, i) => (
          <li key={i} className="rs-claim">
            <span className={`rs-conf rs-conf--${note.confidence}`}>{note.confidence}</span>
            <p>{note.claim}</p>
            <span className="rs-claim__src">
              {note.sources.map((n) => {
                const source = byNumber.get(n);
                return source?.url ? (
                  <a key={n} href={source.url} target="_blank" rel="noopener noreferrer" title={source.title}>
                    [{n}]
                  </a>
                ) : (
                  <span key={n} title={source?.title}>[{n}]</span>
                );
              })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Paper mode: draft an academic paper from the finished research, in the chosen style, then export it. */
function PaperPane({ job, style, sections, onChanged, onError, onExport }: {
  job: Job;
  style: string;
  sections: string[];
  onChanged: (job: Job) => void;
  onError: (message: string) => void;
  onExport: (format: string) => void;
}) {
  const paper: Paper = job.paper ?? {};
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [length, setLength] = useState<"short" | "medium" | "long">("medium");
  const [chosen, setChosen] = useState<string[]>(sections);
  const [drafting, setDrafting] = useState(false);
  const [redo, setRedo] = useState(false);
  const paperStyle = style === "bibtex" ? "apa" : style;

  const draft = async () => {
    setDrafting(true);
    // A long paper takes the model a few minutes; the request waits for it rather than the usual 30 seconds.
    const result = await api.post<{ paper: Paper }>(
      `/api/research/${job.job_id}/paper`,
      { title: title.trim(), author: author.trim(), length, style: paperStyle, sections: chosen },
      6 * 60_000,
    );
    setDrafting(false);
    if (result.ok) {
      onChanged({ ...job, paper: result.data.paper });
      setRedo(false);
    } else onError(result.error);
  };

  if (paper.markdown && !redo && !drafting) {
    return (
      <article className="rs-report rs-paper">
        <div className="rs-paper__bar">
          <span className="rs-hint">
            {paper.words?.toLocaleString()} words · {STYLE_LABEL[paper.style ?? ""] ?? paper.style} · {paper.references?.length ?? 0} references
            {paper.created_at ? ` · drafted ${whenLabel(paper.created_at)}` : ""}
          </span>
          <div className="rs-row">
            <button className="rs-btn" onClick={() => onExport("md")}><Icon name="download" /> Markdown</button>
            <button className="rs-btn" onClick={() => onExport("tex")}><Icon name="download" /> LaTeX</button>
            <button className="rs-btn" onClick={() => onExport("html")}><Icon name="download" /> Web page</button>
            <CopyButton text={paper.markdown} label="Copy" className="rs-btn" />
            <button className="rs-btn rs-btn--quiet" onClick={() => setRedo(true)}><Icon name="refresh" /> Draft again</button>
          </div>
        </div>
        <div className="rs-report__body">
          <Markdown text={paper.markdown} />
        </div>
      </article>
    );
  }

  return (
    <form
      className="rs-paperform"
      onSubmit={(event) => {
        event.preventDefault();
        if (!drafting && chosen.length) void draft();
      }}
    >
      <div>
        <h3>Draft a paper from this research</h3>
        <p className="rs-hint">
          Nyx writes an academic paper using only what these sources say, cites them in {STYLE_LABEL[paperStyle] ?? paperStyle}, and adds
          the reference list. If the sources are a literature review, the Methods and Results say so — nothing is invented.
          {style === "bibtex" ? " BibTeX is a file format, not an in-text style, so the paper uses APA; export BibTeX alongside it." : ""}
        </p>
      </div>
      <div className="rs-fields">
        <label className="rs-input">
          <span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Let Nyx choose a precise title" maxLength={200} />
        </label>
        <label className="rs-input">
          <span>Author</span>
          <input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Optional" maxLength={120} />
        </label>
      </div>
      <div className="rs-field">
        <span className="rs-label">Length</span>
        <div className="segmented">
          {(["short", "medium", "long"] as const).map((option) => (
            <button key={option} type="button" aria-pressed={length === option} onClick={() => setLength(option)}>
              {option === "short" ? "Short · ~1,200 words" : option === "medium" ? "Medium · ~2,500" : "Long · ~5,000"}
            </button>
          ))}
        </div>
      </div>
      <div className="rs-field">
        <span className="rs-label">Sections</span>
        <div className="rs-chips">
          {sections.map((section) => {
            const on = chosen.includes(section);
            return (
              <button
                key={section}
                type="button"
                className="rs-chip"
                aria-pressed={on}
                onClick={() => setChosen((list) => (on ? list.filter((s) => s !== section) : sections.filter((s) => list.includes(s) || s === section)))}
              >
                {on && <Icon name="check" />} {section}
              </button>
            );
          })}
        </div>
      </div>
      <div className="rs-row">
        <button className="rs-btn rs-btn--primary" type="submit" disabled={drafting || chosen.length === 0}>
          <Icon name="pencil" /> {drafting ? "Drafting…" : "Draft paper"}
        </button>
        {redo && !drafting && (
          <button className="rs-btn rs-btn--quiet" type="button" onClick={() => setRedo(false)}>
            Back to the draft
          </button>
        )}
        {drafting && (
          <span className="rs-hint">
            <span className="rs-spinner rs-spinner--inline" aria-hidden="true" /> Writing {length === "long" ? "a long paper takes a few minutes" : "takes a minute or two"}.
          </span>
        )}
      </div>
    </form>
  );
}

