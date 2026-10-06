/** Data Absorption / Training (Request R1–R8).
 *
 * Two views, as the owner asked: **Data analysis** — Nyx studies documents while you watch, on its own, from what you
 * give it, or on a subject — and **Data process use** — you give it data and ask for anything. A finished run leaves a
 * report: what it learned, what it stored, and boxes of changes it wants to make to itself that only you can approve.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { LiveRun } from "./LiveRun";
import { ProcessUse } from "./ProcessUse";
import { RunReport } from "./RunReport";
import { StudyStart } from "./StudyStart";
import type { Live, Overview } from "./types";
import { bytesLabel, clock } from "./types";
import "./absorb.css";

type View = "analysis" | "process";

export function AbsorbPanel() {
  const [view, setView] = useState<View>(() => {
    try { return (localStorage.getItem("nyx.absorb.view") as View) || "analysis"; } catch { return "analysis"; }
  });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { try { localStorage.setItem("nyx.absorb.view", view); } catch { /* private window */ } }, [view]);

  const loadOverview = useCallback(async () => {
    const result = await api.get<Overview>("/api/absorb");
    if (result.ok) {
      setOverview(result.data);
      setLive(result.data.active);
      setError("");
    } else setError(result.error);
  }, []);
  useEffect(() => { void loadOverview(); }, [loadOverview]);
  useEffect(() => onWorkspaceEvent((event) => { if (event.type === "absorb.update") void loadOverview(); }), [loadOverview]);

  // While a run is going, ask for the live view about once a second: that is the reading you watch.
  const runId = live?.id;
  const runningNow = live?.status === "running" || live?.status === "starting" || live?.status === "stopping";
  useEffect(() => {
    if (!runId || !runningNow || report) return;
    let alive = true;
    const tick = async () => {
      const result = await api.get<Live>(`/api/absorb/${runId}/live`);
      if (!alive) return;
      if (result.ok) setLive(result.data);
    };
    const timer = window.setInterval(() => { if (!document.hidden) void tick(); }, 900);
    return () => { alive = false; window.clearInterval(timer); };
  }, [runId, runningNow, report]);

  // A run that just finished: load its report once, so the owner sees what it learned without hunting for it.
  useEffect(() => {
    if (live && !report && live.report_ready && !runningNow && live.status !== "paused") setReport(live.id);
  }, [live?.report_ready, live?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const stop = async () => {
    if (!live) return;
    const result = await api.post<Live>(`/api/absorb/${live.id}/stop`, {}, 120_000);
    if (result.ok) setLive(result.data); else setError(result.error);
  };

  const counts = live?.counts ?? {};
  const statusText = !live ? "Idle"
    : live.status === "running" ? "Studying" : live.status === "paused" ? "Paused" : live.status === "stopping" ? "Finishing"
    : live.status === "starting" ? "Starting" : live.status;

  return (
    <div className="absorb">
      <div className="ab-bar">
        <span className="ab-bar__brand">/ <b>Data absorption</b> · training</span>
        <nav className="ab-nav" role="tablist" aria-label="Data absorption views">
          <button role="tab" aria-selected={view === "analysis" && !report} onClick={() => { setView("analysis"); setReport(null); }}>Data analysis</button>
          <button role="tab" aria-selected={view === "process"} onClick={() => setView("process")}>Data process use</button>
          {overview && overview.runs.length > 0 && (
            <button role="tab" aria-selected={Boolean(report)} onClick={() => { setView("analysis"); setReport(overview.runs[0].id); }}>Reports</button>
          )}
        </nav>
        <div className="ab-bar__stats">
          <span><span className={`ab-dot${runningNow ? " is-live" : live?.status === "paused" ? " is-warn" : ""}`} aria-hidden="true" />{statusText}</span>
          {live && <><span>docs <b>{counts.indexed ?? 0}</b></span><span>facts <b>{counts.facts ?? 0}</b></span><span>rows <b>{counts.rows ?? 0}</b></span></>}
          {overview && <span title="How much of your disk this tab uses — documents are never kept, only facts">store <b>{bytesLabel(overview.storage_bytes)}</b></span>}
        </div>
      </div>

      {view === "process" ? (
        <ProcessUse />
      ) : report ? (
        <RunReport runId={report} onBack={() => { setReport(null); void loadOverview(); }}
          onStarted={(started) => { setReport(null); setLive(started); void loadOverview(); }} />
      ) : live ? (
        <LiveRun live={live} onChanged={setLive} onStop={() => void stop()} onReport={() => setReport(live.id)} />
      ) : (
        <div className="ab-page">
          <div className="ab-page__inner">
            <div className="ab-hero">
              <div className="ab-label">Data analysis</div>
              <h1>Watch Nyx read, and keep what it learns.</h1>
              <p>
                Nyx reads papers, GitHub projects, Wikipedia articles, web pages and your own files line by line. Every word it
                knows lights up and feeds the topic it belongs to; every fact it keeps goes into its memory, so later answers —
                from any model, including a local one — can use it. Stop whenever you like and it reports what it learned.
              </p>
            </div>
            {error && <p className="ab-error" role="alert">{error}</p>}
            {overview && <StudyStart overview={overview} onStarted={(started) => { setLive(started); void loadOverview(); }} />}
            {overview && overview.runs.length > 0 && (
              <section className="ab-card" aria-labelledby="ab-runs">
                <h2 id="ab-runs" className="ab-label" style={{ margin: 0 }}>Earlier runs</h2>
                <ul className="ab-history">
                  {overview.runs.map((run) => (
                    <li key={run.id}>
                      <button className="ab-link" onClick={() => setReport(run.id)}>{run.title}</button>
                      <span className="ab-note">
                        {clock(run.started_at)} · {run.docs} docs · {run.facts} facts
                        {run.pending > 0 ? ` · ${run.pending} waiting for you` : ""}
                      </span>
                      {run.headline && <span className="ab-note">{run.headline}</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {overview && (
              <section className="ab-card">
                <h2 className="ab-label" style={{ margin: 0 }}>How what it studies is used</h2>
                <label className="ab-actions" style={{ gap: 10 }}>
                  <button className="switch" role="switch" aria-checked={overview.prefs.use_in_chats}
                    aria-label="Use what Nyx studied in every chat"
                    onClick={() => void api.put("/api/absorb/prefs", { use_in_chats: !overview.prefs.use_in_chats }).then(loadOverview)} />
                  <span className="ab-note" style={{ maxWidth: 620 }}>
                    <b style={{ color: "var(--ab-text)" }}>Use what it studied in every chat.</b> When a message matches something Nyx
                    read, the facts are added to that turn — so whichever model answers, online or the local one, answers better.
                  </span>
                </label>
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
