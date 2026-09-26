/** Settings → Storage: how much space Nyx uses, what is trimmed for you, and leftovers you may remove.
 *
 * Owner, 2026-09-15: "make sure it doesn't take too much storage. I don't want my entire computer
 * getting too large." Caches and backups are trimmed automatically; memories, uploads and chats are
 * never deleted from here; old build folders are removed only after you confirm each one.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface Entry { label: string; bytes: number; kind: "yours" | "trimmed" | "fixed"; note: string }
interface Leftover { id: string; label: string; path: string; bytes: number; why: string }
interface Report { growing: Entry[]; fixed: Entry[]; leftovers: Leftover[]; total_bytes: number; reclaimable_bytes: number; warnings: string[] }

function size(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(bytes >= 100 * 1024 ** 2 ? 0 : 1)} MB`;
  return `${Math.max(0, Math.round(bytes / 1024))} KB`;
}

const KIND_TEXT: Record<Entry["kind"], string> = { yours: "Kept", trimmed: "Trimmed automatically", fixed: "Needed" };

export function StorageSection() {
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<Report>("/api/storage", 120_000);
    if (result.ok) setReport(result.data); else setMessage(result.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function clean() {
    setBusy("clean");
    const result = await api.post<{ result: { freed_total: number }; report: Report }>("/api/storage/clean", {}, 120_000);
    setBusy(null);
    if (!result.ok) { setMessage(result.error); return; }
    setReport(result.data.report);
    setMessage(result.data.result.freed_total > 0 ? `Freed ${size(result.data.result.freed_total)}.` : "Everything is already within its budget.");
  }

  async function remove(item: Leftover) {
    setBusy(item.id);
    const result = await api.del<{ freed: number; report: Report }>(`/api/storage/leftovers/${item.id}`);
    setBusy(null);
    setConfirming(null);
    if (!result.ok) { setMessage(result.error); return; }
    setReport(result.data.report);
    setMessage(`Removed ${item.label} — freed ${size(result.data.freed)}.`);
  }

  const rows = report ? [...report.growing, ...report.fixed] : [];
  const largest = Math.max(1, ...rows.map((r) => r.bytes), ...(report?.leftovers ?? []).map((l) => l.bytes));

  return (
    <section className="storage">
      <div className="storage__head">
        <div>
          <h2>Storage</h2>
          <p className="muted">
            {report ? `Nyx uses ${size(report.total_bytes)} on this PC${report.reclaimable_bytes ? `, including ${size(report.reclaimable_bytes)} of old leftovers you can remove` : ""}.` : "Measuring…"}
          </p>
        </div>
        <button className="btn btn-secondary" onClick={() => void clean()} disabled={busy !== null}>{busy === "clean" ? "Cleaning…" : "Clean Up Now"}</button>
      </div>
      {report?.warnings.map((w) => <p key={w} className="storage__warn" role="alert">▲ {w}</p>)}
      {report && (
        <ul className="storage__list">
          {rows.map((row) => (
            <li key={row.label} className="storage__row">
              <div className="storage__label"><b>{row.label}</b><span className="muted">{KIND_TEXT[row.kind]} · {row.note}</span></div>
              <div className="storage__bar" aria-hidden="true"><span style={{ width: `${Math.max(1, (row.bytes / largest) * 100)}%` }} className={`is-${row.kind}`} /></div>
              <span className="storage__size">{size(row.bytes)}</span>
            </li>
          ))}
        </ul>
      )}
      {report && report.leftovers.length > 0 && (
        <>
          <h3>Old leftovers</h3>
          <p className="muted">Not used by Nyx. Nothing here is removed unless you confirm it.</p>
          <ul className="storage__list">
            {report.leftovers.map((item) => (
              <li key={item.id} className="storage__row">
                <div className="storage__label"><b>{item.label}</b><span className="muted" title={item.path}>{item.why}</span></div>
                <span className="storage__size">{size(item.bytes)}</span>
                {confirming === item.id ? (
                  <span className="storage__confirm">
                    <button className="btn btn-danger" disabled={busy !== null} onClick={() => void remove(item)}>{busy === item.id ? "Removing…" : "Remove Permanently"}</button>
                    <button className="btn btn-secondary" onClick={() => setConfirming(null)}>Keep</button>
                  </span>
                ) : (
                  <button className="btn btn-secondary" onClick={() => setConfirming(item.id)}>Remove…</button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {message && <p className="muted" aria-live="polite">{message}</p>}
    </section>
  );
}
