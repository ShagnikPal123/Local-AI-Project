/** Collab — send what you changed to GitHub for review, and see everyone's changes (Request K, 2026-09-16).
 *
 * "A second website for beta testers where they can apply changes to github, have a special page for collaboration
 * where they send and show all changes and it auto uploads those changes to that tab."
 *
 * Left: this install's changes (code Nyx applied, tabs, skills, agents you made) — tick, preview exactly which files
 * leave the PC (with a secret check), title, Send. Or send feedback. Right: the live feed from the Collab site, the
 * same list testers see at /collab, refreshing by itself.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { pushToast } from "../state/toastStore";
import "./improve/improve.css";

interface Candidate { id: string; kind: string; title: string; detail: string; files: string[]; at: number }
interface FeedItem {
  id: string; number: number; kind: string; title: string; tester: string; summary: string; files: string[];
  status: "open" | "merged" | "closed"; created_at: string; updated_at: string; url: string; comments?: number;
}
interface Status {
  site_url: string; collab_url: string;
  identity: { has_key: boolean; name?: string; role?: string; exp?: number };
  sent: { title: string; number: number; url: string; kind: string; at: number }[];
}
interface Preview { files: { path: string; bytes: number }[]; secrets: string[] }

const KIND_ICON: Record<string, string> = { code: "⌘", tab: "▦", skill: "✦", agent: "◉", design: "◈", feedback: "✎" };
const STATUS_TEXT: Record<string, string> = { open: "○ In review", merged: "✓ Merged", closed: "– Closed" };

function ago(iso: string | number): string {
  const t = typeof iso === "number" ? iso * 1000 : new Date(iso).getTime();
  const s = Math.max(1, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function CollabPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<Preview | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<"change" | "feedback">("change");
  const [busy, setBusy] = useState(false);
  const [feed, setFeed] = useState<{ items: FeedItem[]; counts: Record<string, number> } | null>(null);
  const [feedError, setFeedError] = useState("");
  const [filter, setFilter] = useState("all");
  const [siteDraft, setSiteDraft] = useState("");

  const loadLocal = useCallback(async () => {
    const [s, c] = await Promise.all([api.get<Status>("/api/collab/status"), api.get<{ candidates: Candidate[] }>("/api/collab/candidates")]);
    if (s.ok) { setStatus(s.data); setSiteDraft(s.data.site_url); }
    if (c.ok) setCandidates(c.data.candidates);
  }, []);
  const loadFeed = useCallback(async (force = false) => {
    const result = await api.get<{ items: FeedItem[]; counts: Record<string, number> }>(`/api/collab/feed${force ? "?force=true" : ""}`, 25_000);
    if (result.ok) { setFeed(result.data); setFeedError(""); } else setFeedError(result.error);
  }, []);
  useEffect(() => { void loadLocal(); void loadFeed(); }, [loadLocal, loadFeed]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) void loadFeed(); }, 30_000);
    return () => window.clearInterval(timer);
  }, [loadFeed]);

  useEffect(() => {
    if (picked.size === 0) { setPreview(null); return; }
    let alive = true;
    void api.post<Preview>("/api/collab/preview", { ids: Array.from(picked) }).then((r) => { if (alive && r.ok) setPreview(r.data); });
    return () => { alive = false; };
  }, [picked]);

  async function send() {
    setBusy(true);
    const result = mode === "feedback"
      ? await api.post<{ number: number; url: string; kind: string }>("/api/collab/feedback", { title, description }, 60_000)
      : await api.post<{ number: number; url: string; kind: string }>("/api/collab/send", { ids: Array.from(picked), title, description }, 90_000);
    setBusy(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(`Sent — ${result.data.kind === "feedback" ? "issue" : "pull request"} #${result.data.number} is waiting for review.`, "ok");
    setPicked(new Set()); setTitle(""); setDescription("");
    void loadLocal(); void loadFeed(true);
  }

  async function saveSite() {
    const result = await api.put<{ site_url: string }>("/api/collab/config", { site_url: siteDraft });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    void loadLocal(); void loadFeed(true);
  }

  const shown = useMemo(() => (feed?.items ?? []).filter((i) =>
    filter === "all" ? true : filter === "open" || filter === "merged" ? i.status === filter : i.kind === filter), [feed, filter]);
  const identity = status?.identity;
  const canSend = Boolean(identity?.has_key) && title.trim().length >= 4 && !busy &&
    (mode === "feedback" || (picked.size > 0 && !(preview?.secrets.length)));

  return (
    <div className="page">
      <div className="page__inner">
        <div className="page__head">
          <div>
            <div className="page__eyebrow">Beta testers</div>
            <h1 className="page__title">Collab</h1>
            <p className="page__sub">
              Send what you changed to GitHub for review — every change becomes a pull request the owner approves — and see
              everyone's changes as they arrive. The same list is on the web at{" "}
              {status && <a href={status.collab_url} target="_blank" rel="noopener noreferrer">{status.collab_url.replace(/^https:\/\//, "")}</a>}.
            </p>
          </div>
        </div>

        <div className="grid-2">
          <section className="card" aria-labelledby="collab-send">
            <div className="section-title" id="collab-send">Send</div>
            {identity && !identity.has_key && (
              <p className="field-row__hint" style={{ color: "var(--color-warn)" }}>
                ▲ Redeem your NYX1- access key first (Settings → Access). It's how the site knows the change is yours.
              </p>
            )}
            {identity?.has_key && <p className="field-row__hint">Sending as <b>{identity.name}</b> ({identity.role})</p>}
            <div className="segmented" role="group" aria-label="What to send" style={{ margin: "6px 0 10px" }}>
              <button aria-pressed={mode === "change"} onClick={() => setMode("change")}>My changes</button>
              <button aria-pressed={mode === "feedback"} onClick={() => setMode("feedback")}>Feedback or a bug</button>
            </div>

            {mode === "change" && (
              <>
                {candidates.length === 0 && <p className="field-row__hint">Nothing to send yet. Code Nyx applies, tabs, skills and agents you make show up here.</p>}
                <ul className="review__list" style={{ maxHeight: 320, overflowY: "auto" }}>
                  {candidates.map((c) => (
                    <li key={c.id} className="review__item" style={{ gridTemplateColumns: "auto auto minmax(0,1fr)" }}>
                      <input type="checkbox" className="review__check" checked={picked.has(c.id)} aria-label={`Send ${c.title}`}
                        onChange={(e) => setPicked((s) => { const n = new Set(s); if (e.target.checked) n.add(c.id); else n.delete(c.id); return n; })} />
                      <span aria-hidden="true" style={{ fontSize: 18, width: 22, textAlign: "center" }}>{KIND_ICON[c.kind] ?? "•"}</span>
                      <div className="review__body">
                        <b style={{ fontSize: 13.5 }}>{c.title}</b>
                        <span className="field-row__hint" style={{ margin: 0 }}>{c.detail}{c.at ? ` · ${ago(c.at)}` : ""}</span>
                        <div className="review__meta">{c.files.map((f) => <code key={f}>{f}</code>)}</div>
                      </div>
                    </li>
                  ))}
                </ul>
                {preview && (
                  <p className="field-row__hint" aria-live="polite" style={{ color: preview.secrets.length ? "#ffb4ae" : undefined }}>
                    {preview.secrets.length
                      ? `▲ Won't send — looks like a secret: ${preview.secrets.slice(0, 2).join("; ")}`
                      : `✓ ${preview.files.length} file${preview.files.length === 1 ? "" : "s"} will leave this PC (${Math.ceil(preview.files.reduce((n, f) => n + f.bytes, 0) / 1000)} KB), no secrets found.`}
                  </p>
                )}
              </>
            )}

            <label className="keys-field" style={{ marginTop: 10 }}><span>Title</span>
              <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)}
                placeholder={mode === "feedback" ? "e.g. Voice stops after two answers" : "e.g. Calmer voice between paragraphs"} /></label>
            <label className="keys-field" style={{ marginTop: 8 }}><span>What and why</span>
              <textarea rows={4} maxLength={6000} value={description} onChange={(e) => setDescription(e.target.value)}
                style={{ resize: "vertical", padding: "8px 10px", borderRadius: 10, border: 0, font: "inherit", color: "var(--color-text)", background: "#0b0b10", boxShadow: "inset 0 0 0 1px var(--color-divider)" }}
                placeholder="What you changed or saw, how to reproduce, how you tested it." /></label>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
              <button className="btn btn-primary" disabled={!canSend} onClick={() => void send()}>
                {busy ? "Sending…" : mode === "feedback" ? "Send Feedback" : `Send ${picked.size || ""} for Review`.replace("  ", " ")}
              </button>
            </div>

            {status && status.sent.length > 0 && (
              <>
                <div className="section-title" style={{ marginTop: 16 }}>You sent</div>
                <ul className="log-list">
                  {status.sent.slice(0, 6).map((s) => (
                    <li key={`${s.number}-${s.at}`}><time>{ago(s.at)}</time><span>#{s.number} {s.title}</span></li>
                  ))}
                </ul>
              </>
            )}
            <details style={{ marginTop: 12 }}>
              <summary className="field-row__hint">Collab site address</summary>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <input className="text-input" value={siteDraft} onChange={(e) => setSiteDraft(e.target.value)} aria-label="Collab site address" />
                <button className="btn btn-secondary" onClick={() => void saveSite()}>Save</button>
              </div>
            </details>
          </section>

          <section className="card" aria-labelledby="collab-feed">
            <div className="section-title" id="collab-feed">
              Everyone's changes
              <span className="hud-caption">{feed ? `${feed.counts.total ?? 0} total · ${feed.counts.open ?? 0} in review · ${feed.counts.merged ?? 0} merged` : ""}</span>
              <button className="chat-inline" style={{ marginLeft: "auto" }} onClick={() => void loadFeed(true)}>Refresh</button>
            </div>
            <div className="segmented review__filters" role="group" aria-label="Filter" style={{ marginBottom: 10 }}>
              {[["all", "All"], ["open", "○ In review"], ["merged", "✓ Merged"], ["feedback", "✎ Feedback"], ["code", "Code"], ["tab", "Tabs"], ["skill", "Skills"], ["agent", "Agents"]].map(([id, label]) => (
                <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>
              ))}
            </div>
            {feedError && <p className="field-row__hint" style={{ color: "var(--color-warn)" }}>▲ {feedError}</p>}
            {feed && shown.length === 0 && <p className="field-row__hint">No changes here yet.</p>}
            <ul className="review__list">
              {shown.map((i) => (
                <li key={i.id} className="review__item" style={{ gridTemplateColumns: "auto minmax(0,1fr) auto" }}>
                  <span aria-hidden="true" style={{ fontSize: 18, width: 26, textAlign: "center" }}>{KIND_ICON[i.kind] ?? "•"}</span>
                  <div className="review__body">
                    <b style={{ fontSize: 13.5 }}>{i.title}</b>
                    <span className="field-row__hint" style={{ margin: 0 }}>
                      {i.tester} · {i.kind} · {ago(i.updated_at || i.created_at)}{i.comments ? ` · ${i.comments} comments` : ""} ·{" "}
                      <a href={i.url} target="_blank" rel="noopener noreferrer">GitHub ↗</a>
                    </span>
                    {i.summary && <p className="review__reasons">{i.summary}</p>}
                    {i.files.length > 0 && <div className="review__meta">{i.files.slice(0, 6).map((f) => <code key={f}>{f}</code>)}</div>}
                  </div>
                  <span className={`chip review__rec is-${i.status === "merged" ? "approve" : i.status === "closed" ? "deny" : ""}`}>
                    {i.kind === "feedback" && i.status === "open" ? "✎ Open" : STATUS_TEXT[i.status] ?? i.status}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
