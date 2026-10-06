/** Research (Request L) — standard and deep research with real, checked citations.
 *
 * The owner: "Create a research (deep and standard) tab for research and add lots of stuff as well as citations,
 * paper publishing mode, and it can search and research papers. It can also help train the model so it can upgrade."
 *
 * The page is the job: ask on the right, past research on the left, and an open job shows Nyx plan, search, read and
 * write, then the cited report. Every `[n]` in a report is a real source it collected — numbers the model invents are
 * stripped by the engine and said so here. A finished job can be drafted into a paper, exported, or taught to Nyx
 * (`research_engine.teach`). The Papers view searches scholarly indexes directly.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../components/chat/Icon";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { ConfirmButton } from "./bits";
import { JobView } from "./JobView";
import { PapersView } from "./PapersView";
import { RUNNING, STATUS_LABEL, STYLE_LABEL, type Job, type Overview, tookLabel, whenLabel } from "./types";
import "./research.css";

type View = "research" | "papers";

const EXAMPLES = [
  "How well does layer-by-layer offloading let a 70B model run on a 16 GB GPU?",
  "What does the evidence say about spaced repetition for long-term retention?",
  "Compare current open-weight speech recognition models for local use",
];

const VIEW_KEY = "nyx.research.view";

export function ResearchPanel() {
  const [view, setView] = useState<View>(() => {
    try {
      return localStorage.getItem(VIEW_KEY) === "papers" ? "papers" : "research";
    } catch {
      return "research";
    }
  });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // The start box
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"standard" | "deep">("standard");
  const [web, setWeb] = useState(true);
  const [papers, setPapers] = useState(true);
  const askRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_KEY, view);
    } catch {
      /* private window */
    }
  }, [view]);

  const loadOverview = useCallback(async () => {
    const result = await api.get<Overview>("/api/research");
    if (result.ok) setOverview(result.data);
    else setError(result.error);
  }, []);

  const openJob = useCallback(async (id: string) => {
    const result = await api.get<{ job: Job }>(`/api/research/${id}`);
    if (result.ok) {
      setJob(result.data.job);
      setView("research");
      setError("");
    } else setError(result.error);
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  // The engine publishes `research.job` on every step, so the list follows a job started anywhere (chat included).
  useEffect(
    () =>
      onWorkspaceEvent((event) => {
        if (event.type === "research.job") void loadOverview();
      }),
    [loadOverview],
  );

  // While a job works, ask for it about once a second: this is the part you watch.
  const openId = job?.job_id ?? "";
  const working = !!job && RUNNING.has(job.status);
  useEffect(() => {
    if (!openId || !working) return;
    let alive = true;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void (async () => {
        const result = await api.get<{ job: Job }>(`/api/research/${openId}`);
        if (alive && result.ok) setJob(result.data.job);
      })();
    }, 1100);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [openId, working]);

  // When the open job finishes, the list beside it should say so too.
  const openStatus = job?.status ?? "";
  useEffect(() => {
    if (openStatus && !RUNNING.has(openStatus)) void loadOverview();
  }, [openStatus, loadOverview]);

  const start = useCallback(async () => {
    const asked = question.trim();
    if (asked.length < 8 || busy) return;
    setBusy(true);
    setError("");
    const result = await api.post<{ job: Job }>("/api/research", { question: asked, mode, web, papers });
    setBusy(false);
    if (result.ok) {
      setJob(result.data.job);
      setQuestion("");
      void loadOverview();
    } else setError(result.error);
  }, [busy, loadOverview, mode, papers, question, web]);

  const remove = useCallback(
    async (id: string) => {
      const result = await api.del<{ deleted: string }>(`/api/research/${id}`);
      if (result.ok) {
        if (job?.job_id === id) setJob(null);
        void loadOverview();
      } else setError(result.error);
    },
    [job?.job_id, loadOverview],
  );

  const saveSettings = useCallback(async (changes: { auto_teach?: boolean; style?: string }) => {
    // Show the change at once; the server's answer settles it.
    setOverview((current) => (current ? { ...current, settings: { ...current.settings, ...changes } } : current));
    const result = await api.put<{ auto_teach: boolean; style: string }>("/api/research/settings", changes);
    if (result.ok) setOverview((current) => (current ? { ...current, settings: result.data } : current));
    else setError(result.error);
  }, []);

  const researchThis = useCallback((text: string) => {
    setView("research");
    setJob(null);
    setQuestion(text);
    window.setTimeout(() => askRef.current?.focus(), 0);
  }, []);

  const style = overview?.settings.style ?? "apa";
  const styles = overview?.styles ?? ["apa", "mla", "chicago", "ieee", "harvard", "bibtex"];
  const autoTeach = overview?.settings.auto_teach ?? true;
  const jobs = overview?.jobs ?? [];
  const runningCount = useMemo(() => jobs.filter((j) => RUNNING.has(j.status)).length, [jobs]);
  const ready = question.trim().length >= 8 && (web || papers);

  return (
    <div className="rs">
      <header className="rs-top">
        <div className="rs-top__title">
          <h1>Research</h1>
          <p>Every claim carries a source Nyx actually read.</p>
        </div>
        <div className="segmented rs-top__views" role="tablist" aria-label="Research view">
          <button role="tab" aria-selected={view === "research"} aria-pressed={view === "research"} onClick={() => setView("research")}>
            Research{runningCount > 0 ? ` · ${runningCount} running` : ""}
          </button>
          <button role="tab" aria-selected={view === "papers"} aria-pressed={view === "papers"} onClick={() => setView("papers")}>
            Papers
          </button>
        </div>
        <div className="rs-top__tools">
          <label className="rs-select">
            <span>Citations</span>
            <select value={style} onChange={(e) => void saveSettings({ style: e.target.value })}>
              {styles.map((s) => (
                <option key={s} value={s}>
                  {STYLE_LABEL[s] ?? s}
                </option>
              ))}
            </select>
          </label>
          <div className="rs-toggle" title="When research finishes, put what it found into Nyx's memory and its learning set.">
            <button
              type="button"
              className="switch"
              role="switch"
              aria-checked={autoTeach}
              aria-labelledby="rs-autoteach"
              onClick={() => void saveSettings({ auto_teach: !autoTeach })}
            />
            <span id="rs-autoteach">Teach Nyx automatically</span>
          </div>
        </div>
      </header>

      {error && (
        <p className="rs-error rs-error--bar" role="alert">
          <Icon name="alert" /> {error}
          <button className="rs-btn rs-btn--quiet" onClick={() => setError("")} aria-label="Dismiss">
            <Icon name="close" />
          </button>
        </p>
      )}

      {view === "papers" ? (
        <div className="rs-scroll">
          <PapersView style={style} onResearch={researchThis} />
        </div>
      ) : (
        <div className="rs-body">
          <aside className="rs-rail" aria-label="Past research">
            <button className="rs-btn rs-btn--primary rs-new" onClick={() => setJob(null)} disabled={!job}>
              <Icon name="plus" /> New research
            </button>
            <h2 className="rs-label rs-rail__title">Past research</h2>
            {overview && jobs.length === 0 && <p className="rs-hint">Nothing yet. Your first question starts the list.</p>}
            <ul className="rs-list">
              {jobs.map((item) => (
                <li key={item.job_id} className="rs-list__row">
                  <button
                    className="rs-item"
                    aria-current={item.job_id === job?.job_id || undefined}
                    onClick={() => void openJob(item.job_id)}
                  >
                    <span className={`rs-dot rs-dot--${item.status}`} aria-hidden="true" />
                    <span className="rs-item__text">
                      <span className="rs-item__q">{item.question}</span>
                      <span className="rs-item__meta">
                        {item.mode === "deep" ? "Deep" : "Standard"} · {STATUS_LABEL[item.status] ?? item.status}
                        {item.source_count ? ` · ${item.source_count} sources` : ""} · {whenLabel(item.created_at)}
                        {item.elapsed_seconds && item.status === "done" ? ` · ${tookLabel(item.elapsed_seconds)}` : ""}
                      </span>
                    </span>
                  </button>
                  <ConfirmButton
                    className="rs-item__x"
                    armed="Delete?"
                    title={`Delete “${item.question.slice(0, 60)}”`}
                    onConfirm={() => void remove(item.job_id)}
                  >
                    <Icon name="trash" />
                  </ConfirmButton>
                </li>
              ))}
            </ul>
          </aside>

          <main className="rs-main">
            {job ? (
              <JobView
                job={job}
                style={style}
                sections={overview?.sections ?? []}
                onChanged={setJob}
                onDelete={() => void remove(job.job_id)}
                onError={setError}
                onOpen={(next) => {
                  setJob(next);
                  void loadOverview();
                }}
              />
            ) : (
              <section className="rs-start">
                <h2>What should Nyx research?</h2>
                <p className="rs-start__lede">
                  Nyx searches the web and scholarly papers, reads the best sources, and writes a report where every claim
                  is cited.
                </p>
                <div className="rs-ask">
                  <textarea
                    ref={askRef}
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start();
                    }}
                    rows={4}
                    aria-label="Research question"
                    placeholder="Ask a real question — a sentence or two works best."
                  />
                </div>
                <div className="rs-modes" role="radiogroup" aria-label="How deep">
                  {(["standard", "deep"] as const).map((option) => (
                    <button
                      key={option}
                      type="button"
                      role="radio"
                      className="rs-mode"
                      aria-checked={mode === option}
                      onClick={() => setMode(option)}
                    >
                      <span className="rs-mode__head">
                        <Icon name={option === "standard" ? "search" : "sparkle"} />
                        <b>{option === "standard" ? "Standard" : "Deep"}</b>
                        <span className="rs-mode__time">{option === "standard" ? "about a minute" : "several minutes"}</span>
                      </span>
                      <span className="rs-mode__text">
                        {option === "standard"
                          ? "One pass: up to 12 sources, the best five read closely, a concise cited report."
                          : "Splits the question into parts, up to 36 sources, pulls out claims first, then a long report with disagreements and gaps."}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="rs-startbar">
                  <div className="rs-toggle">
                    <button type="button" className="switch" role="switch" aria-checked={web} aria-labelledby="rs-web"
                      onClick={() => setWeb((v) => !v)} />
                    <span id="rs-web">Web</span>
                  </div>
                  <div className="rs-toggle">
                    <button type="button" className="switch" role="switch" aria-checked={papers} aria-labelledby="rs-papers"
                      onClick={() => setPapers((v) => !v)} />
                    <span id="rs-papers">Papers <span className="rs-hint">OpenAlex, arXiv</span></span>
                  </div>
                  <button className="rs-btn rs-btn--primary rs-go" disabled={busy || !ready} onClick={() => void start()}>
                    <Icon name="search" /> {busy ? "Starting…" : "Start research"}
                  </button>
                </div>
                <p className="rs-hint">
                  {!web && !papers ? "Turn on the web, papers, or both." : "Ctrl+Enter starts it. It keeps going if you leave this tab."}
                </p>
                <div className="rs-examples">
                  <span className="rs-label">Try</span>
                  {EXAMPLES.map((example) => (
                    <button key={example} type="button" className="rs-chip" onClick={() => setQuestion(example)}>
                      {example}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
