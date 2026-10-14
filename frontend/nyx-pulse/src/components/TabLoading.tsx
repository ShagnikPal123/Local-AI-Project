/** The one big loader every "opening…" and "loading…" state uses (Fixer Upper S27).
 *
 * The owner asked for loading that is big and visibly changing. A fake percentage would lie, so the bar creeps toward
 * but never reaches the end (it only completes when the content replaces it), and the words change with the real
 * time spent waiting: a slow first open is told apart from a stuck one.
 */

import { useEffect, useState } from "react";
import { IchosOrb } from "./orbs/IchosOrb";
import { orbStateFor } from "./orbs/orbState";

/** Share of the bar filled after `seconds`: quick at first, slowing, never past 94 so it never claims to be done. */
export function creepFraction(seconds: number): number {
  return 0.94 * (1 - Math.exp(-seconds / 4));
}

/** What to say after waiting this long; the first thing said is simply what is loading. */
export function waitingLine(what: string, seconds: number): string {
  if (seconds < 3) return `${what}…`;
  if (seconds < 8) return `${what}… the first open is the slowest`;
  if (seconds < 20) return `${what}… still working, this is taking longer than usual`;
  return `${what}… still no answer. If this stays, the engine may be busy or off`;
}

function useSecondsWaited(): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds((Date.now() - started) / 1000), 250);
    return () => window.clearInterval(timer);
  }, []);
  return seconds;
}

/** A thin bar that creeps along while something loads. */
export function LoadingBar({ seconds }: { seconds: number }) {
  return (
    <div className="loading-bar" aria-hidden="true">
      <div className="loading-bar__fill" style={{ width: `${Math.round(creepFraction(seconds) * 100)}%` }} />
    </div>
  );
}

/** The orb, the bar and a line of words that changes as the wait goes on. */
export function TabLoading({ what = "Opening", size = 72, compact = false }: { what?: string; size?: number; compact?: boolean }) {
  const seconds = useSecondsWaited();
  return (
    <div className={`tab-loading orb-loading${compact ? " is-compact" : ""}`} role="status" aria-live="polite">
      <IchosOrb state={orbStateFor(what, "breathing")} size={size} decorative />
      <span className="tab-loading__text">{waitingLine(what, seconds)}</span>
      <LoadingBar seconds={seconds} />
    </div>
  );
}
