/** The live board of a study run (Request R1, R5): the owner's reference screen, for Nyx's own learning.
 *
 * Pipeline strip · controls and the document queue · the reader · the topic list · the document detail with the dataset ·
 * coverage and the knowledge-gain chart. The signature: when the reader reaches a line, its topic words light up and a
 * curve runs from each word to that topic's node while the topic's bar fills (the SVG threads below). Everything the
 * curves say is also written out (topic codes, counts, the legend), and with reduced motion they are drawn without
 * animation.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { api } from "../../api";
import { useReducedMotion } from "../../useReducedMotion";
import type { DatasetRow, DocView, Live, ReaderLine, Settings, Span, Topic } from "./types";
import { clock, topicColor } from "./types";

const STAGE_LABEL: Record<string, string> = {
  ingest: "Ingest", dedupe: "Dedupe", tokenize: "Tokenize", entities: "Entities", topics: "Topic model", claims: "Claims", index: "Index",
};
const STATE_LABEL: Record<DocView["state"], string> = {
  queued: "Queued", fetching: "Fetching", ready: "Ready", reading: "Reading", skimming: "Skimming", analysed: "Indexing",
  indexed: "Indexed", skipped: "Skipped", error: "Error",
};
const SOURCE_LABELS: Record<string, string> = { papers: "Papers", github: "GitHub", wiki: "Wikipedia", web: "Web" };

function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

function Highlighted({ text, spans, topics, current, lineIndex, register }: {
  text: string; spans: Span[]; topics: Map<string, Topic>; current: boolean; lineIndex: number;
  register?: (key: string, el: HTMLElement | null) => void;
}) {
  const parts: ReactElement[] = [];
  let cursor = 0;
  spans.forEach((span, index) => {
    if (span.s < cursor || span.e > text.length) return;
    if (span.s > cursor) parts.push(<span key={`t${index}`}>{text.slice(cursor, span.s)}</span>);
    const topic = span.topic ? topics.get(span.topic) : undefined;
    parts.push(
      <mark key={`h${index}`} className={`ab-hl${topic ? "" : " is-entity"}${current ? " is-new" : ""}`}
        style={topic ? { ["--hl" as string]: topicColor(topic.color) } : undefined}
        title={topic ? `${topic.code} · ${topic.name}` : "A name Nyx noticed"}
        ref={register && topic ? (el) => register(`${lineIndex}-${index}`, el) : undefined}
        data-topic={span.topic ?? undefined}>
        {text.slice(span.s, span.e)}
      </mark>,
    );
    cursor = span.e;
  });
  if (cursor < text.length) parts.push(<span key="end">{text.slice(cursor)}</span>);
  return <>{parts}</>;
}

function GainChart({ points, topics, now }: { points: Live["chart"]; topics: Map<string, Topic>; now: number }) {
  const W = 1000, H = 96, pad = 6;
  const recent = points.filter((p) => now - p.t <= 180);
  const x = (t: number) => pad + ((t - (now - 180)) / 180) * (W - pad * 2);
  const y = (v: number) => H - pad - Math.max(0, Math.min(1, v)) * (H - pad * 2);
  const smooth: string[] = [];
  recent.forEach((p, i) => {
    const window = recent.slice(Math.max(0, i - 7), i + 1);
    const avg = window.reduce((sum, w) => sum + w.v, 0) / window.length;
    smooth.push(`${x(p.t).toFixed(1)},${y(avg).toFixed(1)}`);
  });
  const average = recent.length ? recent.reduce((s, p) => s + p.v, 0) / recent.length : 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
      aria-label={`New knowledge per line over the last 3 minutes: ${recent.length} lines, average ${Math.round(average * 100)}% new.`}>
      {[0.25, 0.5, 0.75].map((v) => <line key={v} x1={pad} x2={W - pad} y1={y(v)} y2={y(v)} stroke="rgba(160,220,190,0.08)" strokeWidth={1} />)}
      {smooth.length > 1 && <polyline points={smooth.join(" ")} fill="none" stroke="#e8efe9" strokeOpacity={0.75} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
      {recent.map((p, i) => (
        <circle key={`${p.t}-${i}`} cx={x(p.t)} cy={y(p.v)} r={2.6} fill={p.topic && topics.get(p.topic) ? topicColor(topics.get(p.topic)!.color) : "#84948b"} />
      ))}
    </svg>
  );
}

export function LiveRun({ live, onChanged, onStop, onReport }: {
  live: Live;
  onChanged: (live: Live) => void;
  onStop: () => void;
  onReport: () => void;
}) {
  const reduced = useReducedMotion();
  const topics = useMemo(() => new Map(live.topics.map((t) => [t.id, t])), [live.topics]);
  const [held, setHeld] = useState<DocView | null>(null);
  const [heldRow, setHeldRow] = useState<number | null>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const [paths, setPaths] = useState<{ key: string; d: string; color: string; len: number; x2: number; y2: number; x1: number; y1: number }[]>([]);
  const [local, setLocal] = useState<Settings>(live.settings);
  useEffect(() => { setLocal(live.settings); }, [live.settings]);

  const doc = held ?? live.reader.doc ?? null;
  const lines: ReaderLine[] = doc?.lines ?? [];
  const lineIndex = held ? lines.length : doc?.line_index ?? 0;
  const currentLine = held ? -1 : lineIndex - 1;
  const running = live.status === "running" || live.status === "paused" || live.status === "starting";

  // --- threads: from each lit word on the current line to its topic's node --------------------------------
  const board = useRef<HTMLDivElement>(null);
  const readerCol = useRef<HTMLDivElement>(null);
  const topicCol = useRef<HTMLDivElement>(null);
  const marks = useRef(new Map<string, HTMLElement>());
  const nodes = useRef(new Map<string, HTMLElement>());
  const registerMark = useCallback((key: string, el: HTMLElement | null) => {
    if (el) marks.current.set(key, el); else marks.current.delete(key);
  }, []);

  const measure = useCallback(() => {
    const root = board.current, reader = readerCol.current, topicList = topicCol.current;
    if (!root || !reader || !topicList || currentLine < 0) { setPaths([]); return; }
    const box = root.getBoundingClientRect();
    const readerBox = reader.getBoundingClientRect();
    const topicBox = topicList.getBoundingClientRect();
    if (topicBox.left < readerBox.right - 4) { setPaths([]); return; } // stacked layout: no room for curves
    const out: typeof paths = [];
    marks.current.forEach((el, key) => {
      if (!key.startsWith(`${currentLine}-`)) return;
      const topicId = el.dataset.topic;
      const node = topicId ? nodes.current.get(topicId) : undefined;
      const topic = topicId ? topics.get(topicId) : undefined;
      if (!node || !topic) return;
      const a = el.getBoundingClientRect(), b = node.getBoundingClientRect();
      if (a.bottom < readerBox.top + 30 || a.top > readerBox.bottom) return;
      const x1 = a.right - box.left, y1 = a.top + a.height / 2 - box.top;
      const x2 = b.left + b.width / 2 - box.left;
      const y2 = Math.max(topicBox.top + 8, Math.min(topicBox.bottom - 8, b.top + b.height / 2)) - box.top;
      const dx = Math.max(40, (x2 - x1) * 0.45);
      const len = Math.hypot(x2 - x1, y2 - y1) * 1.25;
      out.push({ key: `${doc?.id}-${key}`, d: `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`,
        color: topicColor(topic.color), len, x1, y1, x2, y2 });
    });
    setPaths(out);
  }, [currentLine, doc?.id, topics]);

  useLayoutEffect(() => {
    const frame = window.requestAnimationFrame(measure);
    return () => window.cancelAnimationFrame(frame);
  }, [measure, lines.length, lineIndex, live.topics]);
  useEffect(() => {
    const reader = readerCol.current, topicList = topicCol.current;
    const onMove = () => window.requestAnimationFrame(measure);
    reader?.addEventListener("scroll", onMove, { passive: true });
    topicList?.addEventListener("scroll", onMove, { passive: true });
    window.addEventListener("resize", onMove);
    return () => {
      reader?.removeEventListener("scroll", onMove);
      topicList?.removeEventListener("scroll", onMove);
      window.removeEventListener("resize", onMove);
    };
  }, [measure]);

  // Keep the line being read in view, and light up the topics it touched.
  const currentRef = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (held || currentLine < 0) return;
    const el = currentRef.current, reader = readerCol.current;
    if (el && reader) {
      const r = el.getBoundingClientRect(), c = reader.getBoundingClientRect();
      if (r.top < c.top + 60 || r.bottom > c.bottom - 30) el.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
    }
    const touched = new Set((lines[currentLine]?.spans ?? []).map((s) => s.topic).filter((t): t is string => Boolean(t)));
    if (touched.size) {
      setFlash(touched);
      const timer = window.setTimeout(() => setFlash(new Set()), 900);
      return () => window.clearTimeout(timer);
    }
  }, [currentLine, doc?.id, held]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- actions -------------------------------------------------------------------------------------------
  const send = async (path: string, body?: unknown, method: "post" | "put" = "post") => {
    const result = method === "put" ? await api.put<Live>(path, body) : await api.post<Live>(path, body);
    if (result.ok && result.data && (result.data as Live).id) onChanged(result.data as Live);
  };
  const saveSettings = (changes: Partial<Settings>) => void send(`/api/absorb/${live.id}/settings`, changes, "put");
  const focus = (topicId: string | null) => void send(`/api/absorb/${live.id}/focus`, { topic: topicId }, "put");
  const hold = async (row: DatasetRow, index: number) => {
    const result = await api.get<{ doc: DocView }>(`/api/absorb/${live.id}/doc/${row.doc}`);
    if (result.ok) { setHeld(result.data.doc); setHeldRow(index); }
  };

  const reading = live.queue.filter((d) => ["reading", "skimming", "fetching", "analysed"].includes(d.state));
  const totalCount = live.topics.reduce((sum, t) => sum + t.count, 0);
  const topTopic = [...live.topics].sort((a, b) => b.count - a.count)[0];
  const elapsed = live.started_at ? (live.ended_at || live.now) - live.started_at : 0;
  const left = live.ends_at ? live.ends_at - live.now : null;
  const vote = doc?.vote ?? {};
  const voteEntries = Object.entries(vote).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <div className="ab-strip" role="list" aria-label="Pipeline">
        {Object.keys(STAGE_LABEL).map((stage, i) => {
          const count = live.stages[stage] ?? 0;
          const current = running && live.stage === stage;
          return (
            <span key={stage} role="listitem" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              {i > 0 && <span className="ab-strip__sep" aria-hidden="true">·</span>}
              <span className={`ab-stage${current ? " is-current" : count ? " is-done" : ""}`} aria-current={current ? "step" : undefined}>
                <span className="ab-dot" aria-hidden="true" />{STAGE_LABEL[stage]}<span className="ab-stage__n">{count}</span>
              </span>
            </span>
          );
        })}
        <span className="ab-strip__right">
          <span>elapsed {duration(elapsed)}</span>
          {left !== null && running && <span>{duration(left)} left</span>}
          <span>{live.counts.lines ?? 0} lines</span>
        </span>
      </div>

      <div className="ab-board" ref={board}>
        {/* Controls + queue */}
        <aside className="ab-col" aria-label="Controls and documents">
          <div className="ab-section">
            <label className="ab-slider">
              <span>Reading speed</span><output>{local.speed.toFixed(2)}×</output>
              <input type="range" min={0.25} max={4} step={0.25} value={local.speed} disabled={!running}
                onChange={(e) => setLocal((s) => ({ ...s, speed: Number(e.target.value) }))}
                onPointerUp={() => saveSettings({ speed: local.speed })} onKeyUp={() => saveSettings({ speed: local.speed })} />
            </label>
            <label className="ab-slider">
              <span>Documents per minute</span><output>{local.docs_per_min}/min</output>
              <input type="range" min={2} max={60} step={1} value={local.docs_per_min} disabled={!running}
                onChange={(e) => setLocal((s) => ({ ...s, docs_per_min: Number(e.target.value) }))}
                onPointerUp={() => saveSettings({ docs_per_min: local.docs_per_min })} onKeyUp={() => saveSettings({ docs_per_min: local.docs_per_min })} />
            </label>
            <div className="ab-btnrow">
              {live.status === "paused"
                ? <button className="ab-btn" onClick={() => void send(`/api/absorb/${live.id}/resume`)}>Resume</button>
                : <button className="ab-btn" disabled={live.status !== "running"} onClick={() => void send(`/api/absorb/${live.id}/pause`)}>Pause</button>}
              {running
                ? <button className="ab-btn is-danger" disabled={live.status === "stopping"} onClick={onStop}>{live.status === "stopping" ? "Stopping…" : "Stop & Report"}</button>
                : <button className="ab-btn is-primary" disabled={!live.report_ready} onClick={onReport}>Open Report</button>}
            </div>
            {live.mode !== "given" && (
              <div className="ab-tags" role="group" aria-label="Sources">
                {Object.keys(SOURCE_LABELS).map((name) => (
                  <button key={name} type="button" className="ab-tag" aria-pressed={local.sources[name] !== false} disabled={!running}
                    onClick={() => { const next = { ...local.sources, [name]: local.sources[name] === false }; setLocal((s) => ({ ...s, sources: next })); saveSettings({ sources: next }); }}>
                    <span className="ab-tag__box" aria-hidden="true" />{SOURCE_LABELS[name]}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="ab-col__head" style={{ position: "static" }}>
            <span className="ab-label">Documents</span>
            <span className="ab-label">{live.counts.indexed ?? 0} read · {live.counts.queued ?? 0} queued</span>
          </div>
          <ul className="ab-queue" aria-live="off">
            {live.queue.map((item) => (
              <li key={item.id}>
                <div className={`ab-qitem is-${item.state}`}>
                  <div className="ab-qitem__top">
                    <span>{item.source || item.kind}</span>
                    <span className="ab-qitem__state">{STATE_LABEL[item.state]}</span>
                  </div>
                  <div className="ab-qitem__title">{item.title}</div>
                  <div className="ab-qitem__meta">
                    {item.state === "reading" || item.state === "skimming"
                      ? <span>{item.line_index}/{item.line_total} lines</span>
                      : item.state === "indexed" ? <span>{item.facts} facts</span> : item.error ? <span title={item.error}>{item.error.slice(0, 40)}</span> : <span>{clock(item.filed_at)}</span>}
                    {item.state === "indexed" && <span className={`ab-gain ${item.gain >= 0.35 ? "is-up" : "is-low"}`}>{Math.round(item.gain * 100)}% new</span>}
                  </div>
                  {(item.state === "reading" || item.state === "skimming") && (
                    <div className="ab-qitem__bar" aria-hidden="true"><span style={{ width: `${item.line_total ? (item.line_index / item.line_total) * 100 : 0}%` }} /></div>
                  )}
                </div>
              </li>
            ))}
            {live.queue.length === 0 && <li className="ab-empty" style={{ padding: 16, fontSize: 12.5 }}>Finding documents…</li>}
          </ul>
          <div className="ab-queue-stats">
            <div><span className="ab-label">Queue</span><b>{(live.counts.queued ?? 0) + (live.counts.fetching ?? 0)}</b><span>{live.counts.sampled_out ?? 0} sampled out</span></div>
            <div><span className="ab-label">Top topic</span><b>{totalCount && topTopic ? `${Math.round((topTopic.count / totalCount) * 100)}%` : "—"}</b><span>{topTopic?.name ?? "none yet"}</span></div>
          </div>
        </aside>

        {/* Reader */}
        <section className="ab-col ab-reader" ref={readerCol} aria-label="Reader">
          {doc ? (
            <>
              <div className="ab-reader__head">
                <span className="ab-chipsrc is-kind">{doc.kind}</span>
                <span className="ab-chipsrc">{doc.source}</span>
                <span>filed {clock(doc.filed_at)} · read from {clock(doc.read_at)}</span>
                {held ? (
                  <button className="ab-btn" style={{ marginLeft: "auto", minHeight: 24, padding: "3px 8px" }} onClick={() => { setHeld(null); setHeldRow(null); }}>Back to Live</button>
                ) : (
                  <span className="ab-lineprog">
                    line {Math.max(0, lineIndex)}/{doc.line_total}
                    <span className="ab-lineprog__track" aria-hidden="true"><span style={{ width: `${doc.line_total ? (lineIndex / doc.line_total) * 100 : 0}%` }} /></span>
                  </span>
                )}
              </div>
              <div className="ab-reader__body">
                <h2 className="ab-doc-title">
                  {doc.url ? <a href={doc.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
                    <Highlighted text={doc.title} spans={held ? [] : live.reader.title_spans ?? []} topics={topics} current={false} lineIndex={-1} />
                  </a> : <Highlighted text={doc.title} spans={held ? [] : live.reader.title_spans ?? []} topics={topics} current={false} lineIndex={-1} />}
                </h2>
                {doc.meta && Object.keys(doc.meta).length > 0 && (
                  <p className="ab-doc-meta">{Object.entries(doc.meta).map(([k, v]) => `${k} ${String(v)}`).join(" · ")}</p>
                )}
                <ol className="ab-lines">
                  {lines.map((line) => {
                    const isRead = line.i < lineIndex - 1 || Boolean(held);
                    const isCurrent = line.i === currentLine;
                    return (
                      <li key={line.i} ref={isCurrent ? currentRef : undefined} className={`ab-line${isCurrent ? " is-current" : isRead ? " is-read" : ""}`}
                        aria-current={isCurrent ? "true" : undefined}>
                        <Highlighted text={line.text} spans={line.i < lineIndex || held ? line.spans : []} topics={topics} current={isCurrent && !reduced}
                          lineIndex={line.i} register={isCurrent ? registerMark : undefined} />
                      </li>
                    );
                  })}
                </ol>
                {!held && live.reader.finished && <p className="ab-note" style={{ marginTop: 18 }}>Run finished — open the report to see what Nyx learned and approve what it wants to change.</p>}
              </div>
            </>
          ) : (
            <div className="ab-empty">
              <h2>{live.status === "starting" || live.status === "running" ? "Getting ready to read" : "Nothing was read"}</h2>
              <p>{live.log[0]?.text ?? "Planning topics and finding the first documents."}</p>
            </div>
          )}
        </section>

        {/* Topic list */}
        <section className="ab-col" ref={topicCol} aria-label="Topic list">
          <div className="ab-col__head">
            <span className="ab-label">Topic list</span>
            <button className="ab-btn" style={{ minHeight: 24, padding: "3px 8px" }} disabled={!live.focus || !running} onClick={() => focus(null)}>Clear Focus</button>
          </div>
          <ul className="ab-topics">
            {live.topics.map((topic) => {
              const share = totalCount ? topic.count / totalCount : 0;
              const active = paths.some((p) => p.color === topicColor(topic.color)) || flash.has(topic.id);
              return (
                <li key={topic.id}>
                  <button type="button" className={`ab-topic${flash.has(topic.id) && !reduced ? " is-flash" : ""}${active ? " is-active" : ""}`}
                    aria-pressed={live.focus === topic.id} disabled={!running && live.focus !== topic.id}
                    style={{ ["--tc" as string]: topicColor(topic.color) }}
                    onClick={() => focus(live.focus === topic.id ? null : topic.id)}
                    title={live.focus === topic.id ? "Studying this topic first — click to study every topic" : `Study ${topic.name} first`}>
                    <span className="ab-topic__node" ref={(el) => { if (el) nodes.current.set(topic.id, el); else nodes.current.delete(topic.id); }} aria-hidden="true" />
                    <span className="ab-topic__name"><span className="ab-topic__code">{topic.code}</span>{topic.name}</span>
                    <span className="ab-topic__count">{topic.count}</span>
                    <span className="ab-topic__bar" aria-hidden="true">
                      <span className="ab-topic__share" style={{ width: `${share * 100}%` }} />
                      <span className="ab-topic__vote" style={{ width: `${(topic.doc_vote || 0) * 100}%` }} />
                      <span className="ab-topic__tick" style={{ left: `calc(${Math.min(1, topic.gain * 2) * 100}% - 1px)` }} />
                    </span>
                    <span className="ab-topic__terms">
                      <span>{topic.terms.slice(0, 3).join(" · ") || "—"}</span>
                      <span>{topic.docs} docs · {Math.round(share * 100)}%</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="ab-legend">
            A row lights up when a word on the line being read is in that topic's term list · pale bar = share of every word matched ·
            bright bar = this document's vote · tick = how much of it is new to Nyx · click a topic to study it first.
          </p>
        </section>

        {/* Detail + dataset */}
        <section className="ab-col ab-col--detail" aria-label="Document detail and dataset">
          <div className="ab-section">
            {doc ? (
              <>
                <h3 className="ab-detail__title">{doc.title}</h3>
                <div className="ab-detail__sub">{doc.source} · {doc.line_total} lines · {doc.tokens.toLocaleString()} tokens</div>
                {voteEntries.length > 0 && (
                  <>
                    <div className="ab-stack" role="img" aria-label={`Topic share: ${voteEntries.map(([id, v]) => `${topics.get(id)?.code ?? id} ${Math.round(v * 100)}%`).join(", ")}`}>
                      {voteEntries.map(([id, v]) => <span key={id} style={{ width: `${v * 100}%`, background: topicColor(topics.get(id)?.color) }} />)}
                    </div>
                    <div className="ab-stack-legend">
                      {voteEntries.slice(0, 5).map(([id, v]) => (
                        <span key={id}><span className="ab-swatch" style={{ background: topicColor(topics.get(id)?.color) }} />{topics.get(id)?.code ?? id} {Math.round(v * 100)}%</span>
                      ))}
                    </div>
                  </>
                )}
              </>
            ) : <span className="ab-note">No document yet.</span>}
          </div>
          <div className="ab-section">
            <div className="ab-label">New to Nyx</div>
            <div className="ab-meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((doc?.gain ?? 0) * 100)} aria-label="Share of this document that is new to Nyx">
              <span style={{ width: `${(doc?.gain ?? 0) * 100}%` }} />
            </div>
            <div className="ab-detail__sub">{doc ? `${Math.round((doc.gain ?? 0) * 100)}% new so far · ${doc.facts ?? 0} facts kept` : "—"}</div>
            {doc?.summary && <p className="ab-summary">{doc.summary}</p>}
          </div>
          <div className="ab-col__head">
            <span className="ab-label">Dataset</span>
            <span className="ab-label">{live.counts.rows ?? 0} rows</span>
          </div>
          <table className="ab-table">
            <thead><tr><th scope="col">Time</th><th scope="col">Source</th><th scope="col">Topic</th><th scope="col">Fact</th></tr></thead>
            <tbody>
              {live.dataset.map((row, index) => (
                <tr key={`${row.t}-${index}`} className={`ab-row${heldRow === index ? " is-held" : ""}`} tabIndex={0}
                  onClick={() => void hold(row, index)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void hold(row, index); } }}
                  aria-label={`${row.topic}: ${row.text}. Press to show its document.`}>
                  <td>{clock(row.t)}</td>
                  <td>{row.source.slice(0, 10)}</td>
                  <td style={{ color: row.topic_id && topics.get(row.topic_id) ? topicColor(topics.get(row.topic_id)!.color) : undefined }}>{row.topic}</td>
                  <td className="ab-fact">{row.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {live.dataset.length === 0 && <p className="ab-legend">Facts appear here as each document is indexed. Click a row to hold its document in the reader.</p>}
        </section>

        {/* Coverage + gain chart */}
        <div className="ab-bottom">
          <div className="ab-coverage" aria-label="Coverage by topic in the last minute">
            <div className="ab-coverage__label ab-label">Coverage · {live.topics.length}</div>
            {live.coverage.map((c) => (
              <div key={c.id} className={`ab-cov${live.focus === c.id ? " is-focus" : ""}`} style={{ ["--tc" as string]: topicColor(c.color) }}>
                <div className="ab-cov__top">
                  <span className="ab-cov__code">{c.code}</span>
                  <span className={`ab-cov__delta ${c.delta > 0.005 ? "is-up" : c.delta < -0.005 ? "is-down" : "is-flat"}`}>
                    {c.delta >= 0 ? "+" : "−"}{Math.abs(c.delta).toFixed(2)}
                  </span>
                </div>
                <div className="ab-cov__bar" aria-hidden="true"><span style={{ width: `${c.share * 100}%` }} /></div>
              </div>
            ))}
          </div>
          <div className="ab-chart">
            <div className="ab-chart__head">
              <span className="ab-label">Knowledge gain — last 3 minutes</span>
              <span className="ab-label">one point per line · colour = topic · line = recent average</span>
            </div>
            <GainChart points={live.chart} topics={topics} now={live.now} />
          </div>
        </div>

        <svg className="ab-threads" aria-hidden="true">
          {paths.map((p) => (
            <g key={p.key}>
              <path d={p.d} stroke={p.color} className={`ab-thread${reduced ? "" : " is-drawing"}`} style={{ ["--len" as string]: `${p.len}` }} />
              <circle cx={p.x1} cy={p.y1} r={2.5} fill={p.color} className="ab-thread-end" />
              <circle cx={p.x2} cy={p.y2} r={3} fill={p.color} className="ab-thread-end" />
            </g>
          ))}
        </svg>
      </div>
      {reading.length > 1 && <span className="sr-only" aria-live="polite">Reading {reading.length} documents at once.</span>}
    </>
  );
}
