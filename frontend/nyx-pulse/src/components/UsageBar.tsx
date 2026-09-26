/** How much of the answering API's limit is left — shown only when that API reports one (Request G6).
 *
 * Numbers come from the provider (rate-limit headers, a quota error, a balance
 * endpoint) via /api/usage/limits; nothing is estimated here. No limits → no bar.
 */

import { useEffect, useState } from "react";
import { api } from "../api";

interface Limit {
  kind: "requests" | "tokens";
  window: string;
  limit: number;
  remaining: number;
  reset_at?: number | null;
  source: string;
}

interface Snapshot {
  provider: string;
  limits: Limit[];
  balance: { amount: number; currency: string; available: boolean } | null;
}

const WINDOW: Record<string, string> = { day: "today", hour: "this hour", minute: "this minute" };

function fmt(n: number): string {
  return n >= 10000 ? `${Math.round(n / 1000)}k` : n.toLocaleString();
}

function resetIn(at?: number | null): string {
  if (!at) return "";
  const seconds = Math.max(0, at - Date.now() / 1000);
  if (seconds < 90) return `resets in ${Math.ceil(seconds)} s`;
  if (seconds < 5400) return `resets in ${Math.round(seconds / 60)} min`;
  return `resets in ${Math.round(seconds / 3600)} h`;
}

export function UsageBar({ provider, refreshKey }: { provider: string; refreshKey?: string }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  useEffect(() => {
    if (!provider) { setSnapshot(null); return; }
    let alive = true;
    void api.get<Snapshot>(`/api/usage/limits?provider=${encodeURIComponent(provider)}`).then((result) => {
      if (alive) setSnapshot(result.ok ? result.data : null);
    });
    return () => { alive = false; };
  }, [provider, refreshKey]);

  if (!snapshot || (snapshot.limits.length === 0 && !snapshot.balance)) return null;
  const main = snapshot.limits[0];

  return (
    <div className="usage-bar" aria-label={`${provider} usage`}>
      {main && (() => {
        const left = Math.max(0, Math.min(1, main.remaining / main.limit));
        const tone = left < 0.05 ? "is-danger" : left < 0.2 ? "is-warn" : "";
        const label = `${fmt(main.remaining)} of ${fmt(main.limit)} ${main.kind} left ${WINDOW[main.window] ?? ""}`.trim();
        return (
          <>
            <div className="usage-bar__text">
              <span><b>{provider}</b> · {label}</span>
              <span className="usage-bar__meta">{resetIn(main.reset_at)}{main.source === "counted" ? " · counted by Nyx" : ""}</span>
            </div>
            <div
              className={`usage-bar__track ${tone}`}
              role="meter"
              aria-valuemin={0}
              aria-valuemax={main.limit}
              aria-valuenow={main.remaining}
              aria-valuetext={label}
            >
              <div className="usage-bar__fill" style={{ width: `${left * 100}%` }} />
            </div>
          </>
        );
      })()}
      {snapshot.limits.slice(1).map((l) => (
        <div key={`${l.kind}:${l.window}`} className="usage-bar__meta">
          {fmt(l.remaining)} of {fmt(l.limit)} {l.kind} left {WINDOW[l.window] ?? ""} {resetIn(l.reset_at) && `· ${resetIn(l.reset_at)}`}
        </div>
      ))}
      {snapshot.balance && (
        <div className={`usage-bar__meta${snapshot.balance.available ? "" : " is-danger-text"}`}>
          <b>{provider}</b> balance: {snapshot.balance.amount.toFixed(2)} {snapshot.balance.currency}
          {!snapshot.balance.available && " — empty, requests will fail"}
        </div>
      )}
    </div>
  );
}
