/** Studio Glass: the profile and calendar cards at the top of the right column (owner, 2026-10-10 — reference's
 * profile / month calendar / "Scheduled"). Ichos's activity list sits under them as the "Scheduled" part, so nothing
 * that was on the right before is lost. The calendar is local (no account needed); today is the orange day.
 */

import { useMemo, useState } from "react";

const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function Month() {
  const today = new Date();
  const [shown, setShown] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const cells = useMemo(() => {
    const first = shown.getDay();
    const count = new Date(shown.getFullYear(), shown.getMonth() + 1, 0).getDate();
    return [...Array(first).fill(0), ...Array.from({ length: count }, (_, i) => i + 1)] as number[];
  }, [shown]);
  const isToday = (d: number) => d === today.getDate() && shown.getMonth() === today.getMonth() && shown.getFullYear() === today.getFullYear();
  const move = (by: number) => setShown(new Date(shown.getFullYear(), shown.getMonth() + by, 1));
  return (
    <div className="studio-cal">
      <div className="studio-cal__head">
        <b>{shown.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</b>
        <span>
          <button type="button" aria-label="Previous month" onClick={() => move(-1)}>‹</button>
          <button type="button" aria-label="Next month" onClick={() => move(1)}>›</button>
        </span>
      </div>
      <div className="studio-cal__grid" role="grid">
        {DAYS.map((d) => <span key={d} className="studio-cal__dow">{d}</span>)}
        {cells.map((d, i) => d === 0
          ? <span key={`b${i}`} />
          : <span key={d} className={`studio-cal__day${isToday(d) ? " is-today" : ""}`} aria-current={isToday(d) ? "date" : undefined}>{d}</span>)}
      </div>
    </div>
  );
}

export function StudioSide({ name, role, memories, today, onProfile }: { name: string; role: string; memories?: number; today?: number; onProfile: () => void }) {
  return (
    <div className="studio-side__cards">
      <button type="button" className="studio-profile" onClick={onProfile} title="Accounts and settings">
        <span className="studio-profile__avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
        <span className="studio-profile__who"><b>{name}</b><small>{role}</small></span>
      </button>
      <div className="studio-facts">
        <span><b>{memories?.toLocaleString() ?? "—"}</b><small>Memories</small></span>
        <span><b>{new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</b><small>Local time</small></span>
        <span><b>{today?.toLocaleString() ?? "—"}</b><small>New today</small></span>
      </div>
      <Month />
    </div>
  );
}
